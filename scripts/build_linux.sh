#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
MODELS_DIR="src/ezyocr/resources/models"

if [ "$(uname -s)" != "Linux" ]; then
    echo "This script must run on Ubuntu" >&2
    exit 1
fi

APP_DIR="build/ezyocr/ubuntu/$(. /etc/os-release && echo "$VERSION_CODENAME")"

if [ ! -x "$PYTHON" ]; then
    echo "==> Creating virtual environment"
    /usr/bin/python3 -m venv .venv
    "$PYTHON" -m pip install --upgrade pip
    "$PYTHON" -m pip install -e ".[dev]"
fi

if [ -z "$(find "$MODELS_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null)" ]; then
    echo "==> Downloading OCR models"
    "$PYTHON" scripts/fetch_models.py
fi

if [ ! -f packaging/icons/ezyocr-512.png ]; then
    echo "==> Generating app icon"
    "$PYTHON" scripts/make_icon.py
fi

if [ -d "$APP_DIR" ] && ! cmp -s pyproject.toml "$APP_DIR/.pyproject.toml"; then
    echo "==> pyproject.toml changed, recreating app"
    rm -rf "$APP_DIR"
fi

if [ -d "$APP_DIR" ]; then
    echo "==> Updating app"
    "$PYTHON" -m briefcase update linux system --update-requirements --update-resources --no-input
else
    echo "==> Creating app"
    "$PYTHON" -m briefcase create linux system --no-input
    cp pyproject.toml "$APP_DIR/.pyproject.toml"
fi

echo "==> Building app"
"$PYTHON" -m briefcase build linux system --no-input

echo "==> Packaging DEB"
"$PYTHON" -m briefcase package linux system --no-input

echo "==> Done:"
ls -1 dist/*.deb
