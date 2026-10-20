import json
import ssl
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from urllib.parse import quote, urlencode, urljoin, urlsplit

import certifi

from ezyocr.session import StaffSession, parse_expired_at
from ezyocr.upload.client import HttpError

LOGIN_PATH = "/login"
FETCH_TO_COOKIE_PATH = "/api/v1/admins/me/access-token/fetch-to-cookie"
BUSINESS_SCRIPTS_PATH = "/ezyocr/api/v1/ocr-business-scripts"
BUSINESS_SCRIPT_CATEGORIES_PATH = f"{BUSINESS_SCRIPTS_PATH}/categories"
LATEST_APP_RELEASE_PATH = "/ezyocr/api/v1/app-releases/latest"
OCR_OPERATOR_SETTINGS_PATH = "/ezyocr/api/v1/ocr-operators/me/settings"
TOKEN_COOKIE = "adminAccessToken"
EXPIRED_AT_COOKIE = "adminAccessTokenExpiredAt"
DEFAULT_TIMEOUT_SECONDS = 30


class LoginError(Exception):
    INVALID_CREDENTIALS = "invalid_credentials"
    TWO_FACTOR = "two_factor"
    UNEXPECTED = "unexpected"

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class AdminClient:
    def __init__(self, admin_url, timeout=DEFAULT_TIMEOUT_SECONDS):
        self.admin_url = admin_url.rstrip("/")
        self._timeout = timeout
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

    def login(self, username, password):
        body = urlencode({"username": username, "password": password}).encode()
        request = urllib.request.Request(self.admin_url + LOGIN_PATH, data=body, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=self._ssl_context))
        try:
            with opener.open(request, timeout=self._timeout) as response:
                status, headers = response.status, response.headers
        except urllib.error.HTTPError as e:
            status, headers = e.code, e.headers
        if status not in (301, 302, 303, 307, 308):
            raise LoginError(LoginError.UNEXPECTED, f"HTTP {status}")
        location = urlsplit(urljoin(self.admin_url + "/", headers.get("Location") or "")).path.rstrip("/")
        if location.endswith("/2fa"):
            raise LoginError(LoginError.TWO_FACTOR)
        cookies = SimpleCookie()
        for header in headers.get_all("Set-Cookie") or []:
            cookies.load(header)
        token = cookies[TOKEN_COOKIE].value if TOKEN_COOKIE in cookies else ""
        if not token or location.endswith(LOGIN_PATH):
            raise LoginError(LoginError.INVALID_CREDENTIALS)
        expired_at = cookies[EXPIRED_AT_COOKIE].value if EXPIRED_AT_COOKIE in cookies else None
        return StaffSession(token, parse_expired_at(expired_at))

    def fetch_to_cookie_url(self, access_token):
        return f"{self.admin_url}{FETCH_TO_COOKIE_PATH}?{TOKEN_COOKIE}={quote(access_token, safe='')}"

    def business_scripts(self, access_token, keyword=None, category_id=None, next_page_token=None, limit=12):
        params = {"status": "PUBLISHED", "limit": limit}
        if keyword:
            params["keyword"] = keyword
        if category_id:
            params["categoryId"] = int(category_id)
        if next_page_token:
            params["nextPageToken"] = next_page_token
        return self._get_json(f"{BUSINESS_SCRIPTS_PATH}?{urlencode(params)}", access_token)

    def business_script_categories(self, access_token, limit=100):
        return self._get_json(f"{BUSINESS_SCRIPT_CATEGORIES_PATH}?{urlencode({'limit': limit})}", access_token)

    def business_script(self, access_token, script_id):
        return self._get_json(f"{BUSINESS_SCRIPTS_PATH}/{int(script_id)}", access_token)

    def latest_app_release(self, access_token, os_name, arch=None, current_version=None):
        params = {}
        if arch:
            params["arch"] = arch
        if current_version:
            params["currentVersion"] = current_version
        query = f"?{urlencode(params)}" if params else ""
        return self._get_json(f"{LATEST_APP_RELEASE_PATH}/{quote(os_name, safe='')}{query}", access_token)

    def ocr_operator_settings(self, access_token):
        return self._get_json(OCR_OPERATOR_SETTINGS_PATH, access_token)

    def absolute_url(self, url):
        return urljoin(self.admin_url + "/", url)

    def get_bytes(self, url, access_token):
        absolute = self.absolute_url(url)
        if urlsplit(absolute).netloc != urlsplit(self.admin_url).netloc:
            access_token = None
        return self._request(absolute, access_token)

    def _get_json(self, path, access_token):
        content, _ = self._request(self.admin_url + path, access_token, "application/json")
        return json.loads(content)

    def _request(self, url, access_token, accept="*/*"):
        request = urllib.request.Request(url, method="GET")
        request.add_header("Accept", accept)
        if access_token:
            request.add_header("Authorization", f"Bearer {access_token}")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout, context=self._ssl_context) as response:
                return response.read(), response.headers.get_content_type()
        except urllib.error.HTTPError as e:
            raise HttpError(e.code, e.read().decode("utf-8", "replace")) from e
