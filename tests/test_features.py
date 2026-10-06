"""Offline feature tests; no user logs, game config, or persistent data touched."""
from __future__ import annotations
import copy
import json
import os
import random
import tempfile
import time
import unittest
from pathlib import Path
from advisor import compare_shop, economy_notes, recruit_plan, threat_summary
from cards_db import Card, CardsDatabase
from combat import (CombatReport, CombatWorker, Unit, _after_attack, _apply_start_of_combat, _before_attack,
                    _hit, _resolve_deaths, coverage, fight, simulate)
from demo import TRAINING_CARDS, setup_lines
from history import HistoryStore
from insights import browser_cards, card_support, combat_reasons, coverage_inspector, positioning_analysis, turn_plan
from parser import BattlegroundsParser, BattlegroundsState, Entity, MinionStats
from settings import SettingsStore


def minion(identity="1", attack=6, health=5, card="DEMO_BEAST", keywords=(), effects=()):
    return MinionStats(identity, card, "", attack, health, health, keywords, effects)


def database():
    db = CardsDatabase()
    db.add(TRAINING_CARDS)
    return db


class FeatureParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = BattlegroundsParser(lambda state: None, "1")
        for line in setup_lines():
            self.parser.consume(line)

    def test_actual_costs_and_unknown_cost(self):
        self.assertEqual(self.parser.state.action_costs, {"Upgrade": 5, "Refresh": 1, "Buy": 3})
        self.parser.consume("TAG_CHANGE Entity=50 tag=COST value=4")
        self.assertEqual(self.parser.state.action_costs["Upgrade"], 4)
        self.parser.consume("TAG_CHANGE Entity=50 tag=ZONE value=SETASIDE")
        self.assertNotIn("Upgrade", self.parser.state.action_costs)

    def test_pre_attack_snapshot_and_hero_metadata(self):
        self.parser.consume("TAG_CHANGE Entity=GameEntity tag=TURN value=6")
        self.assertFalse(self.parser.state.opponent_stats)
        self.parser.consume("BLOCK_START BlockType=ATTACK Entity=20")
        state = self.parser.state
        self.assertEqual(state.opponent_heroes, {"2": "DEMO_HERO"})
        self.assertEqual(state.opponent_tiers, {"2": 2})
        self.assertEqual(state.opponent_rounds, {"2": 3})
        self.assertEqual([m.health for m in state.combat_board], [5, 6])
        self.assertEqual(len(state.opponent_stats["2"]), 2)  # First encounter is available before an attack resolves.
        self.parser.consume("TAG_CHANGE Entity=20 tag=DAMAGE value=4")
        self.parser.consume("TAG_CHANGE Entity=30 tag=ZONE value=GRAVEYARD")
        self.assertEqual(state.combat_board[0].health, 5)
        self.assertEqual(len(state.opponent_stats["2"]), 2)

    def test_transient_cant_attack_is_not_a_next_combat_effect(self):
        entity = Entity("20", "DEMO_BEAST", tags={"ATK": "4", "HEALTH": "5", "CANT_ATTACK": "1",
                                                     "TAG_SCRIPT_DATA_NUM_1": "4", "TAG_SCRIPT_DATA_NUM_2": "3"})
        stats = self.parser._stats(entity)
        self.assertNotIn("CANT_ATTACK", stats.effects)
        self.assertEqual(dict(stats.script_data), {"TAG_SCRIPT_DATA_NUM_1": 4, "TAG_SCRIPT_DATA_NUM_2": 3})

    def test_placement_only_final_and_stable_replay_id(self):
        self.parser.consume("TAG_CHANGE Entity=8 tag=PLAYER_LEADERBOARD_PLACE value=4")
        self.assertIsNone(self.parser.state.placement)
        self.parser.consume("TAG_CHANGE Entity=8 tag=PLAYSTATE value=LOST")
        self.assertEqual(self.parser.state.placement, 4)
        ids = []
        for _ in range(2):
            parser = BattlegroundsParser(lambda state: None)
            parser.begin_stream(Path("example/Power.log"))
            parser.consume("D 01:00 GameState.DebugPrintPower() - CREATE_GAME")
            ids.append(parser.state.game_id)
        self.assertEqual(ids[0], ids[1])
        parser.consume("D 01:00 GameState.DebugPrintPower() - CREATE_GAME")
        self.assertNotEqual(ids[0], parser.state.game_id)


