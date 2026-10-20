import asyncio
import sys

import cv2

from ezyocr.recognition.backends.base import OcrBackend, has_module
from ezyocr.recognition.line import make_lines

DEFAULT_LANGUAGE = "zh-Hans-CN"
NO_SPACE_LANGUAGES = {"zh", "ja"}
MODULES = (
    "winrt.windows.media.ocr",
    "winrt.windows.globalization",
    "winrt.windows.graphics.imaging",
    "winrt.windows.storage.streams",
)
WORD_SCORE = 1.0


class WindowsOcrBackend(OcrBackend):
    name = "windows_ocr"

    def __init__(self):
        self._engine = None
        self._max_dimension = 0
        self._separator = ""

    @classmethod
    def available(cls):
        return sys.platform == "win32" and all(has_module(name) for name in MODULES)

    def load(self, options):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        tag = options.get("language") or DEFAULT_LANGUAGE
        engine = OcrEngine.try_create_from_language(Language(tag))
        if engine is None:
            raise RuntimeError(f"Windows OCR language {tag} is not installed")
        self._engine = engine
        self._max_dimension = OcrEngine.max_image_dimension
        self._separator = "" if tag.split("-")[0].lower() in NO_SPACE_LANGUAGES else " "

    def read_lines(self, image):
        height, width = image.shape[:2]
        scale = min(1.0, self._max_dimension / max(height, width))
        if scale < 1.0:
            image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        result = asyncio.run(self._recognize(image))
        items = []
        for line in result.lines:
            words = list(line.words)
            if not words:
                continue
            rects = [word.bounding_rect for word in words]
            box = (
                min(r.x for r in rects) / scale,
                min(r.y for r in rects) / scale,
                max(r.x + r.width for r in rects) / scale,
                max(r.y + r.height for r in rects) / scale,
            )
            items.append((self._separator.join(word.text for word in words), WORD_SCORE, box))
        return make_lines(items)

    async def _recognize(self, image):
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter

        height, width = image.shape[:2]
        writer = DataWriter()
        writer.write_bytes(cv2.cvtColor(image, cv2.COLOR_BGR2BGRA).tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, width, height, BitmapAlphaMode.PREMULTIPLIED
        )
        return await self._engine.recognize_async(bitmap)
