#!/bin/bash
# Build Claude Usage Bar.app for local use (semi-standalone: deps bundled, system Python).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

# A previously-opened dist/ (Finder/Spotlight) can hold locks that make a plain
# `rm -rf` fail with "Directory not empty"; clear permissions and retry.
chmod -R u+w dist build 2>/dev/null || true
rm -rf dist build 2>/dev/null || { sleep 1; rm -rf dist build; }

# Regenerate the app icon if the generator changed (cheap, keeps icns in sync).
if [ -f make_icon.py ] && [ ! -f AppIcon.icns ]; then
    /usr/local/bin/python3.11 make_icon.py || true
fi

/usr/local/bin/python3.11 setup.py py2app --semi-standalone 2>&1

APP="dist/Claude Usage Bar.app"
xattr -c "$APP" 2>/dev/null || true
echo "Built: $APP ($(du -sh "$APP" | cut -f1))"
