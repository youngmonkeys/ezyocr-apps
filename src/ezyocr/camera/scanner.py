import logging
import sys
import threading
import time
from datetime import datetime

import cv2

from ezyocr.paths import debug_captures_dir
from ezyocr.recognition.extract import decode_barcodes, tracking_from_barcodes

logger = logging.getLogger(__name__)

REOPEN_DELAY_SECONDS = 3.0
PREVIEW_INTERVAL_SECONDS = 0.3


class CameraScanner:
    def __init__(self, settings, on_capture, on_state, on_preview=None):
        self._settings = settings
        self._on_capture = on_capture
        self._on_state = on_state
        self._on_preview = on_preview
        self.require_barcode = settings.require_barcode
        self._stop = threading.Event()
        self._capture_now = threading.Event()
        self._thread = None

    def capture_now(self):
        self._capture_now.set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            capture = self._open()
            if capture is None:
                self._on_state("error")
                self._stop.wait(REOPEN_DELAY_SECONDS)
                continue
            self._on_state("on")
            try:
                self._scan(capture)
            except Exception:
                logger.exception("Camera loop failed")
            finally:
                capture.release()
            if not self._stop.is_set():
                self._on_state("error")
                self._stop.wait(REOPEN_DELAY_SECONDS)
        self._on_state("off")

    def _open(self):
        backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
        capture = cv2.VideoCapture(self._settings.index, backend)
        if not capture.isOpened():
            logger.warning("Cannot open camera %s", self._settings.index)
            capture.release()
            return None
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._settings.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._settings.height)
        logger.info(
            "Camera %s opened at %dx%d",
            self._settings.index,
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        return capture

    def _scan(self, capture):
        previous = None
        still_since = None
        captured = False
        reported = False
        seen_motion = False
        last_preview = 0.0
        while not self._stop.is_set():
            ok, frame = capture.read()
            if not ok:
                logger.warning("Camera stopped delivering frames")
                return
            small = self._downscale(frame)
            if self._on_preview and time.monotonic() - last_preview >= PREVIEW_INTERVAL_SECONDS:
                last_preview = time.monotonic()
                self._on_preview(small)
            if self._capture_now.is_set():
                self._capture_now.clear()
                tracking, _ = tracking_from_barcodes(*decode_barcodes(small))
                self._on_capture(frame, tracking, True)
                previous = None
                captured = True
                continue
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            moving = previous is not None and cv2.absdiff(gray, previous).mean() > self._settings.motion_threshold
            previous = gray
            now = time.monotonic()
            if moving:
                still_since = now
                captured = False
                reported = False
                seen_motion = True
                continue
            if still_since is None:
                still_since = now
            still_ms = (now - still_since) * 1000
            if captured or still_ms < self._settings.still_ms:
                continue
            linear, matrix = decode_barcodes(small)
            tracking, _ = tracking_from_barcodes(linear, matrix)
            if not tracking and self.require_barcode:
                if not reported:
                    reported = True
                    self._report_no_barcode(frame, gray, linear, matrix)
                fallback_ms = self._settings.ocr_fallback_ms
                if not (seen_motion and fallback_ms > 0 and still_ms >= fallback_ms):
                    continue
                logger.debug("No barcode after %.0f ms still, running OCR anyway", still_ms)
            else:
                logger.debug("Still frame with tracking %s, barcodes=%s qr=%s", tracking, linear, matrix)
            seen_motion = False
            captured = True
            self._on_capture(frame, tracking, False)
            previous = None

    def _report_no_barcode(self, frame, gray, linear, matrix):
        if not logger.isEnabledFor(logging.DEBUG):
            return
        height, width = frame.shape[:2]
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
        path = debug_captures_dir(self._settings.captures_dir) / f"no-barcode-{datetime.now():%Y%m%d-%H%M%S-%f}.jpg"
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        logger.debug(
            "Still frame without tracking barcode: size=%dx%d brightness=%.0f sharpness=%.0f barcodes=%s qr=%s saved=%s",
            width, height, gray.mean(), sharpness, linear, matrix, path,
        )

    def _downscale(self, frame):
        height, width = frame.shape[:2]
        if width <= self._settings.detect_width:
            return frame
        scale = self._settings.detect_width / width
        return cv2.resize(frame, (self._settings.detect_width, int(height * scale)), interpolation=cv2.INTER_AREA)