class AdviceTests(unittest.TestCase):
    def test_tribe_synergy_keyword_and_explanation(self):
        state = BattlegroundsState(board_stats=[minion()], shop_stats=[minion("2", 3, 6, "DEMO_GUARD", ("TAUNT",))])
        suggestion = compare_shop(state, database())[0]
        self.assertEqual(suggestion.score, 12)  # A+H +2 shared tribe +1 taunt
        self.assertTrue(any("Shares a tribe" in r for r in suggestion.reasons))
        self.assertEqual(suggestion.text, "Taunt")

    def test_dual_tribes_count_each_board_minion_once(self):
        db = database()
        db.add([Card("DUAL", "Dual", 2, 2, 2, "BEAST / DEMON", races=("BEAST", "DEMON"))])
        state = BattlegroundsState(board_stats=[minion(card="DUAL")], shop_stats=[minion("2", 2, 2, "DUAL")])
        suggestion = compare_shop(state, db)[0]
        self.assertEqual(suggestion.score, 6)
        self.assertTrue(any("with 1 board minions" in r for r in suggestion.reasons))

    def test_no_guessed_economy_and_combat_pause(self):
        state = BattlegroundsState(gold=4, action_costs={"Upgrade": 5, "Buy": 3, "Refresh": 1})
        text = "\n".join(economy_notes(state))
        self.assertIn("need 1 more gold", text)
        self.assertIn("Budget for up to 1 buys", text)
        self.assertIn("Buy → Refresh: affordable", text)
        state.in_combat = True
        self.assertEqual(economy_notes(state), ["Combat: spending reminders paused."])
        self.assertIn("unknown", economy_notes(BattlegroundsState())[0])

    def test_recruit_plan_replacement_and_observed_threat_summary(self):
        db = database()
        state = BattlegroundsState(gold=6, action_costs={"Buy": 3, "Refresh": 1},
                                   board_stats=[minion(str(index), index + 1, index + 1) for index in range(7)],
                                   shop_stats=[minion("shop", 9, 9, "DEMO_GUARD", ("TAUNT",))])
        text = "\n".join(recruit_plan(state, db))
        self.assertIn("Heuristic shop lead", text)
        self.assertIn("Compare with", text)
        threat = threat_summary([minion("enemy", 25, 31, "DEMO_GUARD", ("TAUNT", "DIVINE_SHIELD"))], db)
        self.assertEqual((threat.total_attack, threat.total_health), (25, 31))
        self.assertTrue(any("High-attack" in signal for signal in threat.signals))
        self.assertTrue(any("Divine Shield" in signal for signal in threat.signals))


