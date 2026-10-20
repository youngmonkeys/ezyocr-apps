import logging

from ezyocr.recognition.backends.apple_vision import AppleVisionBackend
from ezyocr.recognition.backends.paddle import PaddleBackend
from ezyocr.recognition.backends.rapid import RapidBackend
from ezyocr.recognition.backends.tesseract import TesseractBackend
from ezyocr.recognition.backends.windows_ocr import WindowsOcrBackend

logger = logging.getLogger(__name__)

DEFAULT_BACKEND = PaddleBackend.name
BACKENDS = {
    cls.name: cls
    for cls in (PaddleBackend, RapidBackend, AppleVisionBackend, WindowsOcrBackend, TesseractBackend)
}


class BackendUnavailable(Exception):
    def __init__(self, name):
        super().__init__(name)
        self.name = name


def is_available(name):
    cls = BACKENDS.get(name)
    if cls is None:
        return False
    try:
        return cls.available()
    except Exception:
        logger.exception("Cannot check OCR backend %s", name)
        return False


def available_backends():
    return [name for name in BACKENDS if is_available(name)]


def create_backend(name):
    if not is_available(name):
        raise BackendUnavailable(name)
    return BACKENDS[name]()
