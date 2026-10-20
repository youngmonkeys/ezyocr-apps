import argparse
import base64
import difflib
import json
import logging
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.error
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from ezyocr import __version__, appmenu, i18n, titlebar, updater
from ezyocr.bridge import StationApi
from ezyocr.business.loader import SOURCE_DOWNLOADED, load_script
from ezyocr.business.store import BusinessScriptStore, DowngradeError
from ezyocr.core import RecognitionCore
from ezyocr.ezyplatform import TOKEN_COOKIE, AdminClient, LoginError
from ezyocr.i18n import t
from ezyocr.log import setup_logging
from ezyocr.paths import PACKAGE_DIR, captures_dir, data_dir, default_captures_dir, last_page_file, logs_dir, resource_path
from ezyocr.printing import html_printer
from ezyocr.recognition.backends import BACKENDS, available_backends
from ezyocr.session import SessionWatcher
from ezyocr.settings import SettingsStore, merge, origin_of, settings_from_dict
from ezyocr.upload.client import HttpError

logger = logging.getLogger(__name__)

APP_NAME = "EzyOCR"
DEV_ICON_FILE = PACKAGE_DIR.parent.parent / "packaging" / "icons" / "ezyocr.png"
PAGE_EVENT = "ezyocr"
CLEAR_WEB_DATA_TIMEOUT_SECONDS = 5
AUTH_PATHS = {"/login", "/logout", "/register"}
LOADING_HTML = "<!doctype html><html><body style='font:14px -apple-system,sans-serif;color:#6b7280;padding:24px'>{text}</body></html>"
COOKIE_SYNC_TIMEOUT_SECONDS = 20
MAX_IMAGE_BYTES = 5 * 1024 * 1024
DIFF_CONTEXT_LINES = 3
AUTO_UPDATE_INTERVAL_SECONDS = 12 * 60 * 60
AUTO_UPDATE_RETRY_SECONDS = 60


