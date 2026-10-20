import json
import ssl
import uuid
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

import certifi

RETRYABLE_STATUSES = {401, 403, 408, 425, 429}


class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body

    @property
    def retryable(self):
        return self.status >= 500 or self.status in RETRYABLE_STATUSES


class EzyPlatformClient:
    def __init__(self, base_url, settings):
        parts = urlsplit(base_url)
        self._base_url = f"{parts.scheme}://{parts.netloc}"
        self._settings = settings
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

    def upload_media(self, access_token, file_path, file_name):
        with open(file_path, "rb") as f:
            content = f.read()
        boundary = uuid.uuid4().hex
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode(),
            b"Content-Type: image/jpeg\r\n\r\n",
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ])
        response = self._request(
            "POST",
            self._settings.media_path,
            access_token,
            body,
            f"multipart/form-data; boundary={boundary}",
        )
        return int(json.loads(response)["id"])

    def link_media(self, access_token, link_path, code, media_id):
        path = link_path.format(
            code=quote(code, safe=""),
            media_id=media_id,
        )
        self._request("PUT", path, access_token)

    def _request(self, method, path, access_token, body=None, content_type=None):
        request = urllib.request.Request(self._base_url + path, data=body, method=method)
        request.add_header("Authorization", f"Bearer {access_token}")
        request.add_header("Accept", "application/json")
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(
                request,
                timeout=self._settings.timeout_seconds,
                context=self._ssl_context,
            ) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            raise HttpError(e.code, e.read().decode("utf-8", "replace")) from e