class DecisionSupportTests(unittest.TestCase):
    def test_turn_plan_reasons_and_card_browser_are_local_and_explainable(self):
        db = database()
        state = BattlegroundsState(gold=6, action_costs={"Buy": 3, "Upgrade": 5, "Refresh": 1},
                                   board_stats=[minion()], next_opponent="2",
                                   opponent_stats={"2": [minion("enemy", 24, 8)]})
        plan = "\n".join(turn_plan(state, db))
        self.assertIn("Buy → Refresh", plan)
        self.assertIn("Risk context", plan)
        cards = browser_cards(db, tribe="BEAST")
        self.assertTrue(cards)
        self.assertTrue(all("BEAST" in card.minion_type for card in cards))
        self.assertIn(card_support(cards[0]), {"Generic rules", "Baseline only"})

    def test_coverage_reasons_and_positioning_sandbox_disclose_limits(self):
        db = database()
        db.add([Card("TRIGGER", "Trigger", 1, 2, 2, "BEAST", "Whenever a minion dies, gain +1/+1.")])
        inspected = coverage_inspector([minion(card="TRIGGER")], db)
        self.assertIn("text", inspected)
        report = CombatReport("key", "baseline", trials=20, win=.6, loss=.3, tie=.1, baseline=True,
                              blockers=("Trigger: card text has unimplemented effects",))
        reasons = combat_reasons([minion()], [minion("2")], report, db)
        self.assertTrue(any("Incomplete baseline" in reason for reason in reasons))
        analysis = positioning_analysis([minion("a", 7, 6), minion("b", 1, 20)],
                                        [minion("enemy", 6, 6)], db, (2, 2), trials=20)
        self.assertIsNotNone(analysis)
        self.assertGreaterEqual(len(analysis.options), 2)
        self.assertIn("local", analysis.note)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.history = HistoryStore()
        self.state = BattlegroundsState(active=True, local_player="1", hero_card_id="DEMO_HERO",
                                       game_id="game1", round=1, board_stats=[minion()])

    def tearDown(self):
        self.history.close()

    def test_round_progression_idempotence_and_missing_placement(self):
        self.history.record(self.state)
        self.history.record(self.state)
        self.state.round = 2
        self.history.record(self.state)
        self.assertEqual(len(self.history.recent()), 1)
        self.assertEqual(len(self.history.detail("game1")), 2)
        self.assertEqual(self.history.by_hero()[0]["ranked"], 0)
        self.assertIsNone(self.history.by_hero()[0]["average"])
        self.state.result, self.state.active, self.state.placement = "LOST", False, 3
        self.history.record(self.state)
        self.assertEqual(self.history.by_hero()[0]["average"], 3)
        self.assertEqual(self.history.by_hero()[0]["top4"], 1)

    def test_manual_override_retains_provenance_on_replay(self):
        self.history.record(self.state)
        self.history.set_placement("game1", 2)
        self.state.placement, self.state.result = 4, "LOST"
        self.history.record(self.state)
        row = self.history.recent()[0]
        self.assertEqual((row["placement"], row["placement_source"]), (2, "manual"))
        with self.assertRaises(ValueError):
            self.history.set_placement("game1", 9)
        self.assertEqual(self.history.export()["matches"][0]["rounds"][0]["board"][0]["attack"], 6)

    def test_combat_snapshot_survives_deaths(self):
        self.state.in_combat, self.state.combat_round = True, 1
        self.state.combat_board, self.state.board_stats = [minion()], []
        self.history.record(self.state)
        self.assertEqual(self.history.detail("game1")[0]["board"][0]["health"], 5)

    def test_timeline_and_review_only_summarize_recorded_snapshots(self):
        self.history.record(self.state)
        self.state.round = 2
        self.state.tavern_tier, self.state.gold = 3, 4
        self.state.board_stats = [minion("2", 10, 8, "DEMO_GUARD")]
        self.history.record(self.state)
        timeline = self.history.timeline("game1")
        self.assertEqual([item["round"] for item in timeline], [1, 2])
        self.assertEqual(timeline[-1]["attack_change"], 4)
        self.assertIn("DEMO_GUARD", timeline[-1]["added"])
        review = self.history.review("game1")
        self.assertEqual((review["observed_rounds"], review["highest_tier"]), (2, 3))
        self.assertEqual(review["peak"]["round"], 2)

    def test_opponent_timeline_and_anonymous_summary_exclude_identity(self):
        self.state.opponent_stats, self.state.opponent_rounds = {"2": [minion("enemy", 3, 4)]}, {"2": 1}
        self.history.record(self.state)
        self.state.round, self.state.opponent_stats = 2, {"2": [minion("enemy", 8, 4, "DEMO_GUARD")]}
        self.history.record(self.state)
        timeline = self.history.opponent_timeline("game1", "2")
        self.assertEqual([item["round"] for item in timeline], [1, 2])
        summary = self.history.community_summary()
        self.assertEqual(summary["kind"], "open-battlegrounds-anonymous-summary")
        self.assertNotIn("game1", json.dumps(summary))
        self.assertNotIn("tracked_at", json.dumps(summary))

    def test_persistent_database_reopens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.sqlite3"
            first = HistoryStore(path)
            first.record(self.state)
            first.close()
            second = HistoryStore(path)
            try:
                self.assertEqual(second.recent()[0]["id"], "game1")
            finally:
                second.close()

    def test_calibration_only_uses_logged_combat_outcomes(self):
        self.state.in_combat, self.state.combat_round, self.state.combat_opponent = True, 1, "2"
        self.state.opponent_rounds = {"2": 1}
        report = CombatReport("prediction", "board-only", trials=800, win=.6, loss=.3, tie=.1, confidence="High")
        self.history.record_prediction(self.state, report)
        self.assertEqual(self.history.calibration()["samples"], 0)
        self.state.combat_outcome, self.state.combat_outcome_round = "win", 1
        self.history.record(self.state)
        calibration = self.history.calibration()
        self.assertEqual(calibration["samples"], 1)
        self.assertEqual((calibration["predicted"], calibration["actual"]), (.65, 1.))


