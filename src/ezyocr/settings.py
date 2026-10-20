import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from urllib.parse import urlsplit

from ezyocr.paths import resource_path, settings_file

logger = logging.getLogger(__name__)


@dataclass
class WebSettings:
    admin_url: str = ""
    username: str = ""
    title: str = ""
    width: int = 1280
    height: int = 820
    session_check_seconds: float = 3.0
    clear_session_on_start: bool = False


@dataclass
class UploadSettings:
    enabled: bool = True
    media_path: str = "/api/v1/media/add?avatar=false&notPublic=true"
    timeout_seconds: float = 60.0
    max_attempts: int = 10


@dataclass
class CameraSettings:
    index: int = 0
    width: int = 3840
    height: int = 2160
    detect_width: int = 1280
    still_ms: int = 250
    motion_threshold: float = 4.0
    require_barcode: bool = True
    ocr_fallback_ms: int = 1200
    save_captures: bool = True
    captures_dir: str = ""
    captures_keep_days: int = 30


@dataclass
class SoundSettings:
    enabled: bool = True
    success: str = "/System/Library/Sounds/Glass.aiff"
    warning: str = "/System/Library/Sounds/Funk.aiff"


@dataclass
class OcrSettings:
    backend: str = "paddleocr"
    options: dict = field(default_factory=dict)
    use_doc_orientation_classify: bool = True


@dataclass
class PrinterSettings:
    name: str = ""
    language: str = "zpl"
    label_width_mm: int = 60
    label_height_mm: int = 40
    dpi: int = 203
    page_printer_name: str = ""
    show_print_dialog: bool = True


@dataclass
class BusinessScriptSettings:
    source: str = "default"
    script_id: int = 0


@dataclass
class Settings:
    debug: bool = False
    language: str = "auto"
    web: WebSettings = field(default_factory=WebSettings)
    upload: UploadSettings = field(default_factory=UploadSettings)
    camera: CameraSettings = field(default_factory=CameraSettings)
    ocr: OcrSettings = field(default_factory=OcrSettings)
    printer: PrinterSettings = field(default_factory=PrinterSettings)
    sound: SoundSettings = field(default_factory=SoundSettings)
    business_script: BusinessScriptSettings = field(default_factory=BusinessScriptSettings)

    @property
    def configured(self):
        return bool(self.web.admin_url.strip())

    def to_dict(self):
        return asdict(self)


SECTIONS = {
    "web": WebSettings,
    "upload": UploadSettings,
    "camera": CameraSettings,
    "ocr": OcrSettings,
    "printer": PrinterSettings,
    "sound": SoundSettings,
    "business_script": BusinessScriptSettings,
}


def settings_from_dict(data):
    data = _migrate(data)
    values = {}
    for f in fields(Settings):
        if f.name not in data:
            continue
        section = SECTIONS.get(f.name)
        values[f.name] = _section_from_dict(section, data[f.name]) if section else data[f.name]
    return Settings(**values)


def _migrate(data):
    web = data.get("web")
    if not isinstance(web, dict) or web.get("admin_url") or not web.get("station_url"):
        return data
    return {**data, "web": {**web, "admin_url": origin_of(web["station_url"])}}


def origin_of(url):
    parts = urlsplit(str(url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def _section_from_dict(cls, data):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (data or {}).items() if k in names})


def merge(base, override):
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


class SettingsStore:
    def __init__(self, path=None):
        self.path = path or settings_file()

    def load(self):
        data = merge(_read_json(resource_path("default_settings.json")), _platform_defaults())
        if self.path.exists():
            data = merge(data, _read_json(self.path))
        return settings_from_dict(data)

    def save(self, settings):
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings.to_dict(), f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)
        logger.info("Settings saved to %s", self.path)


def _platform_defaults():
    if sys.platform != "win32":
        return {}
    media = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Media")
    return {
        "sound": {
            "success": os.path.join(media, "chimes.wav"),
            "warning": os.path.join(media, "Windows Exclamation.wav"),
        }
    }


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        logger.exception("Invalid settings file %s", path)
        return {}
