"""Native redesign regressions; fixtures use temporary or in-memory data only."""
import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from cards_db import CardsDatabase
from demo import TRAINING_CARDS, setup_lines
from history import HistoryStore
from parser import BattlegroundsParser, MinionStats
from settings import SettingsStore
from ui import DARK, LIGHT


def luminance(color):
    channels = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]
    linear = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels]
    return sum(v*w for v, w in zip(linear, (.2126, .7152, .0722)))


class ThemeTests(unittest.TestCase):
    def test_text_contrast_on_used_surfaces(self):
        for theme in (DARK, LIGHT):
            for foreground in ("text", "secondary", "warning", "accent"):
                for background in ("window", "sidebar", "panel", "raised", "button"):
                    high, low = sorted((luminance(theme[foreground]), luminance(theme[background])), reverse=True)
                    self.assertGreaterEqual((high+.05)/(low+.05), 4.5, (foreground, background, theme))

    def test_corrupt_theme_and_new_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory)/"settings.json")
            store.path.write_text(json.dumps({"theme": [], "topmost": "yes", "ui_version": -2}))
            self.assertEqual(store.load()["theme"], "dark")
            values = store.load()
            values.update(theme="light", topmost=False, reduce_transparency=True, ui_version=2)
            store.save(values)
            self.assertEqual(store.load(), values)