class CombatTests(unittest.TestCase):
    def test_deterministic_win_damage_and_inputs_unchanged(self):
        friendly, enemy = [minion(attack=10, health=10)], [minion("2", 1, 1)]
        original = copy.deepcopy(friendly)
        result = simulate(friendly, enemy, database(), (3, 2), trials=100, seed=1, board_only=True)
        self.assertEqual((result.win, result.loss, result.tie, result.dealt), (1, 0, 0, (5, 5)))
        self.assertEqual(friendly, original)

    def test_simultaneous_damage_tie_and_zero_attack_stalemate(self):
        result = simulate([minion(attack=1, health=1)], [minion("2", 1, 1)], database(), trials=30, board_only=True)
        self.assertEqual(result.tie, 1)
        result = simulate([minion(attack=0)], [minion("2", 0)], database(), trials=30, board_only=True)
        self.assertEqual(result.tie, 1)

    def test_shield_does_not_take_zero_damage_or_consume_venomous(self):
        target = Unit(0, 1, 5, {"DIVINE_SHIELD"}, 1)
        self.assertFalse(_hit(target, 0, True))
        self.assertIn("DIVINE_SHIELD", target.keywords)
        self.assertFalse(_hit(target, 1, True))
        self.assertEqual(target.health, 5)
        self.assertTrue(_hit(target, 1, True))
        self.assertEqual(target.health, 0)
        attacker = Unit(0, 1, 10, {"VENOMOUS"}, 1)
        defender = Unit(0, 0, 20, {"DIVINE_SHIELD"}, 1)
        outcome, survivors = fight([[attacker], [defender]], random.Random(1))
        self.assertEqual(outcome, 1)
        self.assertEqual(survivors[0].health, 10)

    def test_windfury_taunt_and_first_attacker_count(self):
        # Two enemy minions means they start; 0 attack taunt is then targeted.
        initial = [[Unit(0, 3, 20, {"WINDFURY"}, 2)],
                   [Unit(0, 0, 3, {"TAUNT"}, 1), Unit(1, 1, 3, set(), 1)]]
        outcome, survivors = fight(initial, random.Random(1))
        self.assertEqual(outcome, 1)
        self.assertEqual(len(survivors), 1)

    def test_unknown_text_effects_and_missing_context_block_odds(self):
        db = database()
        for m in (minion(card="MISSING"), minion(effects=("DEATHRATTLE",)), minion(health=None)):
            result = simulate([m], [minion("2")], db, trials=10, board_only=True)
            self.assertEqual(result.trials, 0)
            self.assertTrue(result.blockers)
        db.add([Card("TRIGGER", "Trigger", 1, 2, 2, "BEAST", "Whenever a minion dies, gain +1/+1.")])
        self.assertTrue(coverage([minion(card="TRIGGER")], db))
        self.assertTrue(simulate([minion()], [minion("2")], db).blockers)

    def test_explicit_baseline_can_exclude_unsupported_effects(self):
        db = database()
        db.add([Card("TRIGGER", "Trigger", 1, 2, 2, "BEAST", "Whenever a minion dies, gain +1/+1.")])
        strict = simulate([minion(card="TRIGGER")], [minion("2")], db, trials=20, seed=1, board_only=True)
        self.assertEqual(strict.trials, 0)
        baseline = simulate([minion(card="TRIGGER")], [minion("2")], db, trials=20, seed=1,
                            board_only=True, allow_baseline=True)
        self.assertEqual((baseline.trials, baseline.baseline), (20, True))
        self.assertTrue(baseline.blockers)
        self.assertIn("Incomplete baseline", baseline.message)

    def test_reborn_and_modelled_current_combat_cards(self):
        db = database()
        db.add([
            Card("BG26_963", "Electric Synthesizer", 2, 3, 4, "DRAGON", "Battlecry and Start of Combat", ("BATTLECRY",), races=("DRAGON",)),
            Card("BG36_245", "Runic Arcanist", 4, 2, 4, "DRAGON", "Start of Combat: Cast Shiny Ring twice.", ("START_OF_COMBAT",), races=("DRAGON",)),
            Card("BG29_816", "Roaring Recruiter", 3, 2, 8, "DRAGON", "Whenever another friendly Dragon attacks, give it +3/+1.", races=("DRAGON",)),
            Card("BG28_309", "Mummifier", 3, 5, 2, "UNDEAD", "Deathrattle: Give a different friendly Undead Reborn.", ("DEATHRATTLE",), races=("UNDEAD",)),
            Card("BG36_354", "Decoy Conjurer", 2, 3, 4, "Neutral", "Activate (2): Steal the highest-Attack minion in the Tavern."),
            Card("BG36_243_G", "Sky-hatch Runaway", 4, 10, 14, "DRAGON", "Activate (1): Trigger a friendly minion's Rally twice.", races=("DRAGON",)),
            Card("BG36_511", "Dead Bellringer", 4, 3, 6, "UNDEAD", "Activate (1): Give a different friendly Undead Reborn. Then destroy it to gain +4/+4.", races=("UNDEAD",)),
            Card("BG32_324", "Drustfallen Butcher", 5, 2, 7, "UNDEAD", "Avenge (3): Get a Butchering.", ("AVENGE",), races=("UNDEAD",)),
            Card("BG36_364", "Hopebringer", 5, 3, 3, "DRAGON", "Start of Combat: Give your minions +3/+3.", ("START_OF_COMBAT",), races=("DRAGON",)),
            Card("BG25_008", "Eternal Knight", 2, 4, 2, "UNDEAD", "Has +4/+2 for each friendly Eternal Knight that died this game.", ("AURA", "InvisibleDeathrattle"), races=("UNDEAD",)),
        ])
        board = [minion("1", 3, 4, "BG26_963"), minion("2", 2, 4, "BG36_245"),
                 minion("3", 2, 8, "BG29_816"), minion("4", 5, 2, "BG28_309"),
                 minion("5", 3, 4, "BG36_354"), minion("6", 1, 1, "DEMO_BEAST", ("REBORN",))]
        self.assertFalse(coverage(board, db))
        report = simulate(board, [minion("enemy", 1, 1)], db, trials=20, seed=3, board_only=True)
        self.assertEqual(report.trials, 20)
        self.assertIn("Electric Synthesizer Start of Combat Dragon buffs", report.modelled)
        self.assertIn("Friendly board attacks first", report.first_attacker)
        live_snapshot = [minion("sky", 10, 14, "BG36_243_G"), minion("mum", 5, 2, "BG28_309", effects=("DEATHRATTLE",)), minion("bell", 3, 6, "BG36_511"),
                         minion("butcher", 2, 7, "BG32_324"),
                         MinionStats("hope", "BG36_364", "", 4, 3, 3, (), (), (("TAG_SCRIPT_DATA_NUM_1", 4), ("TAG_SCRIPT_DATA_NUM_2", 3))),
                         minion("knight", 12, 6, "BG25_008", effects=("AURA",))]
        self.assertFalse(coverage(live_snapshot, db))

    def test_modelled_effect_resolution(self):
        electric = Unit(0, 3, 4, set(), 2, "BG26_963", {"DRAGON"})
        dragon = Unit(1, 1, 10, set(), 2, "DEMO_DRAGON", {"DRAGON"})
        runic = Unit(0, 2, 4, set(), 4, "BG36_245", {"DRAGON"})
        _apply_start_of_combat([[electric, dragon], [runic]])
        self.assertEqual((dragon.attack, dragon.health), (2, 11))
        self.assertEqual((runic.attack, runic.health), (4, 6))
        recruiter = Unit(0, 2, 8, set(), 3, "BG29_816", {"DRAGON"})
        attacker = Unit(1, 1, 9, set(), 2, "DEMO_DRAGON", {"DRAGON"})
        _before_attack([recruiter, attacker], attacker)
        self.assertEqual((attacker.attack, attacker.health), (4, 10))
        mummifier = Unit(0, 5, 0, set(), 3, "BG28_309", {"UNDEAD"})
        target = Unit(1, 2, 3, set(), 2, "DEMO_UNDEAD", {"UNDEAD"})
        resolved = _resolve_deaths([[mummifier, target], []], random.Random(1))
        self.assertTrue(resolved[0][0].reborn)
        resolved[0][0].health = 0
        reborn = _resolve_deaths(resolved, random.Random(1))[0]
        self.assertEqual((len(reborn), reborn[0].health, reborn[0].reborn), (1, 1, False))
        hope = Unit(0, 4, 3, set(), 5, "BG36_364", {"DRAGON"}, script_data={"TAG_SCRIPT_DATA_NUM_1": 4, "TAG_SCRIPT_DATA_NUM_2": 3})
        target = Unit(1, 1, 2, set(), 2, "DEMO_DRAGON", {"DRAGON"})
        _apply_start_of_combat([[hope, target], []])
        self.assertEqual((target.attack, target.health), (5, 5))
        fallen_knight = Unit(0, 0, 0, set(), 2, "BG25_008", {"UNDEAD"})
        living_knight = Unit(1, 8, 4, set(), 2, "BG25_008", {"UNDEAD"})
        eternal = _resolve_deaths([[fallen_knight, living_knight], []], random.Random(1))[0]
        self.assertEqual((eternal[0].attack, eternal[0].health), (12, 6))

    def test_logged_blood_gem_rally_effects(self):
        bonker = Unit(0, 2, 7, {"WINDFURY"}, 4, "BG20_104", {"QUILBOAR"})
        ally = Unit(1, 1, 5, set(), 2, "DEMO_BEAST", {"QUILBOAR"})
        gems = [3, 4]
        _after_attack([bonker, ally], bonker, gems)
        self.assertEqual((ally.attack, ally.health), (4, 9))
        vine = Unit(0, 4, 4, set(), 5, "BG33_883", {"QUILBOAR"},
                    script_data={"TAG_SCRIPT_DATA_NUM_1": 4})
        _after_attack([vine], vine, gems)
        self.assertEqual((vine.attack, vine.health), (16, 20))
        refiner = Unit(0, 3, 8, set(), 5, "BG33_885", {"QUILBOAR"},
                       script_data={"TAG_SCRIPT_DATA_NUM_1": 1, "TAG_SCRIPT_DATA_NUM_2": 2})
        _after_attack([refiner], refiner, gems)
        self.assertEqual(gems, [4, 6])

    def test_cleave_position_and_fixed_deathrattle_summons(self):
        cleaver = Unit(0, 4, 12, set(), 3, effects={"CLEAVE"})
        enemies = [Unit(0, 0, 3, set(), 1), Unit(1, 0, 3, set(), 1), Unit(2, 0, 3, set(), 1)]
        outcome, survivors = fight([[cleaver], enemies], random.Random(1))
        self.assertEqual((outcome, len(survivors)), (1, 1))
        bonehead = Unit(0, 1, 0, set(), 1, "BG28_300", {"UNDEAD"})
        tokens = _resolve_deaths([[bonehead], []], random.Random(1))[0]
        self.assertEqual([(token.attack, token.health) for token in tokens], [(1, 1), (1, 1)])

    def test_adaptive_interval_confidence_and_stale_sensitivity(self):
        result = simulate([minion(attack=6, health=6)], [minion("2", 6, 6)], database(), (2, 2),
                          seed=9, board_only=True, opponent_age=2)
        self.assertGreaterEqual(result.trials, 800)
        self.assertLessEqual(result.trials, 6000)
        self.assertEqual(result.confidence, "Low")
        self.assertIsNotNone(result.interval)
        self.assertIsNotNone(result.scenario)
        self.assertIn("Sensitivity only", result.scenario_detail)

    def test_tarecgosa_uses_observed_stats_without_presentation_blockers(self):
        db = database()
        db.add([Card("BG21_015_G", "Tarecgosa", 2, 4, 4, "DRAGON",
                     "This permanently keeps Bonus Keywords and stats gained in combat.",
                     mechanics=("TRIGGER_VISUAL",))])
        tarecgosa = minion(card="BG21_015_G", attack=19, health=27, effects=("CANT_ATTACK",))
        self.assertFalse(coverage([tarecgosa], db))
        result = simulate([tarecgosa], [minion("2")], db, trials=30, seed=2, board_only=True)
        self.assertEqual(result.trials, 30)

    def test_unknown_tiers_hide_damage_not_probability(self):
        result = simulate([minion(attack=10, health=10)], [minion("2", 1, 1)], database(), trials=30, board_only=True)
        self.assertEqual(result.win, 1)
        self.assertIsNone(result.dealt)
        self.assertIn("tiers are unknown", result.message)

    def test_background_worker_delivers_and_stops(self):
        reports = []
        worker = CombatWorker(reports.append)
        try:
            key = worker.submit([minion()], [minion("2")], database(), (2, 2), True)
            deadline = time.monotonic() + 3
            while not any(report.stage == "refined" for report in reports) and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(reports)
            refined = next(report for report in reversed(reports) if report.stage == "refined")
            self.assertEqual(refined.key, key)
            self.assertGreaterEqual(refined.trials, 800)
            self.assertLessEqual(refined.trials, 6000)
            self.assertIsNotNone(refined.interval)
            self.assertTrue(any(report.stage == "quick" and report.trials == 100 for report in reports))
        finally:
            worker.close()
        self.assertFalse(worker._thread.is_alive())

    def test_cancelled_trial_returns_without_holding_new_board(self):
        report = simulate([minion(attack=1, health=9999)], [minion("2", 1, 9999)], database(),
                          trials=100, board_only=True, cancelled=lambda: True)
        self.assertEqual(report.trials, 0)
        self.assertEqual(report.message, "Superseded simulation")


