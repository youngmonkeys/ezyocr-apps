import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TOKEN_COOKIES = ("adminAccessToken", "accessToken")
EXPIRED_AT_COOKIES = {
    "adminAccessToken": "adminAccessTokenExpiredAt",
    "accessToken": "accessTokenExpiredAt",
}


@dataclass(frozen=True)
class StaffSession:
    access_token: str
    expired_at: float | None

    @property
    def expired(self):
        return self.expired_at is not None and time.time() >= self.expired_at


class SessionWatcher:
    def __init__(self, read_cookies, on_change, interval):
        self._read_cookies = read_cookies
        self._on_change = on_change
        self._interval = interval
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._current = None
        self._thread = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="session-watcher", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def check_now(self):
        self._wake.set()

    def _run(self):
        while not self._stop.is_set():
            self._check()
            self._wake.wait(self._interval)
            self._wake.clear()

    def _check(self):
        try:
            session = self._read_session()
        except Exception:
            logger.debug("Cannot read cookies", exc_info=True)
            return
        if session is not None and session.expired:
            session = None
        if session == self._current:
            return
        previous, self._current = self._current, session
        if session is None:
            logger.info("Staff session ended")
        elif previous is None or previous.access_token != session.access_token:
            logger.info("Staff session started")
        try:
            self._on_change(session)
        except Exception:
            logger.exception("Session change handler failed")

    def _read_session(self):
        values = {}
        for cookie in self._read_cookies() or []:
            for name, morsel in cookie.items():
                if morsel.value:
                    values[name] = morsel.value
        for name in TOKEN_COOKIES:
            token = values.get(name)
            if token:
                return StaffSession(token, parse_expired_at(values.get(EXPIRED_AT_COOKIES[name])))
        return None


def parse_expired_at(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number / 1000 if number > 1e11 else number
