"""Regression coverage for actual log-following failures and Tk integration."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cards_db import CardsDatabase
from parser import BattlegroundsParser, PowerLogTailer
from config import HearthstonePaths, discover_installation, discover_windows_installation, ensure_client_logging


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Background reader did not deliver expected state")


class TailerTests(unittest.TestCase):
    def test_replay_append_partial_utf8_truncate_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Power.log"
            path.write_bytes(b"existing\n")
            lines, resets = [], []
            reader = PowerLogTailer(path, lines.append, .01, on_reset=lambda: resets.append(1))
            reader.start()
            try:
                wait_for(lambda: lines == ["existing"])
                with path.open("ab") as stream:
                    stream.write(b"caf\xc3")
                time.sleep(.04)
                self.assertEqual(lines, ["existing"])
                with path.open("ab") as stream:
                    stream.write(b"\xa9\nappended\n")
                wait_for(lambda: len(lines) == 3)
                self.assertEqual(lines, ["existing", "café", "appended"])
                path.write_bytes(b"new\n")
                wait_for(lambda: lines[-1] == "new")
                replacement = Path(directory) / "replacement.log"
                replacement.write_bytes(b"replacement\n")
                replacement.replace(path)
                wait_for(lambda: lines[-1] == "replacement")
                self.assertEqual(len(resets), 3)
            finally:
                reader.stop()
            self.assertFalse(reader._thread.is_alive())

    def test_missing_file_new_session_and_rapid_regrowth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Logs"
            lines, statuses = [], []
            reader = PowerLogTailer(root, lines.append, .01, on_status=statuses.append)
            reader.start()
            try:
                wait_for(lambda: any("Waiting" in status for status in statuses))
                first = root / "session1" / "Power.log"
                first.parent.mkdir(parents=True)
                first.write_bytes(b"first\n")
                wait_for(lambda: lines == ["first"])
                first.write_bytes(b"rewritten and longer than the old log\n")
                wait_for(lambda: lines[-1].startswith("rewritten"))
                second = root / "session2" / "Power.log"
                second.parent.mkdir()
                second.write_bytes(b"session two\n")
                wait_for(lambda: lines[-1] == "session two")
            finally:
                reader.stop()

    def test_permission_error_is_visible_and_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Power.log"
            path.write_bytes(b"recovered\n")
            lines, statuses = [], []
            reader = PowerLogTailer(path, lines.append, .01, on_status=statuses.append)
            with patch.object(reader, "_resolve", side_effect=[PermissionError(), path, path, path]):
                reader.start()
                try:
                    wait_for(lambda: lines == ["recovered"])
                finally:
                    reader.stop()
            self.assertTrue(any("access denied" in status for status in statuses))


class ParserTests(unittest.TestCase):
    def test_auto_player_live_stats_shop_round_and_stale_inline_zone(self):
        parser = BattlegroundsParser(lambda state: None)
        lines = [
            "CREATE_GAME", "GameEntity EntityID=7", "tag=CARDTYPE value=GAME",
            "tag=BACON_BARTENDER_CARD_ID value=57110",
            "Player EntityID=8 PlayerID=3", "tag=CARDTYPE value=PLAYER",
            "tag=HERO_ENTITY value=29", "tag=PLAYER_TECH_LEVEL value=4",
            "tag=RESOURCES value=9", "tag=RESOURCES_USED value=2", "tag=TURN value=7",
            "Player EntityID=9 PlayerID=11", "tag=CARDTYPE value=PLAYER", "tag=BACON_DUMMY_PLAYER value=1",
            "FULL_ENTITY - Creating ID=29 CardID=TB_BaconShop_HERO_91",
            "tag=CARDTYPE value=HERO", "tag=CONTROLLER value=3", "tag=ZONE value=PLAY",
            "tag=HEALTH value=30", "tag=DAMAGE value=4", "tag=ARMOR value=7",
            "FULL_ENTITY - Creating ID=40 CardID=", "tag=CARDTYPE value=MINION",
            "tag=CONTROLLER value=3", "tag=ZONE value=PLAY", "tag=ATK value=99", "tag=HEALTH value=42",
            "SHOW_ENTITY - Updating Entity=40 CardID=BG20_100", "tag=CARDTYPE value=MINION",
            "tag=DAMAGE value=5", "tag=DIVINE_SHIELD value=1",
            "FULL_ENTITY - Creating ID=50 CardID=BG20_100", "tag=CARDTYPE value=MINION",
            "tag=CONTROLLER value=11", "tag=ZONE value=PLAY", "tag=ATK value=2", "tag=HEALTH value=1",
            "TAG_CHANGE Entity=GameEntity tag=TURN value=13",
            "TAG_CHANGE Entity=Bartender Bob tag=TURN value=6",
        ]
        for line in lines:
            parser.consume(line)
        state = parser.state
        self.assertEqual(state.local_player, "3")
        self.assertEqual((state.turn, state.round, state.tavern_tier, state.health, state.armor, state.gold),
                         (13, 7, 4, 26, 7, 7))
        self.assertEqual((state.board_attack, state.board_health), (99, 37))
        self.assertEqual([card.entity_id for card in state.board_stats], ["40"])
        self.assertEqual([card.entity_id for card in state.shop_stats], ["50"])
        self.assertIn("DIVINE_SHIELD", state.board_stats[0].keywords)
        parser.consume("TAG_CHANGE Entity=40 tag=ZONE value=GRAVEYARD")
        parser.consume("TAG_CHANGE Entity=[entityName=Old minion id=40 zone=PLAY cardId=BG20_100 player=3] tag=ATK value=0")
        self.assertFalse(parser.state.board_stats)  # Inline zone is a stale description.

    def test_duplicate_sources_do_not_reset_metadata_or_reveal_history(self):
        parser = BattlegroundsParser(lambda state: None)
        for line in ["CREATE_GAME", "Player EntityID=8 PlayerID=3", "tag=CARDTYPE value=PLAYER"]:
            parser.consume("D 00:00:00 GameState.DebugPrintPower() - " + line)
        parser.consume("D 00:00:00 GameState.DebugPrintGame() - PlayerID=3, PlayerName=TrackerUser")
        parser.consume("D 00:00:00 PowerTaskList.DebugPrintPower() - CREATE_GAME")
        parser.consume("D 00:00:00 GameState.DebugPrintEntityChoices() - id=1 Player=TrackerUser TaskList=7 ChoiceType=MULLIGAN CountMin=1 CountMax=1")
        self.assertEqual(parser.state.local_player, "3")
        parser.consume("Truncating log, which has reached the size limit of 10000KB")
        self.assertTrue(parser.state.log_capped)

    def test_real_headers_continuation_tags_and_combat_history(self):
        snapshots = []
        parser = BattlegroundsParser(snapshots.append, local_player="1")
        lines = [
            "CREATE_GAME", "GameEntity EntityID=1", "tag=TURN value=7",
            "GameType=GT_BATTLEGROUNDS", "FULL_ENTITY - Creating ID=10 CardID=BG20_HERO_100",
            "tag=CARDTYPE value=HERO", "tag=CONTROLLER value=1", "tag=ZONE value=PLAY",
            "tag=HEALTH value=30", "tag=DAMAGE value=4", "tag=ARMOR value=5",
            "tag=PLAYER_TECH_LEVEL value=3",
            "SHOW_ENTITY - Updating Entity=[name=Example id=20 zone=PLAY player=2] CardID=BG20_100",
            "tag=CARDTYPE value=MINION", "tag=CONTROLLER value=2", "tag=ZONE value=PLAY",
            "tag=HEALTH value=2", "tag=ARMOR value=99",
            "TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_COMBAT",
            "BLOCK_START BlockType=ATTACK Entity=20", "BLOCK_END", "BLOCK_END",
            "TAG_CHANGE Entity=20 tag=ZONE value=GRAVEYARD",
        ]
        for line in lines:
            parser.consume("D 12:00:00 PowerTaskList.DebugPrintPower() - " + line)
        self.assertTrue(parser.state.in_combat)
        self.assertEqual((parser.state.turn, parser.state.health, parser.state.armor,
                          parser.state.tavern_tier), (7, 26, 5, 3))
        self.assertEqual(parser.state.opponent_boards, {"2": ["BG20_100"]})
        parser.consume("TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_ACTION")
        self.assertFalse(parser.state.in_combat)
        self.assertTrue(snapshots[-2].in_combat)  # Published state is immutable to later updates.
        parser.consume("CREATE_GAME")
        self.assertFalse(parser.state.opponent_boards)
        self.assertEqual(parser.state.turn, 0)


@unittest.skipUnless(os.environ.get("TEST_TK_GUI") == "1", "Set TEST_TK_GUI=1 to test native Tk")
class OverlayTests(unittest.TestCase):
    def test_colors_borderless_and_background_publication(self):
        from overlay import Overlay
        overlay = Overlay(CardsDatabase())
        try:
            self.assertTrue(overlay.root.overrideredirect())
            colors = set(overlay.ui.colors.values())
            def check(widget):
                options = widget.keys()
                if "foreground" in options:
                    self.assertIn(widget.cget("foreground"), colors)
                if "background" in options:
                    self.assertIn(widget.cget("background"), colors)
                for child in widget.winfo_children():
                    check(child)
            check(overlay.root)
            self.assertIn("Waiting", overlay.meta.cget("text"))
            parser = BattlegroundsParser(overlay.publish)
            parser.consume("GameType=GT_BATTLEGROUNDS")
            parser.consume("TAG_CHANGE Entity=GameEntity tag=TURN value=8")
            overlay._drain()
            self.assertIn("Turn 8", overlay.meta.cget("text"))
            self.assertEqual(set(overlay.nav_buttons), {"live", "history", "reference", "coach", "settings"})
            self.assertEqual(overlay.board_names, [])
        finally:
            overlay.close()


class ConfigurationTests(unittest.TestCase):
    def test_find_custom_installation_and_preserve_client_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            installation = Path(directory) / "Hearthstone"
            (installation / "Hearthstone.app").mkdir(parents=True)
            from types import SimpleNamespace
            result = SimpleNamespace(stdout=str(installation / "Hearthstone.app") + "\n")
            with patch("config.subprocess.run", return_value=result):
                self.assertEqual(discover_installation(), installation)
            config = installation / "client.config"
            original = "[Other]\nKeep=True\n[Log]\nFileSizeLimit.Int=10000\n[Last]\nKeep=Yes\n"
            config.write_text(original)
            ensure_client_logging(installation)
            self.assertEqual(config.read_text(), original.replace("=10000", "=-1"))
            self.assertEqual(config.with_name("client.config.tracker-backup").read_text(), original)
            self.assertIn("already enabled", ensure_client_logging(installation))

    def test_windows_log_roots_and_portable_package_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "LocalAppData"
            installation = root / "Program Files (x86)" / "Hearthstone"
            (installation / "Logs").mkdir(parents=True)
            (installation / "Hearthstone.exe").touch()
            (installation / "Logs" / "Power.log").write_text("installed")
            (profile / "Blizzard" / "Hearthstone" / "Logs").mkdir(parents=True)
            (profile / "Blizzard" / "Hearthstone" / "Logs" / "Power.log").write_text("profile")
            self.assertEqual(discover_windows_installation([root / "Program Files (x86)"]), installation)
            paths = HearthstonePaths.windows(profile, installation)
            self.assertEqual(paths.log_config, profile / "Blizzard" / "Hearthstone" / "log.config")
            self.assertIn(paths.logs_dir, {profile / "Blizzard" / "Hearthstone" / "Logs", installation / "Logs"})
        project = Path(__file__).resolve().parents[1]
        self.assertTrue((project / "assets" / "OpenBattlegroundsOverlay.ico").is_file())
        script = (project / "windows" / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("--windowed", script)
        self.assertIn("OpenBattlegroundsOverlay.ico", script)
