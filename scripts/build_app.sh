#!/bin/bash
# Build Claude Usage Bar.app for local use (semi-standalone: deps bundled, system Python).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

rm -rf dist build
/usr/local/bin/python3.11 setup.py py2app --semi-standalone 2>&1

APP="dist/Claude Usage Bar.app"
xattr -c "$APP" 2>/dev/null || true
echo "Built: $APP ($(du -sh "$APP" | cut -f1))"
