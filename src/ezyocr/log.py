import logging
import sys
from logging.handlers import RotatingFileHandler

from ezyocr.paths import logs_dir

LOG_FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"


def setup_logging(debug=False):
    level = logging.DEBUG if debug else logging.INFO
    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        logs_dir() / "station.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers[:] = [file_handler, console_handler]
    for noisy in ("urllib3", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