class StationApp:
    def __init__(self, store, settings, force_setup=False, camera_test=False):
        self._store = store
        self.settings = settings
        self._force_setup = force_setup
        self._camera_test = camera_test
        self._window = None
        self._camera_window = None
        self._about_window = None
        self._camera_enabled = True
        self._core = None
        self._watcher = None
        self._showing_setup = False
        self._setup_page = "setup.html"
        self._first_run = not settings.configured
        self._services_lock = threading.Lock()
        self._menu_language = i18n.language()
        self._script_store = BusinessScriptStore()
        self._script, self._script_error = load_script(settings.business_script, self._script_store)
        self._known_session = None
        self._operator_settings = None
        self._login_lock = threading.Lock()
        self._image_cache = {}
        self._update_lock = threading.Lock()
        self._declined_update_version = None
        self._update_progress = None

    def run(self):
        import webview
        from webview.menu import Menu, MenuAction

        web = self.settings.web
        self._showing_setup = not self._camera_test and (self._force_setup or not self.settings.configured)
        if self._camera_test:
            url, html = None, _camera_test_html()
        elif self._showing_setup:
            url, html = None, _setup_html()
        else:
            url, html = None, LOADING_HTML.format(text=t("app.loading"))
        self._window = webview.create_window(
            self._title(),
            url=url,
            html=html,
            js_api=StationApi(self),
            width=web.width,
            height=web.height,
            min_size=(900, 600),
        )
        self._window.events.loaded += self._on_loaded
        self._window.events.shown += self._on_shown
        self._window.events.closed += self._on_main_closed
        menu = [
            Menu(t("menu.station"), [
                MenuAction(t("menu.home"), self.open_station),
                MenuAction(t("menu.camera_view"), self.open_camera_view),
                MenuAction(self._camera_menu_title(), lambda: _in_thread(self.toggle_camera)),
                MenuAction(t("menu.copy_url"), self.copy_page_url),
                MenuAction(t("menu.reload"), self.reload_page),
                MenuAction(t("menu.back"), self.go_back),
                MenuAction(t("menu.setup"), self.open_setup),
                MenuAction(t("menu.reload_operator_settings"), lambda: _in_thread(self.reload_operator_settings)),
                MenuAction(t("menu.open_logs"), self.open_logs),
                MenuAction(t("menu.logout"), lambda: _in_thread(self.logout_from_menu)),
            ]),
            Menu(t("menu.help"), [
                Menu(t("menu.language"), [
                    MenuAction(self._language_menu_title(code), lambda code=code: self.change_language(code))
                    for code in i18n.LANGUAGE_CHOICES
                ]),
                MenuAction(t("menu.check_updates"), lambda: _in_thread(self.check_for_updates)),
                MenuAction(t("menu.about", name=APP_NAME), self.show_about),
            ]),
        ]
        appmenu.install_about(lambda: _in_thread(self.show_about))
        appmenu.install_camera_title(self._camera_menu_title(), (t("menu.camera_turn_off"), t("menu.camera_turn_on")))
        webview.start(self._on_start, private_mode=False, debug=self.settings.debug, menu=menu)
        self._stop_services()
        logger.info("Window closed, station stopped")

    def status(self):
        status = self._core.status() if self._core else {
            "business_script": self._script.name,
            "business_script_error": self._script_error,
        }
        status.update(configured=self.settings.configured, version=__version__)
        return status

    def pending_results(self):
        if self._core is None:
            return []
        return self._core.pending_results()

    def ack_result(self, image_id, code=None):
        if self._core is None:
            raise ValueError(t("error.core_not_running"))
        self._core.ack_result(image_id, code)

    def print_label(self, tracking_number, customer_code=None):
        if self._core is None:
            raise ValueError(t("error.not_configured"))
        self._core.print_label(tracking_number, customer_code)

    def print_html(self, content, base_url=None):
        import webview

        width, height = html_printer.PRINT_WINDOW_SIZE
        window = webview.create_window(
            t("window.print"),
            html=html_printer.add_base_url(content, base_url),
            width=width,
            height=height,
        )
        window.events.loaded += lambda: html_printer.print_window(window, self.settings.printer)

    def capture_now(self):
        if self._core is None:
            raise ValueError(t("error.core_not_running"))
        self._core.capture_now()

    def recognize_image_file(self):
        import webview

        core = self._core
        if core is None:
            raise ValueError(t("error.core_not_running"))
        window = self._camera_window or self._window
        selected = window.create_file_dialog(webview.FileDialog.OPEN, file_types=(t("camera.image_file_types"),))
        if not selected:
            return False
        core.recognize_file(selected[0])
        return True

    def toggle_camera(self):
        self._camera_enabled = not self._camera_enabled
        core = self._core
        if core is not None:
            core.set_camera_enabled(self._camera_enabled)
        appmenu.set_camera_title(self._camera_menu_title())

    def _camera_menu_title(self):
        if not appmenu.dynamic_titles():
            return t("menu.camera_toggle")
        return t("menu.camera_turn_off") if self._camera_enabled else t("menu.camera_turn_on")

    def set_require_barcode(self, value):
        if self._core is None:
            raise ValueError(t("error.core_not_running"))
        self._core.set_require_barcode(value)

    def save_settings(self, data):
        data = {k: v for k, v in (data or {}).items() if k != "web"}
        settings = settings_from_dict(merge(self.settings.to_dict(), data))
        if not settings.configured or self._valid_session() is None:
            raise ValueError(t("error.login_required"))
        _validate_captures(settings.camera)
        self._validate_business_script(settings.business_script)
        _validate_ocr(settings.ocr)
        self._store.save(settings)
        self.settings = settings
        self._first_run = False
        i18n.set_language(settings.language)
        restart_needed = i18n.language() != self._menu_language
        if not restart_needed:
            self.apply_settings()
        return restart_needed

    def ocr_backends(self):
        available = set(available_backends())
        current = self.settings.ocr.backend
        return [
            {"name": name, "label": t(f"ocr.backend.{name}"), "available": name in available}
            for name in BACKENDS
            if name in available or name == current
        ]

    def change_language(self, value):
        if value == self.settings.language:
            return
        settings = settings_from_dict(merge(self.settings.to_dict(), {"language": value}))
        self._store.save(settings)
        self.settings = settings
        page_changed = i18n.resolve_language(value) != i18n.language()
        i18n.set_language(value)
        if page_changed and self._showing_setup:
            self._reload_setup_page()
        if i18n.language() == self._menu_language:
            return
        if not _confirm(self._window, t("restart.message"), t("restart.confirm"), t("restart.later")):
            return
        try:
            self.restart()
        except Exception:
            logger.exception("Cannot restart")

    def _language_menu_title(self, code):
        name = i18n.language_name(code)
        return f"✓ {name}" if code == self.settings.language else name

    def default_captures_dir(self):
        return str(default_captures_dir())

    def choose_captures_dir(self, current=""):
        import webview

        directory = str(current or "").strip() or str(default_captures_dir())
        selected = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=str(Path(directory).expanduser()))
        return selected[0] if selected else None

    def apply_settings(self):
        threading.Thread(target=self._restart_services, name="restart", daemon=True).start()

    def restart(self):
        _launch_after_exit(_relaunch_command())
        logger.info("Restarting station")
        self._window.destroy()

    def open_station(self):
        if not self.settings.configured:
            self.open_setup()
            return
        self._showing_setup = False
        self._window.load_url(self._home_url())

    def open_setup(self):
        self._showing_setup = True
        self._setup_page = "setup.html"
        self._window.load_html(i18n.render_page(self._setup_page))

    def open_business_scripts(self):
        self._showing_setup = True
        self._setup_page = "business_scripts.html"
        self._window.load_html(i18n.render_page(self._setup_page))

    def _reload_setup_page(self):
        self._window.load_html(i18n.render_page(self._setup_page))

    def _home_url(self):
        path = str(self._script.home_path or "/")
        return self.settings.web.admin_url.rstrip("/") + (path if path.startswith("/") else "/" + path)

    def setup_state(self):
        session = self._valid_session()
        system_language = i18n.resolve_language("auto")
        if not self.settings.configured and self.settings.language == "auto":
            step = "language"
        elif session is None:
            step = "login"
        else:
            step = "settings"
        return {
            "step": step,
            "configured": self.settings.configured,
            "first_run": self._first_run,
            "languages": [
                {"code": code, "native": i18n.LANGUAGE_NAMES[code], "english": i18n.LANGUAGE_ENGLISH_NAMES[code]}
                for code in i18n.LANGUAGES
            ],
            "system_language": system_language,
            "language": i18n.language(),
            "admin_url": self.settings.web.admin_url,
            "username": self.settings.web.username,
            "logged_in": session is not None,
            "expired_at": int(session.expired_at * 1000) if session and session.expired_at else None,
            "business_script": self.settings.business_script.__dict__,
            "business_script_error": self.status().get("business_script_error"),
        }

    def choose_language(self, code):
        if code not in i18n.LANGUAGES:
            raise ValueError(t("error.language_invalid"))
        settings = settings_from_dict(merge(self.settings.to_dict(), {"language": code}))
        self._store.save(settings)
        self.settings = settings
        i18n.set_language(code)
        if i18n.language() == self._menu_language:
            return False
        threading.Timer(0.3, self.restart).start()
        return True

    def login(self, admin_url, username, password):
        origin = origin_of(admin_url)
        if not origin:
            raise ValueError(t("login.error.admin_url"))
        username = str(username or "").strip()
        if not username or not password:
            raise ValueError(t("login.error.required"))
        with self._login_lock:
            client = AdminClient(origin)
            try:
                session = client.login(username, password)
            except LoginError as e:
                raise ValueError(t(f"login.error.{e.reason}")) from e
            except (urllib.error.URLError, OSError) as e:
                raise ValueError(t("login.error.network", url=origin)) from e
            self._sync_session_cookie(client, session)
            settings = settings_from_dict(merge(self.settings.to_dict(), {"web": {"admin_url": origin, "username": username}}))
            self._store.save(settings)
            self.settings = settings
            self._known_session = session
            logger.info("Logged in to %s as %s", origin, username)

    def logout_from_menu(self):
        if not _confirm(self._window, t("logout.confirm"), t("setup.logout"), t("business.confirm.cancel")):
            return
        self.logout()
        self.open_setup()

    def logout(self):
        self._known_session = None
        self._operator_settings = None
        self._image_cache.clear()
        self._stop_services()
        _clear_web_data(self._window)
        logger.info("Logged out")

    def _sync_session_cookie(self, client, session):
        import webview

        loaded = threading.Event()
        window = webview.create_window("", url=client.fetch_to_cookie_url(session.access_token), hidden=True)
        window.events.loaded += loaded.set
        try:
            if not loaded.wait(COOKIE_SYNC_TIMEOUT_SECONDS):
                raise ValueError(t("login.error.session_cookie"))
            cookies = {name: morsel.value for cookie in window.get_cookies() or [] for name, morsel in cookie.items()}
            if cookies.get(TOKEN_COOKIE) != session.access_token:
                raise ValueError(t("login.error.session_cookie"))
        finally:
            window.destroy()

    def _valid_session(self):
        session = self._known_session
        if session is None or session.expired:
            return None
        return session

    def _admin_client(self):
        session = self._valid_session()
        if session is None or not self.settings.configured:
            raise _LoginRequired()
        return AdminClient(self.settings.web.admin_url), session.access_token

    def installed_business_scripts(self):
        return [script.to_dict() for script in self._script_store.list()]

    def list_business_script_categories(self):
        try:
            client, token = self._admin_client()
            data = client.business_script_categories(token)
        except Exception as e:
            return _remote_error(e)
        items = [{"id": item["id"], "name": item.get("name") or ""} for item in data.get("items") or []]
        return {"items": sorted(items, key=lambda item: item["name"].lower())}

    def list_business_scripts(self, keyword="", category_id=None, next_page_token=None):
        try:
            client, token = self._admin_client()
            data = client.business_scripts(
                token,
                str(keyword or "").strip() or None,
                int(category_id or 0) or None,
                next_page_token,
            )
        except Exception as e:
            return _remote_error(e)
        installed = {script.id: script for script in self._script_store.list()}
        items = [self._remote_script_item(client, item, installed.get(item["id"])) for item in data.get("items") or []]
        continuation = data.get("continuation") or {}
        page_token = data.get("pageToken") or {}
        return {"items": items, "next_page_token": page_token.get("next") if continuation.get("hasNext") else None}

    def business_script_details(self, script_id):
        try:
            client, token = self._admin_client()
            details = client.business_script(token, script_id)
        except Exception as e:
            return _remote_error(e)
        installed = self._script_store.get(details["id"])
        item = self._remote_script_item(client, details, installed)
        local = self._script_store.read_content(details["id"]) if installed else None
        diff, added, removed = _diff(local, details.get("content") or "")
        item.update(content=details.get("content") or "", diff=diff, added=added, removed=removed)
        return item

    def install_business_script(self, script_id):
        try:
            client, token = self._admin_client()
            details = client.business_script(token, script_id)
        except Exception as e:
            raise ValueError(_remote_error_message(e)) from e
        content = details.get("content") or ""
        if not content.strip():
            raise ValueError(t("business.error.empty"))
        installed = self._script_store.get(details["id"])
        local = self._script_store.read_content(details["id"]) if installed else None
        _, added, removed = _diff(local, content)
        lines = [
            t("business.confirm.id", id=details["id"]),
            t("business.confirm.updated_at", time=_format_time(details.get("updatedAt"))),
            t("business.confirm.changes", added=added, removed=removed) if installed else t("business.confirm.lines", count=len(content.splitlines())),
            "",
            t("business.confirm.warning"),
        ]
        if not _confirm(
            self._window,
            t("business.confirm.title", title=details.get("title") or ""),
            t("business.confirm.install"),
            t("business.confirm.cancel"),
            "\n".join(lines),
        ):
            return {"ok": False, "cancelled": True}
        try:
            script = self._script_store.install(details, content)
        except DowngradeError as e:
            raise ValueError(t("business.error.downgrade")) from e
        selected = self.settings.business_script
        in_use = selected.source == SOURCE_DOWNLOADED and selected.script_id == script.id
        if in_use:
            self._reload_script()
            self._restart_services_in_background()
        return {"ok": True, "script": script.to_dict(), "in_use": in_use}

    def fetch_image(self, url):
        if not url:
            return None
        cached = self._image_cache.get(url)
        if cached is not None:
            return cached
        try:
            client, token = self._admin_client()
            content, content_type = client.get_bytes(url, token)
        except Exception:
            logger.debug("Cannot fetch image %s", url, exc_info=True)
            return None
        if not content_type.startswith("image/") or len(content) > MAX_IMAGE_BYTES:
            return None
        data_url = f"data:{content_type};base64,{base64.b64encode(content).decode()}"
        self._image_cache[url] = data_url
        return data_url

    def _remote_script_item(self, client, item, installed):
        updated_at = int(item.get("updatedAt") or 0)
        if installed is None:
            state = "new"
        elif updated_at > installed.updated_at:
            state = "update"
        else:
            state = "installed"
        selected = self.settings.business_script
        return {
            "id": item["id"],
            "title": item.get("title") or "",
            "description": item.get("description") or "",
            "category_name": item.get("categoryName") or "",
            "updated_at": updated_at,
            "image_url": client.absolute_url(item["featuredImageUrl"]) if item.get("featuredImageUrl") else None,
            "installed_updated_at": installed.updated_at if installed else None,
            "state": state,
            "in_use": selected.source == SOURCE_DOWNLOADED and selected.script_id == item["id"],
        }

    def _validate_business_script(self, settings):
        if settings.source != SOURCE_DOWNLOADED:
            settings.script_id = 0
            return
        if not settings.script_id or self._script_store.get(settings.script_id) is None:
            raise ValueError(t("business.error.choose_script"))

    def _reload_script(self):
        self._script, self._script_error = load_script(self.settings.business_script, self._script_store)

    def open_camera_view(self):
        if self._camera_test:
            return
        if self._camera_window is not None:
            self._camera_window.show()
            return
        import webview

        self._camera_window = webview.create_window(
            t("window.camera_view", title=self._title()),
            html=_camera_test_html(),
            js_api=StationApi(self),
            width=1100,
            height=720,
            min_size=(800, 560),
        )
        self._camera_window.events.closed += self._on_camera_view_closed
        core = self._core
        if core is not None:
            core.set_preview(True)

    def _on_camera_view_closed(self):
        self._camera_window = None
        core = self._core
        if core is not None:
            core.set_preview(False)

    def _on_main_closed(self):
        for window in (self._camera_window, self._about_window):
            if window is not None:
                window.destroy()

    def copy_page_url(self):
        url = self._current_url()
        if not url:
            return
        try:
            _copy_to_clipboard(url)
        except Exception:
            logger.exception("Cannot copy page URL")
            return
        self._window.set_title(t("window.url_copied", url=url))
        timer = threading.Timer(2.0, self._update_title)
        timer.daemon = True
        timer.start()

    def reload_page(self):
        if not self._showing_setup:
            self._window.run_js("window.location.reload()")

    def go_back(self):
        if not self._showing_setup:
            self._window.run_js("window.history.back()")

    def _current_url(self):
        if self._window is None or self._showing_setup or self._camera_test:
            return None
        try:
            return self._window.get_current_url()
        except Exception:
            logger.debug("Cannot read current URL", exc_info=True)
            return None

    def _title(self):
        return self.settings.web.title.strip() or t("app.title")

    def _update_title(self):
        title = self._title()
        url = self._current_url()
        self._window.set_title(f"{title} — {url}" if url else title)

    def show_about(self):
        if self._about_window is not None:
            self._about_window.show()
            return
        import webview

        self._about_window = webview.create_window(
            t("about.page_title"),
            html=_about_html(),
            width=440,
            height=700,
            resizable=False,
        )
        self._about_window.events.closed += self._on_about_closed

    def _on_about_closed(self):
        self._about_window = None

    def check_for_updates(self, manual=True):
        if not self._update_lock.acquire(blocking=False):
            if manual:
                _alert(self._window, t("update.in_progress"))
            return
        try:
            self._check_for_updates(manual)
        finally:
            self._update_lock.release()

    def _auto_update_loop(self):
        while self._window is not None:
            if self._valid_session() is None:
                time.sleep(AUTO_UPDATE_RETRY_SECONDS)
                continue
            self.check_for_updates(manual=False)
            time.sleep(AUTO_UPDATE_INTERVAL_SECONDS)

    def _check_for_updates(self, manual):
        try:
            client, token = self._admin_client()
            release = client.latest_app_release(token, updater.current_os(), updater.current_arch(), __version__)
        except Exception as e:
            logger.info("Cannot check for updates: %s", e)
            if manual:
                _alert(self._window, _update_error_message(e))
            return
        version = release.get("version") or ""
        if not release.get("updateAvailable"):
            if manual:
                _alert(self._window, t("update.latest", version=__version__))
            return
        if not manual and (not release.get("showUpdatePrompt") or version == self._declined_update_version):
            return
        download = release.get("download") or {}
        package_type = download.get("packageType")
        logger.info("Update %s is available (%s)", version, download.get("fileName"))
        if not _confirm(
            self._window,
            t("update.available", version=version, current=__version__),
            t("update.download"),
            t("update.later"),
            (release.get("releaseNotes") or "").strip() or None,
        ):
            self._declined_update_version = version
            return
        try:
            path = updater.download(download, self._show_update_progress)
        except Exception as e:
            logger.exception("Cannot download update %s", version)
            _alert(self._window, t("update.error.download", error=_update_error_message(e)))
            return
        finally:
            self._update_progress = None
            self._update_title()
        if not updater.can_install(package_type):
            updater.reveal(path)
            _alert(self._window, t("update.manual_install", path=path))
            return
        if not _confirm(self._window, t("update.ready", version=version), t("update.install"), t("update.later")):
            self._declined_update_version = version
            return
        updater.install_after_exit(path, package_type)
        logger.info("Installing update %s, closing the station", version)
        self._window.destroy()

    def _show_update_progress(self, done, total):
        percent = int(done * 100 / total) if total else None
        if percent == self._update_progress:
            return
        self._update_progress = percent
        text = t("update.downloading", percent=percent) if percent is not None else t("update.downloading_size", size=done // (1024 * 1024))
        try:
            self._window.set_title(f"{self._title()} — {text}")
        except Exception:
            logger.debug("Cannot show update progress", exc_info=True)

    def open_logs(self):
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(logs_dir())])
        elif sys.platform == "win32":
            os.startfile(logs_dir())

    def _restart_services(self):
        self._reload_script()
        self._stop_services()
        self._start_services()
        self.open_station()

    def _restart_services_in_background(self):
        def restart():
            self._stop_services()
            self._start_services()

        threading.Thread(target=restart, name="restart-core", daemon=True).start()

    def _on_start(self):
        _schedule_dev_icon()
        web = self.settings.web
        if web.clear_session_on_start:
            _clear_web_data(self._window)
        if not self._camera_test and not self._showing_setup:
            last_page = None if web.clear_session_on_start else _read_last_page()
            self._window.load_url(last_page if _same_site(last_page, web.admin_url) else self._home_url())
        self._start_services()
        if not self._camera_test:
            threading.Thread(target=self._auto_update_loop, name="auto-update", daemon=True).start()

    def _start_services(self):
        with self._services_lock:
            if self._core is not None:
                return
            if self._camera_test:
                self._core = RecognitionCore(self.settings, self._notify, self._script, self._script_error, test_mode=True)
                self._core.set_camera_enabled(self._camera_enabled)
                self._core.warm_up()
                self._core.start_test()
                return
            if not self.settings.configured:
                return
            self._core = RecognitionCore(self.settings, self._notify, self._script, self._script_error)
            self._core.set_camera_enabled(self._camera_enabled)
            self._core.set_preview(self._camera_window is not None)
            self._core.warm_up()
            self._watcher = SessionWatcher(
                self._read_cookies, self._on_session_change, self.settings.web.session_check_seconds
            )
            self._watcher.start()
            logger.info("Station services started")

    def _stop_services(self):
        with self._services_lock:
            if self._watcher:
                self._watcher.stop()
            if self._core:
                self._core.shutdown()
            self._watcher = None
            self._core = None

    def _read_cookies(self):
        if self._showing_setup or self._window is None:
            return []
        return self._window.get_cookies()

    def _on_shown(self):
        if self._camera_test:
            return
        titlebar.add_buttons(self._window.native, [
            ("camera.viewfinder", t("menu.camera_view"), lambda: _in_thread(self.open_camera_view)),
            ("doc.on.doc", t("menu.copy_url"), lambda: _in_thread(self.copy_page_url)),
        ])

    def _on_loaded(self):
        url = self._current_url()
        if _same_site(url, self.settings.web.admin_url) and urlsplit(url).path.rstrip("/") not in AUTH_PATHS:
            _write_last_page(url)
        self._update_title()
        if not self._showing_setup and not self._camera_test:
            _run_js(self._window, html_printer.PRINT_SHIM_JS)
        if self._watcher:
            self._watcher.check_now()

    def _on_session_change(self, session):
        if session is not None:
            self._known_session = session
        elif not self._showing_setup:
            self._known_session = None
        core = self._core
        if core is None:
            return
        if session is None:
            core.stop()
        else:
            core.start(session.access_token)
            _in_thread(lambda: self._load_operator_settings(core, session.access_token))

    def operator_settings(self, refresh=False):
        settings = self._operator_settings
        if refresh or settings is None:
            try:
                settings = self._fetch_operator_settings()
            except Exception as e:
                logger.info("Cannot load OCR operator settings: %s", e)
                return {"ok": False, "error": _operator_settings_error_message(e)}
        return {
            "ok": True,
            "operator": bool(settings.get("ocrOperator")),
            "settings": settings.get("settings") or {},
        }

    def _fetch_operator_settings(self):
        client, token = self._admin_client()
        settings = client.ocr_operator_settings(token)
        self._operator_settings = settings
        self._apply_operator_settings(self._core, settings)
        return settings

    def reload_operator_settings(self):
        try:
            client, token = self._admin_client()
            settings = client.ocr_operator_settings(token)
            self._operator_settings = settings
        except Exception as e:
            logger.info("Cannot reload OCR operator settings: %s", e)
            _alert(self._window, _operator_settings_error_message(e))
            return
        if not settings.get("ocrOperator"):
            _alert(self._window, t("operator_settings.not_operator"))
            return
        if not self._apply_operator_settings(self._core, settings):
            _alert(self._window, t("operator_settings.not_running"))
            return
        _alert(self._window, t("operator_settings.reloaded"))

    def _load_operator_settings(self, core, access_token):
        try:
            settings = AdminClient(self.settings.web.admin_url).ocr_operator_settings(access_token)
        except Exception as e:
            logger.info("Cannot load OCR operator settings: %s", e)
            return
        self._operator_settings = settings
        self._apply_operator_settings(core, settings)

    def _apply_operator_settings(self, core, settings):
        if core is None or core is not self._core or not settings.get("ocrOperator"):
            return False
        values = settings.get("settings") or {}
        if "requireBarcode" in values:
            core.set_require_barcode(values["requireBarcode"])
        logger.info("Applied OCR operator settings %s", values)
        return True

    def _notify(self, event, data):
        detail = json.dumps({"event": event, "data": data})
        script = f"window.dispatchEvent(new CustomEvent('{PAGE_EVENT}', {{detail: {detail}}}))"
        main_window = self._window
        if main_window is not None and not self._showing_setup and (event != "preview" or self._camera_test):
            _run_js(main_window, script)
        camera_window = self._camera_window
        if camera_window is not None:
            _run_js(camera_window, script)


