import importlib.util
import inspect
import logging
import threading

from ezyocr.business.base import BusinessScript
from ezyocr.business.waybill_cn import WaybillCnScript
from ezyocr.i18n import t

logger = logging.getLogger(__name__)

SOURCE_DEFAULT = "default"
SOURCE_DOWNLOADED = "downloaded"


def default_script():
    return WaybillCnScript()


def load_script(settings, store):
    if settings.source != SOURCE_DOWNLOADED or not settings.script_id:
        return default_script(), None
    installed = store.get(settings.script_id)
    if installed is None:
        logger.error("Business script %s is not installed", settings.script_id)
        return default_script(), t("business.error.missing")
    if not store.verify(installed):
        logger.error("Business script %s does not match its sha256", installed.id)
        return default_script(), t("business.error.hash", title=installed.title)
    try:
        script = _load_file(installed.id, store.script_path(installed.id))
    except Exception as e:
        logger.exception("Cannot load business script %s", installed.id)
        return default_script(), t("business.error.load", title=installed.title, error=e)
    logger.info("Business script %s (%s) loaded", installed.id, installed.title)
    return script, None


def _load_file(script_id, path):
    module_name = f"ezyocr_business_script_{script_id}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    classes = [
        value for value in vars(module).values()
        if inspect.isclass(value)
        and issubclass(value, BusinessScript)
        and value.__module__ == module_name
    ]
    if len(classes) != 1:
        raise ValueError(t("business.error.class_count", count=len(classes)))
    script = classes[0]()
    if not script.key_field:
        raise ValueError(t("business.error.key_field"))
    return script


class ScriptRunner:
    def __init__(self, script, error=None, on_error=None):
        self._script = script
        self._fallback = default_script()
        self._error = error
        self._on_error = on_error
        self._lock = threading.Lock()

    @property
    def script(self):
        return self._script

    @property
    def error(self):
        return self._error

    def extract(self, ctx):
        script = self._script
        try:
            result = script.extract(ctx)
            if not isinstance(result, dict):
                raise TypeError(t("business.error.result_type"))
            return result
        except Exception as e:
            if type(script) is type(self._fallback):
                raise
            logger.exception("Business script %s failed, falling back to the default script", script.name)
            with self._lock:
                self._script = self._fallback
                self._error = t("business.error.runtime", error=e)
            if self._on_error:
                self._on_error(self._error)
            return self._fallback.extract(ctx)
