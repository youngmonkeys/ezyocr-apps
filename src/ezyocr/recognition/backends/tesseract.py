import cv2

from ezyocr.recognition.backends.base import OcrBackend, has_module
from ezyocr.recognition.line import make_lines

DEFAULT_LANG = "chi_sim+eng"
NO_SPACE_LANGS = ("chi", "jpn")


class TesseractBackend(OcrBackend):
    name = "tesseract"

    def __init__(self):
        self._pytesseract = None
        self._lang = DEFAULT_LANG
        self._config = ""
        self._separator = ""

    @classmethod
    def available(cls):
        return has_module("pytesseract")

    def load(self, options):
        import pytesseract

        if options.get("tesseract_cmd"):
            pytesseract.pytesseract.tesseract_cmd = options["tesseract_cmd"]
        pytesseract.get_tesseract_version()
        self._pytesseract = pytesseract
        self._lang = options.get("lang") or DEFAULT_LANG
        self._config = options.get("config") or ""
        self._separator = "" if self._lang.startswith(NO_SPACE_LANGS) else " "

    def read_lines(self, image):
        data = self._pytesseract.image_to_data(
            cv2.cvtColor(image, cv2.COLOR_BGR2RGB),
            lang=self._lang,
            config=self._config,
            output_type=self._pytesseract.Output.DICT,
        )
        groups = {}
        for i, text in enumerate(data["text"]):
            score = float(data["conf"][i])
            if score < 0 or not text.strip():
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            groups.setdefault(key, []).append(
                (text.strip(), score, data["left"][i], data["top"][i], data["width"][i], data["height"][i])
            )
        items = []
        for words in groups.values():
            box = (
                min(w[2] for w in words),
                min(w[3] for w in words),
                max(w[2] + w[4] for w in words),
                max(w[3] + w[5] for w in words),
            )
            score = sum(w[1] for w in words) / len(words) / 100
            items.append((self._separator.join(w[0] for w in words), score, box))
        return make_lines(items)