def _run_js(window, script):
    try:
        window.run_js(script)
    except Exception:
        logger.debug("Cannot notify page", exc_info=True)


class _LoginRequired(Exception):
    pass


def _remote_error(error):
    if isinstance(error, _LoginRequired):
        return {"login_required": True}
    if isinstance(error, HttpError):
        if error.status == 401:
            return {"login_required": True}
        if error.status == 403:
            return {"no_permission": True}
        if error.status == 404:
            return {"error": t("business.error.not_found")}
        logger.warning("Business script request failed: %s", error)
        return {"error": t("business.error.server", status=error.status)}
    if isinstance(error, (urllib.error.URLError, OSError)):
        return {"error": t("business.error.network")}
    logger.exception("Business script request failed", exc_info=error)
    return {"error": t("business.error.unexpected", error=error)}


def _remote_error_message(error):
    result = _remote_error(error)
    if result.get("login_required"):
        return t("business.error.login_required")
    if result.get("no_permission"):
        return t("business.error.no_permission")
    return result["error"]


def _update_error_message(error):
    if isinstance(error, updater.UpdateError):
        return t(f"update.error.{error.reason}")
    if isinstance(error, _LoginRequired) or (isinstance(error, HttpError) and error.status == 401):
        return t("update.error.login_required")
    if isinstance(error, HttpError) and error.status == 404:
        return t("update.error.not_found")
    if isinstance(error, HttpError):
        return t("update.error.server", status=error.status)
    if isinstance(error, (urllib.error.URLError, OSError)):
        return t("update.error.network")
    return t("update.error.unexpected", error=error)


