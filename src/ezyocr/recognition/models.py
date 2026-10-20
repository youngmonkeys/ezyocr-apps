import logging
import os
import shutil
import sys

from ezyocr.paths import paddlex_home, resource_path

logger = logging.getLogger(__name__)

BUNDLED_MODELS_DIR = resource_path("models")


def configure_paddlex_env():
    home = paddlex_home()
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(home)
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    return home


def install_bundled_models(home):
    if not BUNDLED_MODELS_DIR.is_dir():
        logger.warning("No bundled models at %s, PaddleOCR will download them", BUNDLED_MODELS_DIR)
        return
    target_root = home / "official_models"
    target_root.mkdir(parents=True, exist_ok=True)
    for source in sorted(p for p in BUNDLED_MODELS_DIR.iterdir() if p.is_dir()):
        target = target_root / source.name
        if target.is_symlink() and target.resolve() != source.resolve():
            target.unlink()
        if target.exists():
            continue
        if sys.platform == "win32":
            shutil.copytree(source, target)
        else:
            target.symlink_to(source, target_is_directory=True)
        logger.info("Installed model %s", source.name)
