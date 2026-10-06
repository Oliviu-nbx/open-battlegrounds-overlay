"""Offline artwork tests: deterministic bytes, temporary caches and Tk widgets."""
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from card_images import Image, ImageCache, image_url, decode_image, oval_image, badge_number
from cards_db import Card, CardsDatabase
from parser import BattlegroundsState, MinionStats


def pump(root, duration=.35):
    until = time.monotonic()+duration
    while time.monotonic() < until:
        root.update()
        time.sleep(.01)


def payload(size=(256, 256)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "#8040aa").save(buffer, "PNG")
    return buffer.getvalue()


class ImageURLTests(unittest.TestCase):
    def test_paths_and_validation(self):
        self.assertIn("/256x/BG26_001.jpg", image_url("BG26_001", "portrait"))
        self.assertIn("/frFR/512x/BG26_001.png", image_url("BG26_001", "full", "frFR"))
        for identity in ("../data", "https://bad.example", "a/b", "", "a"*101):
            with self.assertRaises(ValueError):
                image_url(identity, "portrait")
        with self.assertRaises(ValueError):
            image_url("BG26_001", "full", "../")

    def test_large_badges_and_exact_small_values(self):
        self.assertEqual(badge_number(None), "—")
        self.assertEqual(badge_number(9999), "9999")
        self.assertEqual(badge_number(12500), "12.5k")
        self.assertEqual(badge_number(1200000), "1.2M")


@unittest.skipIf(Image is None, "Install Pillow for image-processing tests")
class ImageCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.calls = []
        self.data = payload()
        def opener(request, timeout):
            self.calls.append(request.full_url)
            stream = io.BytesIO(self.data)
            stream.headers = {}
            return stream
        self.cache = ImageCache(self.directory.name, opener=opener)

    def tearDown(self):
        self.cache.close()
        self.directory.cleanup()

    def wait_asset(self, identity="BG_TEST", kind="portrait"):
        until = time.monotonic()+3
        while time.monotonic() < until:
            value = self.cache.request(identity, kind)
            if value.image is not None or value.retry_at:
                return value
            time.sleep(.01)
        self.fail("Artwork worker did not deliver")

    def test_dedup_provenance_and_offline_reopen(self):
        for _ in range(20):
            self.cache.request("BG_TEST", "portrait")
        asset = self.wait_asset()
        self.assertIsNotNone(asset.image)
        self.assertEqual(len(self.calls), 1)
        path = self.cache.path("BG_TEST", "portrait")
        provenance = json.loads(path.with_suffix(".img.source.json").read_text())
        self.assertEqual(provenance["source"], self.calls[0])
        offline = ImageCache(self.directory.name, network=False)
        try:
            until = time.monotonic()+2
            value = offline.request("BG_TEST", "portrait")
            while value.image is None and time.monotonic() < until:
                time.sleep(.01)
                value = offline.request("BG_TEST", "portrait")
            self.assertIsNotNone(value.image)
        finally:
            offline.close()

    def test_failure_backoff_and_synthetic_no_network(self):
        def failed(request, timeout):
            self.calls.append(request.full_url)
            raise HTTPError(request.full_url, 404, "missing", {}, None)
        self.cache.opener = failed
        asset = self.wait_asset()
        self.assertIn("not published", asset.message)
        for _ in range(10):
            self.cache.request("BG_TEST", "portrait")
        self.assertEqual(len(self.calls), 1)
        self.assertIn("Synthetic", self.cache.request("DEMO_BEAST", "portrait").message)
        self.assertEqual(len(self.calls), 1)

    def test_current_full_render_fallback_and_golden_provenance(self):
        self.cache.register(Card("BG_GOLD", "Golden", 2, 2, 2, "BEAST", dbf_id=999,
                                 render_dbf_id=123, is_golden=True))
        def opener(request, timeout):
            self.calls.append(request.full_url)
            if request.full_url.startswith("https://art."):
                raise HTTPError(request.full_url, 404, "missing", {}, None)
            stream = io.BytesIO(self.data)
            stream.headers = {"X-Image-Fallback": "no-golden"}
            return stream
        self.cache.opener = opener
        asset = self.wait_asset("BG_GOLD", "full")
        self.assertEqual(self.calls[-1], "https://hsbg.cards/api/v1/cards/123/image?golden=true")
        self.assertIn("normal render shown", asset.message)
        self.assertIn("English", asset.message)
        self.assertIsNotNone(asset.image)

    def test_corrupt_cache_recovers_and_bad_download_is_rejected(self):
        path = self.cache.path("BG_TEST", "portrait")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"broken")
        self.assertIsNotNone(self.wait_asset().image)
        with self.assertRaises((OSError, ValueError)):
            decode_image(b"<html>not an image</html>")
        with self.assertRaises(ValueError):
            decode_image(payload((2049, 2049)))

    def test_oval_mask_keeps_center_and_clears_corners(self):
        result = oval_image(decode_image(self.data))
        self.assertEqual(result.size, (56, 74))
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((28, 37))[3], 255)