def _operator_settings_error_message(error):
    if isinstance(error, _LoginRequired) or (isinstance(error, HttpError) and error.status == 401):
        return t("operator_settings.error.login_required")
    if isinstance(error, HttpError) and error.status == 404:
        return t("operator_settings.error.not_supported")
    if isinstance(error, HttpError):
        return t("operator_settings.error.server", status=error.status)
    if isinstance(error, (urllib.error.URLError, OSError)):
        return t("update.error.network")
    return t("operator_settings.error.unexpected", error=error)


def _diff(old, new):
    if old is None:
        return [], len(new.splitlines()), 0
    result = []
    added = removed = 0
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=DIFF_CONTEXT_LINES):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            result.append({"type": "hunk", "text": line})
        elif line.startswith("+"):
            added += 1
            result.append({"type": "add", "text": line[1:]})
        elif line.startswith("-"):
            removed += 1
            result.append({"type": "del", "text": line[1:]})
        else:
            result.append({"type": "same", "text": line[1:]})
    return result, added, removed


def _format_time(millis):
    try:
        return datetime.fromtimestamp(int(millis) / 1000).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def _same_site(url, base_url):
    if not url or not base_url:
        return False
    page, base = urlsplit(url), urlsplit(base_url)
    return page.scheme in ("http", "https") and (page.scheme, page.netloc) == (base.scheme, base.netloc)


