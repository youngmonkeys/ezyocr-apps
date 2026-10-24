import argparse
import json
import webbrowser
from pathlib import Path

from ezyocr import __version__, i18n
from ezyocr.paths import resource_path

OUTPUT_FILE = Path(__file__).resolve().parent.parent / "output" / "preview" / "setup.html"
SAMPLE_RELEASE_NOTES = "- Read waybills faster on low-light cameras\n- Fix label printing on TSPL printers\n- Show new versions on the station settings page"

MOCK_API = """
<script>
  window.pywebview = { api: new Proxy(__MOCK__, {
    get: (target, name) => async (...args) => {
      console.log("pywebview.api." + name, args);
      const value = target[name];
      return typeof value === "function" ? value(...args) : (value === undefined ? { ok: true } : value);
    },
  }) };
</script>
"""


def mock_api(args):
    settings = json.loads(resource_path("default_settings.json").read_text(encoding="utf-8"))
    settings["language"] = args.lang
    settings["web"].update(admin_url="https://example.com", username="operator01")
    update = None
    if args.update_version:
        update = {
            "version": args.update_version,
            "current": __version__,
            "release_notes": "" if args.no_notes else SAMPLE_RELEASE_NOTES,
        }
    return {
        "get_setup_state": {
            "step": "settings",
            "configured": True,
            "first_run": False,
            "languages": [
                {"code": code, "native": i18n.LANGUAGE_NAMES[code], "english": i18n.LANGUAGE_ENGLISH_NAMES[code]}
                for code in i18n.LANGUAGES
            ],
            "system_language": args.lang,
            "language": args.lang,
            "admin_url": "https://example.com",
            "username": "operator01",
            "logged_in": True,
            "expired_at": None,
            "business_script": settings["business_script"],
            "business_script_error": None,
        },
        "get_settings": settings,
        "get_ocr_backends": [{"name": "paddleocr", "label": "PaddleOCR", "available": True}],
        "get_status": {"ocr_backend": None},
        "get_installed_business_scripts": [],
        "get_default_captures_dir": "~/Library/Application Support/EzyOCR/captures",
        "get_operator_settings": {"ok": True, "operator": True, "settings": {"requireBarcode": True}},
        "get_update_info": update,
    }


def main():
    parser = argparse.ArgumentParser(description="Preview the station settings page in a browser with mock data")
    parser.add_argument("--lang", choices=i18n.LANGUAGES, default="vi")
    parser.add_argument("--update-version", default="0.1.0", help="new version to show, empty to hide the update banner")
    parser.add_argument("--no-notes", action="store_true", help="hide the release notes")
    args = parser.parse_args()
    i18n.set_language(args.lang)
    page = i18n.render_page("setup.html")
    mock = json.dumps(mock_api(args), ensure_ascii=False).replace("</", "<\\/")
    page = page.replace("<script>", MOCK_API.replace("__MOCK__", mock) + "<script>", 1)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(page, encoding="utf-8")
    print(OUTPUT_FILE)
    webbrowser.open(OUTPUT_FILE.as_uri())


if __name__ == "__main__":
    main()
