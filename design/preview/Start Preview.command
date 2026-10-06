#!/bin/zsh
preview_dir="${0:A:h}"
exec /usr/bin/env python3 "$preview_dir/serve.py" --port 0 --open