def _read_last_page():
    try:
        return last_page_file().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _write_last_page(url):
    try:
        last_page_file().write_text(url, encoding="utf-8")
    except OSError:
        logger.debug("Cannot save last page", exc_info=True)


def _clear_web_data(window):
    if sys.platform != "darwin":
        window.clear_cookies()
        return
    try:
        import Foundation
        import WebKit
        from PyObjCTools import AppHelper
    except ImportError:
        window.clear_cookies()
        return
    done = threading.Event()

    def clear():
        WebKit.WKWebsiteDataStore.defaultDataStore().removeDataOfTypes_modifiedSince_completionHandler_(
            WebKit.WKWebsiteDataStore.allWebsiteDataTypes(),
            Foundation.NSDate.dateWithTimeIntervalSince1970_(0),
            done.set,
        )

    AppHelper.callAfter(clear)
    if not done.wait(CLEAR_WEB_DATA_TIMEOUT_SECONDS):
        logger.warning("Clearing web data did not finish in time")


def _about_html():
    icon = base64.b64encode(resource_path("icon.png").read_bytes()).decode("ascii")
    replacements = {
        "__ICON__": f"data:image/png;base64,{icon}",
        "__VERSION__": __version__,
        "__PYTHON__": platform.python_version(),
        "__SYSTEM__": _system_name(),
    }
    content = i18n.render_page("about.html")
    for key, value in replacements.items():
        content = content.replace(key, escape(value))
    return content


