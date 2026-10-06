#!/bin/zsh
# Double-click in Finder; use a modern Tk without depending on shell PATH.
# main.py now opens the redesigned native interface, not the browser prototype.
cd "${0:A:h}" || exit 1
for tracker_python in \
    "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" \
    /opt/homebrew/bin/python3 /usr/local/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/*/bin/python3(N); do
    if [[ -x "$tracker_python" ]] && "$tracker_python" -c \
        'import tkinter, sys; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)' 2>/dev/null; then
        exec "$tracker_python" main.py "$@"
    fi
done
echo "Install a current Python.org macOS Python with Tk 8.6 or newer."
read -r "tracker_reply?Press Return to close. "
