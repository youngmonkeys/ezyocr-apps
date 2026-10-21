import hashlib
import logging
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlsplit

import certifi

from ezyocr import __version__
from ezyocr.paths import logs_dir, updates_dir

logger = logging.getLogger(__name__)

PACKAGE_MSI = "MSI"
PACKAGE_DMG = "DMG"
PACKAGE_DEB = "DEB"
LINUX_APP_DIR = Path("/usr/lib/ezyocr")
LINUX_EXECUTABLE = Path("/usr/bin/ezyocr")
DOWNLOAD_TIMEOUT_SECONDS = 60
CHUNK_SIZE = 1 << 16
PART_SUFFIX = ".part"
SAFE_FILE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
PYTHON_EXECUTABLES = {"python", "pythonw", "python3"}

_MACOS_INSTALL_SCRIPT = r'''
pid="$0"; dmg="$1"; bundle="$2"
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
echo "$(date) installing $dmg to $bundle"
mnt="$(mktemp -d /tmp/ezyocr-update.XXXXXX)"
if hdiutil attach -nobrowse -readonly -noverify -mountpoint "$mnt" "$dmg" >/dev/null; then
    app="$(find "$mnt" -maxdepth 1 -name '*.app' -print -quit)"
    rm -rf "$bundle.new" "$bundle.old"
    if [ -n "$app" ] && ditto "$app" "$bundle.new"; then
        if mv "$bundle" "$bundle.old" && mv "$bundle.new" "$bundle"; then
            rm -rf "$bundle.old"
            echo "$(date) installed"
        else
            echo "$(date) cannot replace the app"
        fi
    else
        echo "$(date) cannot copy the app from the disk image"
    fi
    rm -rf "$bundle.new"
    [ -d "$bundle" ] || mv "$bundle.old" "$bundle"
    hdiutil detach "$mnt" -quiet || hdiutil detach "$mnt" -force -quiet
else
    echo "$(date) cannot mount $dmg"
fi
rmdir "$mnt" 2>/dev/null
open "$bundle"
'''

_LINUX_INSTALL_SCRIPT = r'''
pid="$0"; deb="$1"; exe="$2"
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
echo "$(date) installing $deb"
if pkexec apt-get install -y --allow-downgrades "$deb"; then
    echo "$(date) installed"
else
    echo "$(date) apt-get exit code $?"
fi
exec "$exe"
'''

_WINDOWS_INSTALL_SCRIPT = r'''
$ErrorActionPreference = "Continue"
while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ Start-Sleep -Milliseconds 200 }}
Add-Content -Path {log} -Value ((Get-Date).ToString() + " installing " + {msi})
$process = Start-Process -FilePath "msiexec.exe" -ArgumentList @("/i", ('"' + {msi} + '"'), "/passive", "/norestart") -Wait -PassThru
Add-Content -Path {log} -Value ((Get-Date).ToString() + " msiexec exit code " + $process.ExitCode)
Start-Process -FilePath {exe}
'''


class UpdateError(Exception):
    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def current_os():
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


def current_arch():
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64", "x64"):
        return "x64"
    if machine in ("x86", "i386", "i686"):
        return "x86"
    return None


def download(info, on_progress=None):
    url = str(info.get("url") or "")
    if urlsplit(url).scheme not in ("http", "https"):
        raise UpdateError("invalid_download", url)
    target = updates_dir() / _file_name(info, url)
    expected_size = int(info.get("size") or 0)
    expected_sha256 = str(info.get("sha256") or "").lower() or None
    _remove_other_files(target)
    if target.is_file() and expected_sha256 and _sha256_of(target) == expected_sha256:
        logger.info("Update %s was already downloaded", target)
        return target
    part = target.with_name(target.name + PART_SUFFIX)
    request = urllib.request.Request(url, method=str(info.get("method") or "GET").upper())
    request.add_header("User-Agent", f"EzyOCR/{__version__}")
    for name, value in (info.get("headers") or {}).items():
        request.add_header(str(name), str(value))
    handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))]
    if info.get("followRedirects") is False:
        handlers.append(_NoRedirect())
    opener = urllib.request.build_opener(*handlers)
    digest = hashlib.sha256()
    done = 0
    try:
        with opener.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, part.open("wb") as f:
            total = expected_size or int(response.headers.get("Content-Length") or 0)
            while chunk := response.read(CHUNK_SIZE):
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    if expected_size and done != expected_size:
        part.unlink(missing_ok=True)
        raise UpdateError("size_mismatch", f"{done} != {expected_size}")
    if expected_sha256 and digest.hexdigest() != expected_sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("checksum_mismatch")
    os.replace(part, target)
    logger.info("Downloaded update %s (%d bytes)", target, done)
    return target


def can_install(package_type):
    if package_type == PACKAGE_MSI:
        return _windows_executable() is not None
    if package_type == PACKAGE_DMG:
        bundle = _macos_bundle()
        return bundle is not None and os.access(bundle.parent, os.W_OK)
    if package_type == PACKAGE_DEB:
        return _linux_executable() is not None and shutil.which("pkexec") is not None
    return False


def install_after_exit(path, package_type):
    log_file = logs_dir() / "update.log"
    if package_type == PACKAGE_DMG:
        with log_file.open("a", encoding="utf-8") as log:
            subprocess.Popen(
                ["/bin/sh", "-c", _MACOS_INSTALL_SCRIPT, str(os.getpid()), str(path), str(_macos_bundle())],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return
    if package_type == PACKAGE_DEB:
        with log_file.open("a", encoding="utf-8") as log:
            subprocess.Popen(
                ["/bin/sh", "-c", _LINUX_INSTALL_SCRIPT, str(os.getpid()), str(path), str(_linux_executable())],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return
    if package_type == PACKAGE_MSI:
        script = _WINDOWS_INSTALL_SCRIPT.format(
            pid=os.getpid(),
            log=_ps_quote(str(log_file)),
            msi=_ps_quote(str(path)),
            exe=_ps_quote(str(_windows_executable())),
        )
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", script],
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        )
        return
    raise UpdateError("unsupported_package", package_type)


def reveal(path):
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", f"/select,{path}"])
        else:
            subprocess.Popen(["xdg-open", str(Path(path).parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        logger.debug("Cannot reveal %s", path, exc_info=True)


def _file_name(info, url):
    name = Path(str(info.get("fileName") or "")).name or Path(unquote(urlsplit(url).path)).name
    name = SAFE_FILE_NAME.sub("_", name).strip("._")
    return name or "ezyocr-update"


def _remove_other_files(target):
    for path in updates_dir().iterdir():
        if path.is_file() and path.name != target.name:
            path.unlink(missing_ok=True)


def _sha256_of(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _macos_bundle():
    if sys.platform != "darwin":
        return None
    try:
        from Foundation import NSBundle
    except ImportError:
        return None
    bundle = Path(str(NSBundle.mainBundle().bundlePath()))
    package_dir = Path(__file__).resolve().parent
    if bundle.suffix == ".app" and package_dir.is_relative_to(bundle):
        return bundle
    return None


def _windows_executable():
    if sys.platform != "win32":
        return None
    executable = Path(sys.executable)
    if executable.stem.lower() in PYTHON_EXECUTABLES:
        return None
    return executable


def _linux_executable():
    if not sys.platform.startswith("linux"):
        return None
    if not Path(__file__).resolve().is_relative_to(LINUX_APP_DIR) or not LINUX_EXECUTABLE.is_file():
        return None
    return LINUX_EXECUTABLE


def _ps_quote(value):
    return "'" + value.replace("'", "''") + "'"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
