#!/bin/zsh
# Double-click in Finder to launch the native AppKit always-on-top rail.
# It starts a local Python feed and never clicks or automates Hearthstone.
set -euo pipefail
ROOT="${0:A:h}"
cd "$ROOT"
for tracker_python in \
    "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" \
    /opt/homebrew/bin/python3 /usr/local/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/*/bin/python3(N); do
    if [[ -x "$tracker_python" ]] && "$tracker_python" -c \
        'import tkinter, sys; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)' 2>/dev/null; then
        "$ROOT/native_macos/build_native_overlay.sh"
        exec "$ROOT/dist/OpenBattlegroundsOverlay.app/Contents/MacOS/OpenBattlegroundsOverlay" \
            --project "$ROOT" --python "$tracker_python" "$@"
    fi
done
echo "Install a current Python.org macOS Python with Tk 8.6 or newer."
read -r "tracker_reply?Press Return to close. "