def _system_name():
    if sys.platform == "darwin":
        name = f"macOS {platform.mac_ver()[0]}"
    elif sys.platform == "win32":
        name = f"Windows {platform.release()}"
    else:
        name = f"{platform.system()} {platform.release()}"
    return f"{name} · {platform.machine()}"


def _in_thread(target):
    threading.Thread(target=target, daemon=True).start()


def _validate_captures(camera):
    if camera.captures_keep_days < 0:
        raise ValueError(t("error.captures_keep_days"))
    if camera.save_captures and camera.captures_dir.strip():
        try:
            captures_dir(camera.captures_dir)
        except OSError as e:
            raise ValueError(t("error.captures_dir", error=e)) from e


def _validate_ocr(ocr):
    if ocr.backend not in available_backends():
        raise ValueError(t("error.ocr_backend_unavailable", name=t(f"ocr.backend.{ocr.backend}")))
    if not isinstance(ocr.options, dict):
        raise ValueError(t("error.ocr_options"))


def _confirm(window, message, confirm, cancel, details=None):
    if sys.platform != "darwin":
        return window.create_confirmation_dialog(t("app.title"), f"{message}\n\n{details}" if details else message)
    import AppKit
    from PyObjCTools import AppHelper

    result = {}
    done = threading.Event()

    def show():
        try:
            alert = AppKit.NSAlert.alloc().init()
            _set_alert_icon(alert)
            alert.setMessageText_(message)
            if details:
                alert.setInformativeText_(details)
            alert.addButtonWithTitle_(confirm)
            alert.addButtonWithTitle_(cancel)
            result["ok"] = alert.runModal() == AppKit.NSAlertFirstButtonReturn
        finally:
            done.set()

    AppHelper.callAfter(show)
    done.wait()
    return result.get("ok", False)


