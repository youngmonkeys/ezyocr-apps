from ezyocr.recognition.backends.base import OcrBackend, has_module
from ezyocr.recognition.line import box_from_points, make_lines


class RapidBackend(OcrBackend):
    name = "rapidocr"

    def __init__(self):
        self._ocr = None

    @classmethod
    def available(cls):
        return has_module("rapidocr")

    def load(self, options):
        from rapidocr import RapidOCR

        self._ocr = RapidOCR(config_path=options.get("config_path") or None, params=options.get("params") or None)

    def read_lines(self, image):
        result = self._ocr(image)
        if result.boxes is None or result.txts is None:
            return []
        return make_lines(
            (text, score, box_from_points(points))
            for text, score, points in zip(result.txts, result.scores, result.boxes)
        )
