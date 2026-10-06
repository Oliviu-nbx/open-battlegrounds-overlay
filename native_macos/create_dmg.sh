#!/bin/zsh
# Creates a local, unsigned drag-to-Applications DMG from the self-contained app.
set -euo pipefail
ROOT="${0:A:h:h}"
APP="$ROOT/dist/OpenBattlegroundsOverlay.app"
STAGING="$ROOT/.work/dmg-root"
DMG="$ROOT/dist/OpenBattlegroundsOverlay.dmg"
/bin/zsh "$ROOT/native_macos/build_native_overlay.sh"
rm -rf "$STAGING"
mkdir -p "$STAGING"
/usr/bin/ditto "$APP" "$STAGING/Open Battlegrounds Overlay.app"
ln -s /Applications "$STAGING/Applications"
cat > "$STAGING/README.txt" <<'README'
Open Battlegrounds Overlay

1. Drag “Open Battlegrounds Overlay.app” to the Applications alias.
2. Open it from Applications. The panel stays above compatible full-screen
   game spaces while reading only local Hearthstone Power.log data.
3. Press Command-Q while the panel is active to close it.

The app bundles its private parser/model runtime. Mutable card cache, history,
and live state remain local in ~/Library/Application Support/OpenBattlegroundsOverlay.
No game actions, screen capture, or uploads are performed.

This is a locally built, unsigned application. On a different Mac, macOS may
ask you to Control-click the app and choose Open once because it is not
Developer-ID signed or notarized.
README
rm -f "$DMG"
/usr/bin/hdiutil create -volname "Open Battlegrounds Overlay" -srcfolder "$STAGING" -format UDZO -ov "$DMG"
printf 'Created %s\n' "$DMG"