@unittest.skipUnless(os.environ.get("TEST_TK_GUI") == "1" and Image is not None, "Needs native Tk and Pillow")
class CardHoverTests(unittest.TestCase):
    def setUp(self):
        from overlay import Overlay
        self.directory = tempfile.TemporaryDirectory()
        self.cache = ImageCache(self.directory.name, network=False)
        for kind, size in (("portrait", (256, 256)), ("full", (256, 384))):
            path = self.cache.path("BG_TEST", kind)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload(size))
        cards = CardsDatabase(self.directory.name)
        cards.add([Card("BG_TEST", "Test minion", 2, 3, 4, "BEAST", "Test ability")])
        self.app = Overlay(cards, demo=True, image_cache=self.cache)
        self.state = BattlegroundsState(active=True, local_player="1", round=3,
            board_stats=[MinionStats("20", "BG_TEST", "", 12500, 17, 17)])
        self.app.publish(self.state)
        self.app._drain()
        pump(self.app.root)
        self.tile = self.app.card_images.find(("portrait", "own", "20"))

    def tearDown(self):
        self.app.close()
        self.directory.cleanup()

    def test_hover_delay_full_image_and_escape_preserves_app(self):
        preview = self.app.card_images.preview
        self.assertIsNotNone(self.tile.photo_image)
        preview.schedule(self.tile)
        self.assertFalse(preview.visible)
        pump(self.app.root, .4)
        self.app.card_images.poll()
        self.assertTrue(preview.visible)
        self.assertIsNotNone(preview.photo_image)
        self.assertIn("12500", preview.stats.cget("text"))
        self.assertIn("base values", preview.note.cget("text"))
        self.app._escape()
        self.assertFalse(preview.visible)
        self.assertFalse(self.app._closed)

    def test_popup_hover_focus_and_rerender_keeps_card(self):
        preview = self.app.card_images.preview
        self.tile.focus_force()
        self.tile.open()
        preview.schedule_hide()
        with patch.object(self.app.root, "winfo_containing", return_value=preview.image):
            preview._maybe_hide()
        self.assertTrue(preview.visible)
        self.state.board_stats = [MinionStats("20", "BG_TEST", "", 12501, 19, 19)]
        self.app.publish(self.state)
        self.app._drain()
        pump(self.app.root, .1)
        self.assertTrue(preview.visible)
        self.assertIn("12501", preview.stats.cget("text"))
        self.assertEqual(self.app.root.focus_get(), self.app.card_images.find(("portrait", "own", "20")))
        self.app.show_view("settings")
        self.assertFalse(preview.visible)

    def test_preview_missing_image_uses_metadata_and_focus_dismisses(self):
        preview = self.app.card_images.preview
        self.tile.card_id = "BG_MISSING"
        self.tile.open()
        pump(self.app.root)
        self.app.card_images.poll()
        self.assertIsNone(preview.photo_image)
        self.assertIn("Test minion", preview.image.cget("text"))
        self.assertIn("Test ability", preview.image.cget("text"))
        self.app.nav_buttons["live"].focus_force()
        with patch.object(self.app.root, "winfo_containing", return_value=self.app.root):
            preview._maybe_hide()
        self.assertFalse(preview.visible)

    def test_hiding_preview_ignores_destroy_time_leave_event(self):
        preview = self.app.card_images.preview
        self.tile.open()
        pump(self.app.root)
        self.assertTrue(preview.visible)
        # A hoverable child can emit <Leave> during Toplevel destruction.
        preview.window.bind("<Destroy>", lambda event: preview.schedule_hide(), add="+")
        preview.hide()
        self.assertIsNone(preview._hide_timer)
        self.app.root.update()
        self.assertIsNone(preview._hide_timer)

    def test_direct_hide_check_cancels_queued_leave_timer(self):
        preview = self.app.card_images.preview
        self.tile.open()
        pump(self.app.root)
        preview.schedule_hide()
        timer = preview._hide_timer
        self.assertIsNotNone(timer)
        with patch.object(self.app.root, "winfo_containing", return_value=self.app.root):
            preview._maybe_hide()
        self.assertIsNone(preview._hide_timer)
        self.assertNotIn(timer, self.app.root.tk.call("after", "info"))
