import html
import json
import locale
import logging
import os
import re
import sys

from ezyocr.paths import resource_path

logger = logging.getLogger(__name__)

LANGUAGES = ("vi", "en", "zh")
LANGUAGE_CHOICES = ("auto", *LANGUAGES)
LANGUAGE_NAMES = {"vi": "Tiếng Việt", "en": "English", "zh": "中文（简体）"}
LANGUAGE_ENGLISH_NAMES = {"vi": "Vietnamese", "en": "English", "zh": "Chinese (Simplified)"}
FALLBACK_LANGUAGE = "en"
HTML_LANG = {"vi": "vi", "en": "en", "zh": "zh-CN"}
TEMPLATE_KEY = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

_language = FALLBACK_LANGUAGE
_messages = {}


def set_language(value):
    global _language
    _language = resolve_language(value)
    logger.info("Language %s (setting %r)", _language, value)


def language():
    return _language


def language_name(code):
    return LANGUAGE_NAMES.get(code) or t("language.auto")


def resolve_language(value):
    code = _match(value)
    if code:
        return code
    for candidate in _system_languages():
        code = _match(candidate)
        if code:
            return code
    return FALLBACK_LANGUAGE


def messages():
    if _language not in _messages:
        _messages[_language] = {**_load(FALLBACK_LANGUAGE), **_load(_language)}
    return _messages[_language]


def t(key, **kwargs):
    text = messages().get(key, key)
    return text.format(**kwargs) if kwargs else text


def render_page(name):
    content = resource_path(name).read_text(encoding="utf-8")
    content = TEMPLATE_KEY.sub(lambda m: html.escape(t(m.group(1))), content)
    data = json.dumps(messages(), ensure_ascii=False).replace("</", "<\\/")
    return content.replace("__HTML_LANG__", HTML_LANG[_language]).replace("__I18N__", data)


def _match(value):
    prefix = str(value or "").strip().lower().replace("_", "-").split("-")[0]
    return prefix if prefix in LANGUAGES else None


def _system_languages():
    if sys.platform == "darwin":
        try:
            from Foundation import NSLocale

            yield from (str(code) for code in NSLocale.preferredLanguages())
        except ImportError:
            pass
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        yield os.environ.get(name)
    yield locale.getlocale()[0]


def _load(lang):
    path = resource_path("i18n", f"{lang}.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.exception("Cannot load messages %s", path)
        return {}