def _alert(window, message, details=None):
    if sys.platform != "darwin":
        if window is not None:
            window.create_confirmation_dialog(t("app.title"), f"{message}\n\n{details}" if details else message)
        return
    import AppKit
    from PyObjCTools import AppHelper

    done = threading.Event()

    def show():
        try:
            alert = AppKit.NSAlert.alloc().init()
            _set_alert_icon(alert)
            alert.setMessageText_(message)
            if details:
                alert.setInformativeText_(details)
            alert.addButtonWithTitle_(t("update.ok"))
            alert.runModal()
        finally:
            done.set()

    AppHelper.callAfter(show)
    done.wait()


def _set_alert_icon(alert):
    try:
        import AppKit

        image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(resource_path("icon.png")))
        if image is not None:
            alert.setIcon_(image)
    except Exception:
        logger.debug("Cannot set the alert icon", exc_info=True)


def _relaunch_command():
    bundle = _app_bundle()
    if bundle:
        return ["open", "-n", bundle]
    return [sys.executable, "-m", "ezyocr", *sys.argv[1:]]


def _app_bundle():
    if sys.platform != "darwin":
        return None
    try:
        from Foundation import NSBundle
    except ImportError:
        return None
    bundle = Path(str(NSBundle.mainBundle().bundlePath()))
    if bundle.suffix == ".app" and PACKAGE_DIR.is_relative_to(bundle):
        return str(bundle)
    return None


