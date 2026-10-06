#!/bin/zsh
# Builds an unsigned, self-contained local AppKit host. The app contains a
# private Python runtime and the parser/model source, while mutable card cache,
# history and the state bridge live in the user's Application Support folder.
set -euo pipefail
ROOT="${0:A:h:h}"
APP="$ROOT/dist/OpenBattlegroundsOverlay.app"
MACOS="$APP/Contents/MacOS"
RESOURCES="$APP/Contents/Resources"
mkdir -p "$MACOS"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>en</string>
  <key>CFBundleDisplayName</key><string>Open Battlegrounds Overlay</string>
  <key>CFBundleExecutable</key><string>OpenBattlegroundsOverlay</string>
  <key>CFBundleIdentifier</key><string>local.openbattlegrounds.overlay</string>
  <key>CFBundleIconFile</key><string>OpenBattlegroundsOverlay.icns</string>
  <key>CFBundleName</key><string>Open Battlegrounds Overlay</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><false/>
</dict>
</plist>
PLIST
SDK="$(/usr/bin/xcrun --sdk macosx --show-sdk-path)"
MODULE_CACHE="$ROOT/.work/native-clang-cache"
mkdir -p "$MODULE_CACHE"
/usr/bin/xcrun clang -isysroot "$SDK" -fobjc-arc -fmodules -fmodules-cache-path="$MODULE_CACHE" -framework Cocoa \
  "$ROOT/native_macos/OpenBattlegroundsOverlay.m" -o "$MACOS/OpenBattlegroundsOverlay"
rm -rf "$RESOURCES/tracker" "$RESOURCES/tracker_seed" "$RESOURCES/python-runtime"
mkdir -p "$RESOURCES/tracker" "$RESOURCES/tracker_seed/data"
cp "$ROOT/assets/OpenBattlegroundsOverlay.icns" "$RESOURCES/OpenBattlegroundsOverlay.icns"
for source in advisor.py cards_db.py combat.py config.py demo.py history.py insights.py main.py native_feed.py parser.py; do
  cp "$ROOT/$source" "$RESOURCES/tracker/$source"
done
if [[ -f "$ROOT/data/cards.json" ]]; then
  cp "$ROOT/data/cards.json" "$RESOURCES/tracker_seed/data/cards.json"
else
  print -u2 "Missing data/cards.json; the installed app will need to fetch card metadata on first launch."
fi
PYTHON_RUNTIME="${OPEN_BATTLEGROUNDS_PYTHON_RUNTIME:-$(python3 -c 'import sys; print(sys.prefix)')}"
if [[ ! -x "$PYTHON_RUNTIME/bin/python3" ]]; then
  print -u2 "A Python runtime was not found at $PYTHON_RUNTIME. Set OPEN_BATTLEGROUNDS_PYTHON_RUNTIME to a Python installation root."
  exit 1
fi
/usr/bin/ditto "$PYTHON_RUNTIME" "$RESOURCES/python-runtime"
printf 'Built %s\n' "$APP"
