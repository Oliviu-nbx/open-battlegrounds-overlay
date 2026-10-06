#!/usr/bin/env python3
"""Serve only the public design-preview assets on the loopback interface."""
from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
import webbrowser

ROOT = Path(__file__).resolve().parent
ASSETS = {"/", "/index.html", "/styles.css", "/app.js"}


class PreviewHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        # Do not expose neighboring tracker files, settings, or private data.
        if unquote(urlsplit(self.path).path) not in ASSETS:
            self.send_error(404, "Preview asset not found")
            return None
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8769, help="Local port; 0 selects an available port")
    parser.add_argument("--open", action="store_true", help="Open the preview in your default browser")
    args = parser.parse_args()
    handler = functools.partial(PreviewHandler, directory=str(ROOT))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except (OSError, OverflowError) as error:
        parser.exit(1, f"Could not start the local preview: {error}. Try --port 0.\n")
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Design preview: {url}\nSample data only. Press Ctrl+C to stop.", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPreview stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
