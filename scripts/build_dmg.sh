#!/bin/bash
# Build an unsigned, drag-to-Applications DMG for Claude Usage Bar.
#
#   bash scripts/build_dmg.sh
#
# Produces: dist/Claude-Usage-Bar.dmg
# Unsigned: first launch needs right-click -> Open (Gatekeeper). See README.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

APP="dist/Claude Usage Bar.app"
VOL="Claude Usage Bar"
DMG="dist/Claude-Usage-Bar.dmg"

# Ensure a fresh app bundle exists.
if [ ! -d "$APP" ]; then
    echo "App bundle missing — building it first..."
    bash scripts/build_app.sh
fi

# Strip quarantine so the packaged copy is clean.
xattr -cr "$APP" 2>/dev/null || true

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"   # drag-to-install target

rm -f "$DMG"
hdiutil create \
    -volname "$VOL" \
    -srcfolder "$STAGE" \
    -fs HFS+ \
    -format UDZO \
    -ov \
    "$DMG" >/dev/null

SIZE="$(du -sh "$DMG" | cut -f1)"
echo "Built: $DMG ($SIZE)"
echo "Unsigned — recipients: right-click the app in the DMG -> Open on first launch."
