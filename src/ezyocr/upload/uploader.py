import logging
import os
import threading

from ezyocr.upload.client import EzyPlatformClient, HttpError

logger = logging.getLogger(__name__)

IDLE_SECONDS = 5.0
FIRST_RETRY_SECONDS = 5.0
MAX_RETRY_SECONDS = 600.0


class MediaUploader:
    def __init__(self, base_url, settings, link_path, queue, keep_files, on_change):
        self._client = EzyPlatformClient(base_url, settings)
        self._link_path = link_path
        self._settings = settings
        self._queue = queue
        self._keep_files = keep_files
        self._on_change = on_change
        self._access_token = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="media-uploader", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        self._thread = None

    def set_access_token(self, access_token):
        self._access_token = access_token
        self._wake.set()

    def wake(self):
        self._wake.set()

    def discard(self, image_id):
        job = self._queue.get(image_id)
        if job is None:
            return
        self._queue.remove(image_id)
        self._remove_file(job.file_path)
        self._on_change()

    def _run(self):
        while not self._stop.is_set():
            access_token = self._access_token
            job = self._queue.next_due() if access_token else None
            if job is None:
                self._wake.wait(IDLE_SECONDS)
                self._wake.clear()
                continue
            self._process(job, access_token)

    def _process(self, job, access_token):
        try:
            if job.media_id is None:
                media_id = self._client.upload_media(access_token, job.file_path, f"{job.image_id}.jpg")
                logger.info("Uploaded image %s as media %s", job.image_id, media_id)
                self._queue.set_media_id(job.image_id, media_id)
            else:
                self._client.link_media(access_token, self._link_path, job.delivery_order_code, job.media_id)
                logger.info("Linked media %s to delivery order %s", job.media_id, job.delivery_order_code)
                self._finish(job)
        except FileNotFoundError:
            logger.warning("Image file %s is missing, dropping upload", job.file_path)
            self._queue.remove(job.image_id)
            self._on_change()
        except HttpError as e:
            if not e.retryable and job.attempts + 1 >= self._settings.max_attempts:
                logger.warning("Giving up image %s after %s attempts: %s", job.image_id, job.attempts + 1, e)
                self._queue.remove(job.image_id)
                self._on_change()
            else:
                self._retry_later(job, e)
        except Exception as e:
            self._retry_later(job, e)

    def _retry_later(self, job, error):
        delay = min(MAX_RETRY_SECONDS, FIRST_RETRY_SECONDS * 2 ** job.attempts)
        logger.warning("Upload of image %s failed, retry in %.0fs: %s", job.image_id, delay, error)
        self._queue.retry_later(job.image_id, delay)

    def _finish(self, job):
        self._queue.remove(job.image_id)
        self._remove_file(job.file_path)
        self._on_change()

    def _remove_file(self, file_path):
        if self._keep_files:
            return
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.debug("Cannot remove %s", file_path, exc_info=True)