def _launch_after_exit(command):
    if sys.platform == "win32":
        subprocess.Popen(command, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        return
    script = 'while kill -0 "$0" 2>/dev/null; do sleep 0.2; done; exec "$@"'
    subprocess.Popen(
        ["/bin/sh", "-c", script, str(os.getpid()), *command],
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def _copy_to_clipboard(text):
    if sys.platform == "darwin":
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    elif sys.platform == "win32":
        subprocess.run(["clip"], input=text.encode("utf-16"), check=True)
    else:
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=True)


def _setup_html():
    return i18n.render_page("setup.html")


def _camera_test_html():
    return i18n.render_page("camera_test.html")


def _set_macos_app_identity():
    if sys.platform != "darwin":
        return
    try:
        import AppKit
    except ImportError:
        return
    try:
        bundle = AppKit.NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        info["CFBundleName"] = APP_NAME
        info["CFBundleDisplayName"] = APP_NAME
    except Exception:
        logger.exception("Cannot set the macOS app name")
    _apply_dev_icon()


def _schedule_dev_icon():
    if sys.platform != "darwin" or _app_bundle() is not None:
        return
    try:
        from PyObjCTools import AppHelper
    except ImportError:
        return
    AppHelper.callAfter(_apply_dev_icon)


def _apply_dev_icon():
    if sys.platform != "darwin" or _app_bundle() is not None or not DEV_ICON_FILE.is_file():
        return
    try:
        import AppKit

        image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(DEV_ICON_FILE))
        if image is not None:
            AppKit.NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:
        logger.exception("Cannot set the macOS dock icon")


def main():
    parser = argparse.ArgumentParser(prog="ezyocr")
    parser.add_argument("--setup", action="store_true", help="mở trang cài đặt trạm")
    parser.add_argument("--debug", action="store_true", help="ghi log chi tiết, bật công cụ dev của webview")
    parser.add_argument("--camera-test", action="store_true", help="thử camera và nhận diện trên máy, không cần đăng nhập")
    args, _ = parser.parse_known_args()

    store = SettingsStore()
    settings = store.load()
    if args.debug:
        settings.debug = True
    setup_logging(settings.debug)
    i18n.set_language(settings.language)
    _set_macos_app_identity()
    logger.info("EzyOCR %s starting, data dir %s", __version__, data_dir())
    try:
        StationApp(store, settings, force_setup=args.setup, camera_test=args.camera_test).run()
    except Exception:
        logger.exception("EzyOCR crashed")
        raise
