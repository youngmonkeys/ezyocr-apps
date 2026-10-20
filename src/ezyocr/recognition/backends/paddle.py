from ezyocr.recognition.backends.base import OcrBackend, has_module
from ezyocr.recognition.line import make_lines
from ezyocr.recognition.models import configure_paddlex_env, install_bundled_models

DEFAULT_LANG = "ch"
DEFAULT_ENGINE = "onnxruntime"
MODEL_OPTIONS = (
    "ocr_version",
    "text_detection_model_name",
    "text_detection_model_dir",
    "text_recognition_model_name",
    "text_recognition_model_dir",
)


class PaddleBackend(OcrBackend):
    name = "paddleocr"

    def __init__(self):
        self._ocr = None

    @classmethod
    def available(cls):
        return has_module("paddleocr")

    def load(self, options):
        install_bundled_models(configure_paddlex_env())
        from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(
            lang=options.get("lang") or DEFAULT_LANG,
            engine=options.get("engine") or DEFAULT_ENGINE,
            use_doc_orientation_classify=bool(options.get("use_doc_orientation_classify", True)),
            use_doc_unwarping=False,
            use_textline_orientation=bool(options.get("use_textline_orientation", False)),
            **{key: options[key] for key in MODEL_OPTIONS if options.get(key)},
        )

    def read_lines(self, image):
        result = next(iter(self._ocr.predict(image)))
        return lines_from_paddle(result.json["res"])


def lines_from_paddle(data):
    return make_lines(zip(data["rec_texts"], data["rec_scores"], data["rec_boxes"]))
