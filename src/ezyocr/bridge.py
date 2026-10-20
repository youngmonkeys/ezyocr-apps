import logging

from ezyocr import __version__, i18n
from ezyocr.i18n import t
from ezyocr.printing.printer import PrintError

logger = logging.getLogger(__name__)


class StationApi:
    def __init__(self, app):
        self._app = app

    def get_version(self):
        return __version__

    def get_language(self):
        return i18n.language()

    def get_status(self):
        return self._app.status()

    def get_settings(self):
        return self._app.settings.to_dict()

    def get_ocr_backends(self):
        return self._app.ocr_backends()

    def get_setup_state(self):
        return self._app.setup_state()

    def choose_language(self, code):
        try:
            return {"ok": True, "restart": self._app.choose_language(code)}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def login(self, admin_url, username, password):
        try:
            self._app.login(admin_url, username, password)
            return {"ok": True, "state": self._app.setup_state()}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.exception("Cannot log in")
            return {"ok": False, "error": t("login.error.failed", error=e)}

    def logout(self):
        try:
            self._app.logout()
            return {"ok": True}
        except Exception as e:
            logger.exception("Cannot log out")
            return {"ok": False, "error": str(e)}

    def get_operator_settings(self, refresh=False):
        return self._app.operator_settings(bool(refresh))

    def get_installed_business_scripts(self):
        return self._app.installed_business_scripts()

    def list_business_script_categories(self):
        return self._app.list_business_script_categories()

    def list_business_scripts(self, keyword="", category_id=None, next_page_token=None):
        return self._app.list_business_scripts(keyword, category_id, next_page_token)

    def get_business_script(self, script_id):
        return self._app.business_script_details(script_id)

    def install_business_script(self, script_id):
        try:
            return self._app.install_business_script(script_id)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.exception("Cannot install business script %s", script_id)
            return {"ok": False, "error": t("business.error.install", error=e)}

    def fetch_image(self, url):
        return self._app.fetch_image(url)

    def open_business_scripts(self):
        self._app.open_business_scripts()

    def save_settings(self, data):
        try:
            if not self._app.save_settings(data or {}):
                return {"ok": True}
            return {
                "ok": True,
                "restart": {
                    "message": t("restart.message"),
                    "confirm": t("restart.confirm"),
                    "later": t("restart.later"),
                },
            }
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.exception("Cannot save settings")
            return {"ok": False, "error": t("error.save_settings", error=e)}

    def get_default_captures_dir(self):
        return self._app.default_captures_dir()

    def choose_captures_dir(self, current=""):
        try:
            return self._app.choose_captures_dir(current)
        except Exception:
            logger.exception("Cannot choose captures folder")
            return None

    def apply_settings(self):
        self._app.apply_settings()

    def restart_app(self):
        try:
            self._app.restart()
            return {"ok": True}
        except Exception as e:
            logger.exception("Cannot restart")
            return {"ok": False, "error": t("error.restart", error=e)}

    def get_pending_results(self):
        return self._app.pending_results()

    def ack_result(self, image_id, code=None):
        try:
            self._app.ack_result(image_id, code)
            return {"ok": True}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def print_label(self, tracking_number, customer_code=None):
        try:
            self._app.print_label(tracking_number, customer_code)
            return {"ok": True}
        except PrintError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.exception("Cannot print label %s", tracking_number)
            return {"ok": False, "error": t("error.print_label", error=e)}

    def print_html(self, content, base_url=None):
        try:
            self._app.print_html(content or "", base_url)
            return {"ok": True}
        except Exception as e:
            logger.exception("Cannot print page")
            return {"ok": False, "error": t("error.print_page", error=e)}

    def capture_now(self):
        try:
            self._app.capture_now()
            return {"ok": True}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def recognize_image_file(self):
        try:
            return {"ok": True, "selected": self._app.recognize_image_file()}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            logger.exception("Cannot recognize the image file")
            return {"ok": False, "error": t("error.recognition_failed")}

    def set_require_barcode(self, value):
        try:
            self._app.set_require_barcode(value)
            return {"ok": True}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def open_station(self):
        self._app.open_station()

    def open_setup(self):
        self._app.open_setup()
