"""Native AppKit bridge tests use only temporary local state files."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from cards_db import CardsDatabase
from demo import TRAINING_CARDS
from native_feed import NativeStatePublisher
from parser import BattlegroundsState, MinionStats


def minion(identity: str, card_id: str, attack: int, health: int) -> MinionStats:
    return MinionStats(identity, card_id, "", attack, health, health)


class NativeFeedTests(unittest.TestCase):
    def test_native_host_uses_original_game_style_combat_surface(self):
        source = (Path(__file__).resolve().parents[1] / "native_macos" / "OpenBattlegroundsOverlay.m").read_text(encoding="utf-8")
        self.assertIn("@interface CombatOddsView", source)
        self.assertIn("COMBAT ODDS · CURRENT FIGHT", source)
        self.assertIn("MODEL FIDELITY · INCOMPLETE BASELINE", source)
        self.assertIn("OPEN BATTLEGROUNDS", source)

    def test_private_atomic_feed_contains_recruit_and_combat_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_file = root / "native_overlay_state.json"
            cards = CardsDatabase(root)
            cards.add(TRAINING_CARDS)
            publisher = NativeStatePublisher(state_file, root)
            try:
                publisher.publish_cards(cards, "Training cards loaded")
                state = BattlegroundsState(active=True, local_player="1", hero_card_id="DEMO_HERO",
                                           round=6, tavern_tier=3, gold=7, health=28, armor=2,
                                           next_opponent="2", action_costs={"Buy": 3, "Refresh": 1},
                                           board_stats=[minion("own", "DEMO_BEAST", 8, 7)],
                                           opponent_stats={"2": [minion("enemy", "DEMO_GUARD", 3, 6)]},
                                           opponent_heroes={"2": "DEMO_HERO"}, opponent_rounds={"2": 5})
                publisher.publish(state)
                payload = json.loads(state_file.read_text(encoding="utf-8"))
                self.assertEqual((payload["schema"], payload["phase"], payload["round"]), (1, "recruit", 6))
                self.assertEqual(payload["board"][0]["name"], "Training beast")
                self.assertTrue(any("gold available" in line for line in payload["recruit_plan"]))
                self.assertEqual(payload["opponent"]["age"], 1)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    payload = json.loads(state_file.read_text(encoding="utf-8"))
                    if payload["odds"]["state"] == "ready":
                        break
                    time.sleep(.02)
                self.assertEqual(payload["odds"]["state"], "ready")
                self.assertIn("first_attacker", payload["odds"])
                self.assertIn(payload["odds"]["stage"], {"quick", "refined"})
                self.assertTrue(payload["turn_plan"])
                self.assertIn("coverage", payload)
            finally:
                publisher.close()
