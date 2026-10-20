import logging
import threading
import time

from ezyocr.paths import captures_dir

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 3600
SECONDS_PER_DAY = 86400


class CaptureCleaner:
    def __init__(self, settings, protected_paths=None):
        self._directory = settings.captures_dir
        self._keep_days = settings.captures_keep_days
        self._protected_paths = protected_paths or set
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._keep_days <= 0:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="capture-cleaner", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            try:
                self.clean()
            except Exception:
                logger.exception("Cannot clean old captures")
            self._stop.wait(CLEANUP_INTERVAL_SECONDS)

    def clean(self):
        root = captures_dir(self._directory)
        cutoff = time.time() - self._keep_days * SECONDS_PER_DAY
        protected = self._protected_paths()
        removed = 0
        for folder in (root, root / "debug"):
            if not folder.is_dir():
                continue
            for path in folder.glob("*.jpg"):
                if self._stop.is_set():
                    return
                try:
                    if str(path) in protected or path.stat().st_mtime >= cutoff:
                        continue
                    path.unlink()
                    removed += 1
                except FileNotFoundError:
                    continue
                except OSError:
                    logger.debug("Cannot remove %s", path, exc_info=True)
        if removed:
            logger.info("Removed %s captures older than %s days from %s", removed, self._keep_days, root)
