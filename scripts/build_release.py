import argparse
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
RELEASE_DIR = ROOT / "release"
NOTES_FILE = "NOTES.md"

BUILDS = {
    "macos": (["bash", "scripts/build_macos.sh"], ".dmg"),
    "windows": (
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts\\build_windows.ps1"],
        ".msi",
    ),
    "linux": (["bash", "scripts/build_linux.sh"], ".deb"),
}


def read_version():
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def current_os():
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    sys.exit(f"Unsupported platform: {sys.platform}")


def current_arch():
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64", "x64"):
        return "x64"
    if machine in ("x86", "i386", "i686"):
        return "x86"
    sys.exit(f"Unsupported architecture: {platform.machine()}")


def find_package(version, extension):
    packages = [
        path for path in DIST_DIR.glob(f"*{extension}")
        if path.is_file() and version in path.name
    ]
    if not packages:
        sys.exit(f"No {extension} for version {version} in {DIST_DIR}")
    return max(packages, key=lambda path: path.stat().st_mtime)


def main():
    parser = argparse.ArgumentParser(description="Build EzyOCR and collect the installer into release/<tag>")
    parser.add_argument("--skip-build", action="store_true", help="only collect the installer already in dist/")
    args = parser.parse_args()

    version = read_version()
    os_name = current_os()
    arch = current_arch()
    command, extension = BUILDS[os_name]
    print(f"==> EzyOCR {version} for {os_name}-{arch}")

    if not args.skip_build:
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode != 0:
            sys.exit(result.returncode)

    package = find_package(version, extension)
    target_dir = RELEASE_DIR / f"v{version}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"ezyocr-{version}-{os_name}-{arch}{extension}"
    shutil.copy2(package, target)
    notes = target_dir / NOTES_FILE
    if not notes.exists():
        notes.write_text(f"# EzyOCR {version}\n", encoding="utf-8")
    print(f"==> Release file: {target}")
    print(f"==> Release notes: {notes}")


if __name__ == "__main__":
    main()
