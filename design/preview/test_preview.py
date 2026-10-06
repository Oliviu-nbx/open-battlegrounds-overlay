"""Standard-library checks for the isolated, loopback-only preview server."""
import functools
from http.server import ThreadingHTTPServer
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from serve import PreviewHandler, ROOT


class QuietHandler(PreviewHandler):
    def log_message(self, *_args):
        pass


class PreviewServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(ROOT))
        )
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.worker.join(timeout=2)
        cls.server.server_close()

    def test_assets_and_security_headers(self):
        for path in ("/", "/index.html", "/styles.css", "/app.js"):
            with self.subTest(path=path), urlopen(self.url + path, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertGreater(len(response.read()), 100)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertIn("connect-src 'none'", response.headers["Content-Security-Policy"])

    def test_private_and_traversal_paths_are_not_served(self):
        for path in ("/README.md", "/serve.py", "/data/cards.json", "/../main.py",
                     "/%2e%2e/main.py", "/.impeccable/design.json"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(self.url + path, timeout=2)
            self.assertEqual(error.exception.code, 404)

    def test_head_has_no_body(self):
        request = Request(self.url + "/", method="HEAD")
        with urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"")


if __name__ == "__main__":
    unittest.main()
