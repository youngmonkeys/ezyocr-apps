import argparse
import hashlib
import json
import mimetypes
import re
import shutil
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "output" / "mock-github"
NOTES_FILE = "NOTES.md"
SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SAMPLE_REPOSITORY = ("youngmonkeys", "ezyocr-apps")
SAMPLE_TAG = "v1.0.0"
SAMPLE_ASSETS = (
    "ezyocr-windows-x64.zip",
    "ezyocr-macos-arm64.dmg",
    "ezyocr-linux-x64.AppImage",
)


def version_key(tag):
    parts = re.split(r"[.\-+_]", tag.lower().removeprefix("v"))
    return [(0, int(part), "") if part.isdigit() else (-1, 0, part) for part in parts]


def iso_time(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 16):
            digest.update(chunk)
    return digest.hexdigest()


def is_safe(*segments):
    return all(SEGMENT_PATTERN.match(segment) and segment not in (".", "..") for segment in segments)


class MockGithub:
    def __init__(self, data_dir):
        self.data_dir = data_dir

    def tags(self, owner, repo):
        repo_dir = self.data_dir / owner / repo
        if not repo_dir.is_dir():
            return []
        tags = [path.name for path in repo_dir.iterdir() if path.is_dir() and is_safe(path.name)]
        return sorted(tags, key=version_key, reverse=True)

    def release(self, base_url, owner, repo, tag):
        release_dir = self.data_dir / owner / repo / tag
        if not release_dir.is_dir():
            return None
        notes_path = release_dir / NOTES_FILE
        files = sorted(
            path for path in release_dir.iterdir()
            if path.is_file() and path.name != NOTES_FILE and not path.name.startswith(".")
        )
        published_at = iso_time(release_dir.stat().st_mtime)
        assets = []
        for index, path in enumerate(files, start=1):
            stat = path.stat()
            assets.append({
                "id": index,
                "name": path.name,
                "label": None,
                "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "state": "uploaded",
                "size": stat.st_size,
                "digest": "sha256:" + sha256_of(path),
                "download_count": 0,
                "created_at": iso_time(stat.st_mtime),
                "updated_at": iso_time(stat.st_mtime),
                "url": f"{base_url}/repos/{owner}/{repo}/releases/assets/{index}",
                "browser_download_url": f"{base_url}/{owner}/{repo}/releases/download/{quote(tag)}/{quote(path.name)}",
            })
        return {
            "id": abs(hash((owner, repo, tag))) % 10_000_000,
            "tag_name": tag,
            "name": tag,
            "body": notes_path.read_text(encoding="utf-8") if notes_path.is_file() else "",
            "draft": False,
            "prerelease": False,
            "created_at": published_at,
            "published_at": published_at,
            "html_url": f"{base_url}/{owner}/{repo}/releases/tag/{quote(tag)}",
            "url": f"{base_url}/repos/{owner}/{repo}/releases/tags/{quote(tag)}",
            "assets": assets,
        }

    def init_sample(self):
        owner, repo = SAMPLE_REPOSITORY
        release_dir = self.data_dir / owner / repo / SAMPLE_TAG
        if release_dir.exists():
            return release_dir
        release_dir.mkdir(parents=True)
        for name in SAMPLE_ASSETS:
            (release_dir / name).write_bytes(f"mock content of {name}\n".encode() * 1024)
        (release_dir / NOTES_FILE).write_text("- First mock release\n", encoding="utf-8")
        return release_dir


class Handler(BaseHTTPRequestHandler):
    server_version = "MockGitHub/1.0"
    github = None

    def do_GET(self):
        self.route(send_body=True)

    def do_HEAD(self):
        self.route(send_body=False)

    def route(self, send_body):
        segments = [unquote(segment) for segment in urlsplit(self.path).path.strip("/").split("/") if segment]
        if not is_safe(*segments):
            return self.send_json({"message": "Not Found"}, HTTPStatus.NOT_FOUND, send_body)
        if len(segments) >= 4 and segments[0] == "repos" and segments[3] == "releases":
            return self.route_api(segments[1], segments[2], segments[4:], send_body)
        if len(segments) == 6 and segments[2:4] == ["releases", "download"]:
            return self.redirect(f"/_objects/{'/'.join(quote(s) for s in segments[:2] + segments[4:])}")
        if len(segments) == 6 and segments[2:5] == ["releases", "latest", "download"]:
            tags = self.github.tags(segments[0], segments[1])
            if not tags:
                return self.send_json({"message": "Not Found"}, HTTPStatus.NOT_FOUND, send_body)
            return self.redirect(f"/_objects/{quote(segments[0])}/{quote(segments[1])}/{quote(tags[0])}/{quote(segments[5])}")
        if len(segments) == 5 and segments[0] == "_objects":
            return self.send_file(self.github.data_dir.joinpath(*segments[1:]), send_body)
        self.send_json({"message": "Not Found"}, HTTPStatus.NOT_FOUND, send_body)

    def route_api(self, owner, repo, rest, send_body):
        base_url = self.base_url()
        tags = self.github.tags(owner, repo)
        if not rest:
            releases = [self.github.release(base_url, owner, repo, tag) for tag in tags]
            return self.send_json(releases, HTTPStatus.OK, send_body)
        if rest == ["latest"]:
            tag = tags[0] if tags else None
        elif len(rest) == 2 and rest[0] == "tags":
            tag = rest[1]
        else:
            tag = None
        release = self.github.release(base_url, owner, repo, tag) if tag else None
        if release is None:
            return self.send_json({"message": "Not Found"}, HTTPStatus.NOT_FOUND, send_body)
        self.send_json(release, HTTPStatus.OK, send_body)

    def base_url(self):
        return f"http://{self.headers.get('Host') or '%s:%d' % self.server.server_address[:2]}"

    def redirect(self, location):
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_json(self, data, status, send_body):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-RateLimit-Limit", "60")
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def send_file(self, path, send_body):
        if not path.is_file() or path.name == NOTES_FILE:
            return self.send_json({"message": "Not Found"}, HTTPStatus.NOT_FOUND, send_body)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Content-Disposition", f"attachment; filename={quote(path.name)}")
        self.end_headers()
        if send_body:
            with path.open("rb") as f:
                shutil.copyfileobj(f, self.wfile)


def main():
    parser = argparse.ArgumentParser(description="Mock GitHub releases API for local testing")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--init", action="store_true", help=f"create a sample {SAMPLE_TAG} release if missing")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    Handler.github = MockGithub(data_dir)
    if args.init:
        print(f"sample release: {Handler.github.init_sample()}")
    print(f"data dir: {data_dir}")
    print(f"layout: <data dir>/<owner>/<repo>/<tag>/<asset files> (+ optional {NOTES_FILE})")
    print(f"listening on http://{args.host}:{args.port}")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
