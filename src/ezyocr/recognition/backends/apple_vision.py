import sys

import cv2

from ezyocr.recognition.backends.base import OcrBackend, has_module
from ezyocr.recognition.line import make_lines

DEFAULT_LANGUAGES = ("zh-Hans", "en-US")
JPEG_QUALITY = 95


class AppleVisionBackend(OcrBackend):
    name = "apple_vision"

    def __init__(self):
        self._languages = list(DEFAULT_LANGUAGES)
        self._level = None
        self._language_correction = False

    @classmethod
    def available(cls):
        return sys.platform == "darwin" and has_module("Vision")

    def load(self, options):
        import Vision

        self._languages = list(options.get("languages") or DEFAULT_LANGUAGES)
        self._language_correction = bool(options.get("language_correction", False))
        if options.get("recognition_level") == "fast":
            self._level = Vision.VNRequestTextRecognitionLevelFast
        else:
            self._level = Vision.VNRequestTextRecognitionLevelAccurate
        request = self._new_request()
        supported, _ = request.supportedRecognitionLanguagesAndReturnError_(None)
        missing = [code for code in self._languages if code not in set(supported or ())]
        if missing:
            raise RuntimeError(f"Apple Vision does not support {', '.join(missing)} on this macOS version")

    def read_lines(self, image):
        import objc
        from Foundation import NSData
        import Vision

        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise RuntimeError("Cannot encode image for Apple Vision")
        height, width = image.shape[:2]
        items = []
        with objc.autorelease_pool():
            data = NSData.dataWithBytes_length_(encoded.tobytes(), len(encoded))
            handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
            request = self._new_request()
            success, error = handler.performRequests_error_([request], None)
            if not success:
                raise RuntimeError(f"Apple Vision failed: {error}")
            for observation in request.results() or ():
                candidates = observation.topCandidates_(1)
                if not candidates:
                    continue
                candidate = candidates[0]
                box = observation.boundingBox()
                x1 = box.origin.x * width
                x2 = (box.origin.x + box.size.width) * width
                y1 = (1 - box.origin.y - box.size.height) * height
                y2 = (1 - box.origin.y) * height
                items.append((str(candidate.string()), float(candidate.confidence()), (x1, y1, x2, y2)))
        return make_lines(items)

    def _new_request(self):
        import Vision

        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(self._level)
        request.setRecognitionLanguages_(self._languages)
        request.setUsesLanguageCorrection_(self._language_correction)
        return request
