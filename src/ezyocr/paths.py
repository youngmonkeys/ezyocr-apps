import os
import sys
from pathlib import Path

APP_DIR_NAME = "EzyOCR"
PACKAGE_DIR = Path(__file__).resolve().parent


def resource_path(*parts):
    return PACKAGE_DIR.joinpath("resources", *parts)


def data_dir():
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return _ensure(base / APP_DIR_NAME)


def settings_file():
    return data_dir() / "settings.json"


def last_page_file():
    return data_dir() / "last_page.txt"


def logs_dir():
    if sys.platform == "darwin":
        return _ensure(Path.home() / "Library" / "Logs" / APP_DIR_NAME)
    return _ensure(data_dir() / "logs")


def default_captures_dir():
    return data_dir() / "captures"


def captures_dir(directory=""):
    custom = str(directory or "").strip()
    return _ensure(Path(custom).expanduser() if custom else default_captures_dir())


def debug_captures_dir(directory=""):
    return _ensure(captures_dir(directory) / "debug")


def business_scripts_dir():
    return _ensure(data_dir() / "business_scripts")


def updates_dir():
    return _ensure(data_dir() / "updates")


def outbox_file():
    return data_dir() / "outbox.sqlite3"


def paddlex_home():
    return _ensure(data_dir() / "paddlex")


def _ensure(path):
    path.mkdir(parents=True, exist_ok=True)
    return path
