import logging
import subprocess
import sys

from ezyocr.i18n import t
from ezyocr.printing.label import build_label

logger = logging.getLogger(__name__)


class PrintError(Exception):
    pass


class LabelPrinter:
    def __init__(self, settings):
        self._settings = settings

    def print_label(self, tracking_number, customer_code):
        if not tracking_number:
            raise PrintError(t("print.missing_tracking"))
        data = build_label(self._settings, tracking_number, customer_code)
        if sys.platform == "win32":
            self._print_windows(data)
        else:
            self._print_cups(data)
        logger.info("Printed label %s / %s", tracking_number, customer_code)

    def _print_windows(self, data):
        import win32print

        try:
            name = self._settings.name or win32print.GetDefaultPrinter()
            handle = win32print.OpenPrinter(name)
            try:
                win32print.StartDocPrinter(handle, 1, ("Waybill label", None, "RAW"))
                try:
                    win32print.StartPagePrinter(handle)
                    win32print.WritePrinter(handle, data)
                    win32print.EndPagePrinter(handle)
                finally:
                    win32print.EndDocPrinter(handle)
            finally:
                win32print.ClosePrinter(handle)
        except win32print.error as e:
            raise PrintError(t("print.printer_error", message=e.strerror)) from e

    def _print_cups(self, data):
        command = ["lp", "-o", "raw"]
        if self._settings.name:
            command += ["-d", self._settings.name]
        try:
            completed = subprocess.run(command, input=data, capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise PrintError(t("print.send_failed", error=e)) from e
        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", "replace").strip() or t("print.unknown_error")
            raise PrintError(t("print.printer_error", message=message))
