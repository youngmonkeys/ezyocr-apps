import base64
import logging
import threading
from collections import OrderedDict
from datetime import datetime

import cv2
import numpy as np

from ezyocr.business.loader import ScriptRunner
from ezyocr.camera.scanner import CameraScanner
from ezyocr.i18n import t
from ezyocr.paths import captures_dir, outbox_file
from ezyocr.printing.printer import LabelPrinter
from ezyocr.recognition.extract import decode_barcodes, tracking_from_barcodes
from ezyocr.recognition.engine import OcrEngine, Recognizer
from ezyocr.sound import SoundPlayer
from ezyocr.storage.captures import CaptureCleaner
from ezyocr.storage.outbox import Outbox
from ezyocr.storage.uploads import UploadQueue
from ezyocr.upload.uploader import MediaUploader

logger = logging.getLogger(__name__)

ENGINE_WAIT_SECONDS = 120
RECENT_RESULTS_LIMIT = 100
PREVIEW_WIDTH = 640
UPLOAD_READY_FALLBACK_SECONDS = 60


class RecognitionCore:
    def __init__(self, settings, notify, script, script_error=None, test_mode=False):
        self._settings = settings
        self._notify = notify
        self._test_mode = test_mode
        self._runner = ScriptRunner(script, script_error, self._on_script_error)
        self._engine = OcrEngine(settings.ocr)
        self._recognizer = Recognizer(self._engine, self._runner)
        self._outbox = Outbox(outbox_file())
        self._uploads = None
        self._uploader = None
        link_path = script.media_link_path
        if not test_mode and settings.upload.enabled and settings.web.admin_url and link_path:
            self._uploads = UploadQueue(outbox_file())
            self._uploader = MediaUploader(
                settings.web.admin_url,
                settings.upload,
                link_path,
                self._uploads,
                settings.camera.save_captures,
                self._on_uploads_changed,
            )
        self._preview_enabled = test_mode
        self._camera_enabled = True
        self._scanner = CameraScanner(settings.camera, self._on_capture, self._on_camera_state, self._on_preview)
        if test_mode:
            self._scanner.require_barcode = False
        self._printer = LabelPrinter(settings.printer)
        self._sound = SoundPlayer(settings.sound)
        self._lock = threading.RLock()
        self._recent = OrderedDict()
        self._state = {
            "test_mode": test_mode,
            "require_barcode": self._scanner.require_barcode,
            "ocr": "loading",
            "ocr_backend": self._engine.name,
            "ocr_error": None,
            "ocr_avg_ms": None,
            "business_script": script.name,
            "business_script_error": script_error,
            "camera": "off",
            "camera_enabled": True,
            "running": False,
            "pending": self._outbox.count(),
            "uploads": self._uploads.count() if self._uploads else 0,
        }
        if self._uploader:
            self._uploader.start()
        self._cleaner = CaptureCleaner(settings.camera, self._uploads.file_paths if self._uploads else None)
        self._cleaner.start()

    def warm_up(self):
        threading.Thread(target=self._load_engine, name="ocr-loader", daemon=True).start()

    def _load_engine(self):
        try:
            self._engine.load()
        except Exception:
            pass
        self._update(ocr=self._engine.state, ocr_error=self._engine.error)

    def start(self, access_token):
        with self._lock:
            if self._uploader:
                self._uploader.set_access_token(access_token)
            if self._state["running"]:
                return
            if self._camera_enabled:
                self._scanner.start()
            self._update(running=True)
            logger.info("Recognition core started")

    def start_test(self):
        with self._lock:
            if self._camera_enabled:
                self._scanner.start()
            self._update(running=True)
            logger.info("Recognition core started in camera test mode")

    def capture_now(self):
        self._scanner.capture_now()

    def recognize_file(self, path):
        frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(t("error.image_unreadable"))
        logger.info("Recognizing image file %s", path)
        threading.Thread(target=self._recognize_frame, args=(frame,), name="recognize-file", daemon=True).start()

    def _recognize_frame(self, frame):
        tracking, _ = tracking_from_barcodes(*decode_barcodes(frame))
        self._on_capture(frame, tracking, True)

    def set_preview(self, enabled):
        self._preview_enabled = self._test_mode or bool(enabled)

    def set_camera_enabled(self, enabled):
        with self._lock:
            enabled = bool(enabled)
            if enabled == self._camera_enabled:
                return
            self._camera_enabled = enabled
            if self._state["running"]:
                if enabled:
                    self._scanner.start()
                else:
                    self._scanner.stop()
            self._update(camera_enabled=enabled)
            logger.info("Camera %s", "enabled" if enabled else "disabled")

    def set_require_barcode(self, value):
        self._scanner.require_barcode = bool(value)
        self._update(require_barcode=self._scanner.require_barcode)

    def stop(self):
        with self._lock:
            self._stop_locked()

    def _stop_locked(self):
        if not self._state["running"]:
            return
        self._scanner.stop()
        if self._uploader:
            self._uploader.set_access_token(None)
        self._update(running=False)
        logger.info("Recognition core stopped")

    def shutdown(self):
        self.stop()
        self._cleaner.stop()
        if self._uploader:
            self._uploader.stop()
            self._uploads.close()
        self._outbox.close()

    def status(self):
        return dict(self._state)

    def pending_results(self):
        return self._outbox.pending()

    def ack_result(self, image_id, code=None):
        self._outbox.acknowledge(image_id)
        if self._uploader:
            code = (code or "").strip()
            if code:
                self._uploads.set_delivery_order_code(image_id, code)
                self._uploader.wake()
            else:
                self._uploader.discard(image_id)
        self._update(pending=self._outbox.count())

    def print_label(self, tracking_number, customer_code=None):
        if not customer_code:
            customer_code = (self._recent.get(tracking_number) or {}).get("customer_code")
        self._printer.print_label(tracking_number, customer_code)

    def _on_capture(self, frame, barcode, manual):
        self._notify("processing", {"tracking_number": barcode})
        if not self._engine.wait_ready(ENGINE_WAIT_SECONDS):
            self._notify("error", {"message": self._engine.error or t("error.engine_not_ready")})
            return
        captured_at = datetime.now().astimezone()
        image_id = f"{captured_at:%Y%m%d-%H%M%S-%f}"[:-3]
        try:
            result = self._recognizer.recognize(frame, barcode)
        except Exception:
            logger.exception("Recognition failed for %s", barcode)
            self._notify("error", {"message": t("error.recognition_failed"), "tracking_number": barcode})
            return
        self._update(ocr_avg_ms=self._engine.average_ms)
        ocr_texts = result.pop("ocr_texts", [])
        logger.debug("OCR texts: %s", ocr_texts)
        script = self._runner.script
        message = {
            "captured_at": captured_at.isoformat(timespec="milliseconds"),
            **result,
            "image_id": image_id,
        }
        key = message.get(script.key_field)
        logger.info("Recognized %s", message)
        if self._test_mode:
            logger.info("OCR texts: %s", ocr_texts)
        if self._preview_enabled:
            message["ocr_texts"] = ocr_texts
        if not manual and not self._accept_auto_result(script, message):
            return
        self._remember(key, message)
        queued = not self._test_mode and bool(key)
        upload = queued and self._uploader is not None
        image_path = captures_dir(self._settings.camera.captures_dir) / f"{image_id}.jpg"
        if queued:
            payload = {k: v for k, v in message.items() if k != "ocr_texts"}
            self._outbox.add(key, image_id, payload)
            if upload:
                self._uploads.add(image_id, str(image_path), UPLOAD_READY_FALLBACK_SECONDS)
            self._update(pending=self._outbox.count(), uploads=self._uploads.count() if upload else 0)
        self._notify("result", message)
        if script.is_complete(message):
            self._sound.success()
        else:
            self._sound.warning()
        if upload or self._settings.camera.save_captures:
            cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if upload:
            self._uploads.mark_ready(image_id)
            self._uploader.wake()

    def _on_preview(self, frame):
        if not self._preview_enabled:
            return
        height, width = frame.shape[:2]
        if width > PREVIEW_WIDTH:
            frame = cv2.resize(frame, (PREVIEW_WIDTH, int(height * PREVIEW_WIDTH / width)), interpolation=cv2.INTER_AREA)
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            self._notify("preview", {"image": "data:image/jpeg;base64," + base64.b64encode(jpeg.tobytes()).decode()})

    def _accept_auto_result(self, script, message):
        if not script.has_any_field(message):
            self._notify("empty", {"image_id": message["image_id"], "ocr_texts": message.get("ocr_texts", [])})
            return False
        return True

    def _remember(self, key, message):
        if not key:
            return
        self._recent[key] = message
        while len(self._recent) > RECENT_RESULTS_LIMIT:
            self._recent.popitem(last=False)

    def _on_script_error(self, error):
        self._update(business_script=self._runner.script.name, business_script_error=error)
        self._notify("error", {"message": error})

    def _on_uploads_changed(self):
        self._update(uploads=self._uploads.count())

    def _on_camera_state(self, state):
        self._update(camera=state)

    def _update(self, **changes):
        self._state.update(changes)
        self._notify("status", self.status())
