#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
MODELS_DIR="src/ezyocr/resources/models"
APP_DIR="build/ezyocr/macos/app"

if [ -z "$(find "$MODELS_DIR" -mindepth 1 -maxdepth 1 -type d 2>/dev/null)" ]; then
    echo "==> Downloading OCR models"
    "$PYTHON" scripts/fetch_models.py
fi

if [ ! -f packaging/icons/ezyocr.icns ]; then
    echo "==> Generating app icon"
    "$PYTHON" scripts/make_icon.py
fi

if [ -d "$APP_DIR" ] && ! cmp -s pyproject.toml "$APP_DIR/.pyproject.toml"; then
    echo "==> pyproject.toml changed, recreating app"
    rm -rf "$APP_DIR"
fi

if [ -d "$APP_DIR" ]; then
    echo "==> Updating app bundle"
    "$PYTHON" -m briefcase update macOS app --update-requirements --update-resources --no-input
else
    echo "==> Creating app bundle"
    "$PYTHON" -m briefcase create macOS app --no-input
    cp pyproject.toml "$APP_DIR/.pyproject.toml"
fi

echo "==> Building app"
"$PYTHON" -m briefcase build macOS app --no-input

echo "==> Packaging DMG"
if [ -n "${SIGN_IDENTITY:-}" ]; then
    "$PYTHON" -m briefcase package macOS app --identity "$SIGN_IDENTITY" --no-input
else
    "$PYTHON" -m briefcase package macOS app --adhoc-sign --no-input
fi

echo "==> Done:"
ls -1 dist/*.dmg