class SettingsTests(unittest.TestCase):
    def test_roundtrip_and_invalid_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            settings = SettingsStore(path)
            value = settings.load()
            self.assertTrue(value["auto_combat_estimate"])
            self.assertFalse(value["game_overlay"])
            value.update(x=91, opacity=.7, collapsed=["shop"], auto_combat_estimate=False,
                         game_overlay=True, game_x=1500, game_y=80, game_preset="combat")
            settings.save(value)
            self.assertEqual(settings.load()["x"], 91)
            self.assertEqual(settings.load()["collapsed"], ["shop"])
            self.assertFalse(settings.load()["auto_combat_estimate"])
            self.assertEqual((settings.load()["game_overlay"], settings.load()["game_x"], settings.load()["game_y"]),
                             (True, 1500, 80))
            self.assertEqual(settings.load()["game_preset"], "combat")
            path.write_text('{"opacity": 0, "width": 1, "height": -30, "collapsed": [1]}')
            recovered = settings.load()
            self.assertGreaterEqual(recovered["opacity"], .45)
            self.assertEqual(recovered["width"], 380)
            path.write_text("not JSON")
            self.assertEqual(settings.load()["x"], 30)


@unittest.skipUnless(os.environ.get("TEST_TK_GUI") == "1", "Set TEST_TK_GUI=1 for native Tk")
class FeatureOverlayTests(unittest.TestCase):
    def test_controls_history_and_simulation(self):
        from overlay import Overlay
        history = HistoryStore()
        with tempfile.TemporaryDirectory() as directory:
            overlay = Overlay(database(), history=history, settings_path=Path(directory) / "settings.json")
            try:
                parser = BattlegroundsParser(lambda s: (history.record(s), overlay.publish(s)), "1")
                for line in setup_lines():
                    parser.consume(line)
                parser.consume("TAG_CHANGE Entity=GameEntity tag=TURN value=6")
                parser.consume("BLOCK_START BlockType=ATTACK Entity=20")
                overlay._drain()
                self.assertEqual(overlay._opponent_name("2"), "Training hero")
                self.assertTrue(overlay.board_names)
                self.assertTrue(overlay.board_only)
                deadline = time.monotonic() + 4
                while (not overlay.odds or not overlay.odds.trials) and time.monotonic() < deadline:
                    overlay.root.update()
                    time.sleep(.01)
                self.assertGreaterEqual(overlay.odds.trials, 800)
                self.assertLessEqual(overlay.odds.trials, 6000)
                self.assertIsNotNone(overlay.odds.interval)
                self.assertIn("Hypothetical win chance", overlay.combat_estimate_title.cget("text"))
                self.assertIn(f"{overlay.odds.win:.1%}", overlay.combat_estimate_title.cget("text"))
                overlay.toggle_model()
                self.assertFalse(overlay.board_only)
                self.assertFalse(overlay.preferences["auto_combat_estimate"])
                overlay.toggle_section("shop")
                overlay.change_opacity(-.1)
                self.assertAlmostEqual(float(overlay.root.wm_attributes("-alpha")), .86, places=2)
                overlay.toggle_compact()
                overlay.root.update()
                self.assertLess(overlay.root.winfo_height(), 100)
                overlay.toggle_compact()
                overlay.root.update()
                self.assertEqual(overlay.root.winfo_width(), 1040)
                overlay.toggle_visibility()
                self.assertEqual(overlay.root.state(), "withdrawn")
                overlay.toggle_visibility()
                overlay.show_history()
                overlay.section_controls()
                overlay.root.update()
                # Explicit colors apply to every widget, including auxiliary windows.
                def check(widget):
                    keys = widget.keys()
                    if "foreground" in keys:
                        self.assertIn(widget.cget("foreground"), set(overlay.ui.colors.values()))
                    if "background" in keys:
                        self.assertIn(widget.cget("background"), set(overlay.ui.colors.values()))
                    for child in widget.winfo_children():
                        check(child)
                check(overlay.root)
                if os.sys.platform == "darwin":
                    self.assertTrue(overlay.hotkey.registered, overlay.hotkey.status)
                    # Deliver a hotkey event to this app's registered Carbon handler.
                    # No OS keyboard injection or accessibility permissions are used.
                    import ctypes as C
                    from hotkeys import HotkeyID, fourcc
                    carbon = overlay.hotkey._carbon
                    carbon.CreateEvent.argtypes = [C.c_void_p, C.c_uint32, C.c_uint32, C.c_double,
                                                    C.c_uint32, C.POINTER(C.c_void_p)]
                    carbon.SetEventParameter.argtypes = [C.c_void_p, C.c_uint32, C.c_uint32, C.c_uint32, C.c_void_p]
                    carbon.SendEventToEventTarget.argtypes = [C.c_void_p, C.c_void_p]
                    carbon.ReleaseEvent.argtypes = [C.c_void_p]
                    event = C.c_void_p()
                    self.assertEqual(carbon.CreateEvent(None, fourcc("keyb"), 6, 0., 0, C.byref(event)), 0)
                    identity = HotkeyID(fourcc("OBGT"), 1)
                    try:
                        self.assertEqual(carbon.SetEventParameter(event, fourcc("----"), fourcc("hkid"), C.sizeof(identity), C.byref(identity)), 0)
                        self.assertEqual(carbon.SendEventToEventTarget(event, carbon.GetApplicationEventTarget()), 0)
                        self.assertEqual(overlay.commands.get_nowait(), "visibility")
                    finally:
                        carbon.ReleaseEvent(event)
            finally:
                overlay.close()
                history.close()
