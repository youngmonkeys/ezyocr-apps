import logging
import threading
import time

from ezyocr.business.base import RecognitionContext
from ezyocr.i18n import t
from ezyocr.recognition.backends import DEFAULT_BACKEND, BackendUnavailable, create_backend

logger = logging.getLogger(__name__)


class OcrEngine:
    def __init__(self, settings):
        self._settings = settings
        self._backend = None
        self._error = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._read_count = 0
        self._read_total_ms = 0.0

    @property
    def name(self):
        return self._settings.backend or DEFAULT_BACKEND

    @property
    def state(self):
        if self._error:
            return "error"
        return "ready" if self._ready.is_set() else "loading"

    @property
    def error(self):
        return self._error

    @property
    def average_ms(self):
        if not self._read_count:
            return None
        return int(self._read_total_ms / self._read_count)

    def load(self):
        with self._lock:
            if self._backend is not None:
                return
            try:
                backend = create_backend(self.name)
                started = time.perf_counter()
                backend.load(self._options())
                self._backend = backend
                logger.info("OCR backend %s loaded in %.2fs", self.name, time.perf_counter() - started)
                self._error = None
            except BackendUnavailable as e:
                self._error = t("error.ocr_backend_unavailable", name=t(f"ocr.backend.{e.name}"))
                logger.error("OCR backend %s is not available in this build", e.name)
                raise
            except Exception as e:
                self._error = str(e)
                logger.exception("Cannot load OCR backend %s", self.name)
                raise
            finally:
                self._ready.set()

    def _options(self):
        options = {"use_doc_orientation_classify": self._settings.use_doc_orientation_classify}
        per_backend = self._settings.options if isinstance(self._settings.options, dict) else {}
        options.update(per_backend.get(self.name) or {})
        return options

    def wait_ready(self, timeout=None):
        return self._ready.wait(timeout) and self._backend is not None

    def read_lines(self, image):
        with self._lock:
            started = time.perf_counter()
            lines = self._backend.read_lines(image)
            self._read_total_ms += (time.perf_counter() - started) * 1000
            self._read_count += 1
        return lines


class Recognizer:
    def __init__(self, engine, runner):
        self._engine = engine
        self._runner = runner

    def recognize(self, image, barcode=None):
        started = time.perf_counter()
        lines = self._engine.read_lines(image)
        result = self._runner.extract(RecognitionContext(lines=lines, image=image, barcode=barcode))
        result["ocr_texts"] = [line.text for line in lines]
        result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return result
