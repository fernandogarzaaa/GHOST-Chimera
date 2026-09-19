#!/bin/bash
# Build the Ghost Chimera macOS app + DMG. Run from the repo root:
#   bash packaging/macos/build-macos-app.sh
# Requires: Python 3.11+, Xcode CLT (for hdiutil codesign basics).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

VERSION="${GHOSTCHIMERA_VERSION:-$(python3 -c "import ghostchimera; print(ghostchimera.__version__)")}"
echo "Ghost Chimera $VERSION"

python3 -m pip install --upgrade pip
python3 -m pip install ".[gateway]" pyinstaller pillow

python3 packaging/assets/generate_icons.py --out packaging/assets

pyinstaller packaging/ghostchimera.spec --distpath dist-desktop --workpath build-desktop -y

# Assemble Ghost Chimera.app around the one-dir bundle.
APP="dist-desktop/Ghost Chimera.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -R dist-desktop/GhostChimera/* "$APP/Contents/MacOS/"
cp packaging/assets/ghost.icns "$APP/Contents/Resources/ghost.icns"
sed "s/__GHOSTCHIMERA_VERSION__/${VERSION}/g" packaging/macos/Info.plist > "$APP/Contents/Info.plist"

# Smoke test: launch, wait for /health on the RESOLVED url, kill.
# Ports auto-resolve when busy, so parse the printed console URL instead of
# assuming 8766. Unbuffered output keeps the URL line visible promptly.
export PYTHONUNBUFFERED=1
"$APP/Contents/MacOS/GhostConsole" &>/tmp/ghost-console-smoke.log &
SMOKE_PID=$!
SMOKE_OK=0
SMOKE_URL=""
for _ in $(seq 1 40); do
  SMOKE_URL=$(grep -oE 'Ghost Console: http://[^ ]+' /tmp/ghost-console-smoke.log 2>/dev/null | tail -1 | sed 's/^Ghost Console: //')
  if [ -n "$SMOKE_URL" ] && curl -fsS "${SMOKE_URL}health" >/dev/null 2>&1; then SMOKE_OK=1; break; fi
  sleep 3
done
kill "$SMOKE_PID" 2>/dev/null || true
if [ "$SMOKE_OK" != "1" ]; then
  echo "Smoke test failed — see /tmp/ghost-console-smoke.log"
  exit 1
fi
echo "Smoke test passed ($SMOKE_URL)."

# Pack a drag-to-Applications DMG.
DMG_DIR="dist-desktop/dmg-staging"
DMG="dist-desktop/GhostChimera-${VERSION}-macOS.dmg"
rm -rf "$DMG_DIR" "$DMG"
mkdir -p "$DMG_DIR"
cp -R "$APP" "$DMG_DIR/"
ln -s /Applications "$DMG_DIR/Applications"
hdiutil create -volname "Ghost Chimera" -srcfolder "$DMG_DIR" -ov -format UDZO "$DMG"
echo "DMG ready: $DMG"
echo "NOTE: unsigned build — notarize with an Apple Developer ID before public distribution."