@unittest.skipUnless(os.environ.get("TEST_TK_GUI") == "1", "Set TEST_TK_GUI=1 to test native Tk")
class NativeDesignTests(unittest.TestCase):
    def setUp(self):
        from overlay import Overlay
        self.directory = tempfile.TemporaryDirectory()
        self.cards = CardsDatabase(self.directory.name)
        self.cards.add(TRAINING_CARDS)
        self.history = HistoryStore()
        self.app = Overlay(self.cards, history=self.history, demo=True,
                           settings_path=Path(self.directory.name)/"settings.json")
        parser = BattlegroundsParser(lambda state: None, "1")
        for line in setup_lines():
            parser.consume(line)
        self.state = copy.deepcopy(parser.state)

    def tearDown(self):
        self.app.close()
        self.history.close()
        self.directory.cleanup()

    def publish(self):
        self.history.record(self.state)
        self.app.publish(self.state)
        self.app._drain()
        # Let the real debounced native resize handler settle after deiconifying.
        until = time.monotonic() + .18
        while time.monotonic() < until:
            self.app.root.update()
            time.sleep(.01)

    def test_all_seven_board_rows_precede_disclosures(self):
        self.state.board_stats = [MinionStats(str(i), "DEMO_BEAST", "", i+1, i+2, i+2) for i in range(7)]
        self.publish()
        self.assertEqual(len(self.app.board_names), 7)
        first_disclosure = self.app._live_controls["economy"]
        board_bottom = first_disclosure.winfo_rooty() - self.app.area.canvas.winfo_rooty()
        self.assertLess(board_bottom, self.app.area.canvas.winfo_height(), "Board must fit before scrolling at default size")
        self.assertFalse(self.app.listing.winfo_ismapped(), "Secondary details start collapsed")

    def test_history_filter_correction_and_unknown_provenance(self):
        self.publish()
        self.app.show_view("history")
        self.app.root.update()
        self.assertEqual(len(self.app.history_table.get_children()), 1)
        self.assertIn("Incomplete", self.app.history_table.item(self.state.game_id, "values"))
        self.app.rank_value.set("3")
        self.app.save_rank()
        self.assertEqual(self.history.recent()[0]["placement_source"], "manual")
        self.assertIn("Manual", self.app.history_table.item(self.state.game_id, "values"))
        self.app.history_query.set("missing hero")
        self.assertFalse(self.app.history_table.get_children())
        self.app.history_query.set("training")
        self.assertEqual(len(self.app.history_table.get_children()), 1)
        self.app.rank_value.set("9")
        self.app.save_rank()
        self.assertIn("Could not save", self.app.feedback_value.get())

    def test_reference_filters_only_cached_pool_cards(self):
        self.cards.cache_path.write_text(json.dumps([
            {"id": "BG_TEST", "name": "Reference beast", "type": "MINION", "techLevel": 1,
             "attack": 2, "health": 3, "race": "BEAST", "isBattlegroundsPoolMinion": True},
            {"id": "BG_RETIRED", "name": "Retired", "type": "MINION", "techLevel": 1},
        ]))
        self.cards.load()
        self.app.show_view("reference")
        self.assertIn("Reference beast", self.app.reference_listing.get("1.0", "end"))
        self.assertNotIn("Retired", self.app.reference_listing.get("1.0", "end"))
        self.app.reference_query.set("demon")
        self.assertIn("No matching", self.app.reference_listing.get("1.0", "end"))

    def test_theme_and_compact_restore_navigation_and_geometry(self):
        self.publish()
        self.app.show_view("settings")
        self.app.set_theme("light")
        self.app.root.update()
        self.assertEqual(self.app.root.cget("bg"), LIGHT["window"])
        self.assertEqual(self.app.current_view, "settings")
        self.app.toggle_transparency()
        self.assertEqual(float(self.app.root.wm_attributes("-alpha")), 1)
        previous = (self.app.root.winfo_width(), self.app.root.winfo_height())
        self.app.toggle_compact()
        self.app.root.update()
        self.assertEqual(self.app.root.winfo_height(), 96)
        self.assertIn("DEMO · Synthetic", self.app.compact_summary.cget("text"))
        self.app.toggle_compact()
        self.app.root.update()
        self.assertEqual((self.app.root.winfo_width(), self.app.root.winfo_height()), previous)
        self.app.show_view("live")
        self.assertEqual(self.app.board_names, ["Training beast", "Training guard"])

    def test_small_window_stacks_live_board_first(self):
        self.app.root.geometry("800x580")
        self.app._narrow = True
        self.publish()
        self.assertEqual(self.app._live_controls["economy"].master.grid_info()["column"], 0)
        self.app.show_view("settings")
        self.app.root.update()
        self.assertGreater(self.app.area.canvas.bbox("all")[3], self.app.area.canvas.winfo_height())

    def test_portrait_layout_ignores_destroyed_grid(self):
        self.publish()
        portrait = self.app.card_images.find(("portrait", "own", "20"))
        self.assertIsNotNone(portrait)
        grid = portrait.master
        grid.destroy()
        # A queued Configure may arrive after a live rerender destroys its old grid.
        self.app._layout_portraits(grid, [portrait], 336)

    def test_game_side_overlay_keeps_live_boards_in_a_narrow_rail(self):
        self.publish()
        self.app.toggle_game_overlay()
        self.app.root.update()
        self.assertTrue(self.app.game_overlay)
        self.assertEqual(self.app.current_view, "live")
        self.assertLessEqual(self.app.root.winfo_width(), 330)
        self.assertFalse(self.app.sidebar.winfo_exists())
        self.assertTrue(self.app.game_content.winfo_exists())
        portrait = self.app.card_images.find(("portrait", "game:own", "20"))
        self.assertIsNotNone(portrait)
        self.assertEqual(int(portrait.cget("width")), 46)
        self.assertIn("Win chance", self.app.game_estimate_title.cget("text"))
        self.assertEqual(self.app._game_focus(), "recruit")
        self.app.set_game_preset("combat")
        self.app.root.update()
        self.assertEqual((self.app.game_preset, self.app._game_focus()), ("combat", "combat"))
        self.assertEqual(self.app._preset_label(), "Combat")
        self.app.set_game_preset("minimal")
        self.app.root.update()
        self.assertEqual(self.app._game_focus(), "minimal")
        self.assertEqual(self.app.preferences["game_preset"], "minimal")
        self.app.toggle_game_overlay()
        self.app.root.update()
        self.assertFalse(self.app.game_overlay)
        self.assertTrue(self.app.sidebar.winfo_exists())

    def test_opponent_keyboard_focus_survives_selection_and_publication(self):
        self.state.opponent_heroes = {"2": "DEMO_HERO"}
        self.publish()
        self.app._opponent_controls["2"].focus_force()
        self.app._opponent_controls["2"].invoke()
        self.app.root.update()
        self.assertEqual(self.app.root.focus_get(), self.app._opponent_controls["2"])
        self.publish()
        self.assertEqual(self.app.root.focus_get(), self.app._opponent_controls["2"])
