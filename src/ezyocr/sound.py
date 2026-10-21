import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class SoundPlayer:
    def __init__(self, settings):
        self._settings = settings

    def success(self):
        self._play(self._settings.success)

    def warning(self):
        self._play(self._settings.warning)

    def _play(self, path):
        if not self._settings.enabled or not path:
            return
        if not Path(path).is_file():
            logger.warning("Sound file not found: %s", path)
            return
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform == "win32":
                import winsound

                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                command = _linux_player(path)
                if command:
                    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    logger.warning("No sound player found for %s", path)
        except Exception:
            logger.warning("Cannot play sound %s", path, exc_info=True)


def _linux_player(path):
    for name in ("pw-play", "paplay"):
        player = shutil.which(name)
        if player:
            return [player, path]
    player = shutil.which("aplay")
    if player and path.lower().endswith(".wav"):
        return [player, "-q", path]
    return None
