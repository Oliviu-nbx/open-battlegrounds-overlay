"""Local JSON bridge for the native AppKit overlay.

The feed is intentionally a private file on the same Mac. It receives parsed
Power.log state, runs the existing conservative combat worker, and never opens a
network listener or sends game data anywhere.
"""
from __future__ import annotations

import copy
import json
import logging
import signal
import sqlite3
import sys
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from advisor import recruit_plan, threat_summary
from cards_db import CardsDatabase
from combat import CombatReport, CombatWorker, model_key
from config import HearthstonePaths, discover_installation, ensure_client_logging, ensure_power_logging
from history import HistoryStore
from insights import combat_reasons, coverage_inspector, turn_plan
from parser import BattlegroundsParser, BattlegroundsState, MinionStats, PowerLogTailer


class NativeStatePublisher:
    """Atomic local state snapshots consumed by the companion AppKit panel."""
    def __init__(self, path: Path, data_dir: Path, locale: str = "enUS", demo: bool = False,
                 on_prediction=None) -> None:
        self.path, self.data_dir, self.locale, self.demo = Path(path), Path(data_dir), locale, demo
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cards = CardsDatabase(self.data_dir, self.locale)
        self.state = BattlegroundsState(stream_status="Starting native overlay feed…")
        self.card_status = "Loading local card reference…"
        self.report: CombatReport | None = None
        self._model_key = ""
        self._closed = False
        self.on_prediction = on_prediction
        self._lock = threading.RLock()
        self._worker = CombatWorker(self._receive_report)
        self._write_locked()

    @staticmethod
    def _minion(minion: MinionStats, cards: CardsDatabase) -> dict:
        card = cards.get(minion.card_id)
        return {"id": minion.card_id, "name": card.name if card else minion.name or minion.card_id or "Unknown minion",
                "attack": minion.attack, "health": minion.health, "keywords": list(minion.keywords)}

    def _opponent(self):
        state = self.state
        captured = state.in_combat and state.combat_round == state.round
        opponent = state.combat_opponent if captured else state.next_opponent
        board = state.opponent_stats.get(opponent, [])
        hero = state.opponent_heroes.get(opponent)
        hero_card = self.cards.get(hero) if hero else None
        name = hero_card.name if hero_card else (f"Opponent {opponent}" if opponent else "Opponent not observed")
        seen = state.opponent_rounds.get(opponent)
        age = max(0, state.round-seen) if seen is not None else None
        return opponent, board, {"name": name, "seen_round": seen, "age": age,
                                 "board": [self._minion(minion, self.cards) for minion in board],
                                 "threat": list(threat_summary(board, self.cards).signals)}

    def _odds_payload(self, own: list[MinionStats], enemy: list[MinionStats]) -> dict:
        if not own:
            return {"state": "waiting", "title": "Win chance awaiting your board",
                    "detail": "Need observed friendly minions before an estimate can run.",
                    "modelled": [], "blockers": []}
        if not enemy:
            return {"state": "waiting", "title": "Win chance awaiting opponent",
                    "detail": "Need a last-observed opponent board before an estimate can run.",
                    "modelled": [], "blockers": []}
        report = self.report
        if report is None or report.key != self._model_key:
            return {"state": "calculating", "title": "Calculating hypothetical win chance…",
                    "detail": "Observed boards only; a quick result is refined in the background.",
                    "modelled": [], "blockers": []}
        if report.trials:
            return {"state": "ready", "title": "Incomplete baseline win chance" if report.baseline else "Hypothetical win chance", "detail": report.message,
                    "win": report.win, "loss": report.loss, "tie": report.tie,
                    "first_attacker": report.first_attacker, "modelled": list(report.modelled),
                    "blockers": list(report.blockers), "baseline": report.baseline,
                    "dealt": list(report.dealt) if report.dealt else None,
                    "received": list(report.received) if report.received else None,
                    "interval": list(report.interval) if report.interval else None,
                    "sample_error": report.sample_error, "confidence": report.confidence,
                    "scenario": list(report.scenario) if report.scenario else None,
                    "scenario_detail": report.scenario_detail, "stage": report.stage}
        return {"state": "unavailable", "title": "Win chance unavailable", "detail": report.message,
                "modelled": list(report.modelled), "blockers": list(report.blockers)}

    def _payload_locked(self) -> dict:
        state = self.state
        captured = state.in_combat and state.combat_round == state.round
        own = state.combat_board if captured else state.board_stats
        _, enemy, opponent = self._opponent()
        phase = "combat" if state.in_combat else "recruit" if state.active else "waiting"
        return {"schema": 1, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "phase": phase, "round": state.round, "tier": state.tavern_tier if state.local_player else None,
                "gold": state.gold, "health": state.health, "armor": state.armor,
                "status": self.card_status if "Loading" in self.card_status else state.stream_status,
                "board": [self._minion(minion, self.cards) for minion in own],
                "opponent": opponent, "odds": self._odds_payload(own, enemy),
                "recruit_plan": recruit_plan(state, self.cards) if phase == "recruit" else [],
                "turn_plan": turn_plan(state, self.cards) if phase == "recruit" else [],
                "combat_factors": combat_reasons(own, enemy, self.report, self.cards) if phase == "combat" else [],
                "coverage": coverage_inspector(own + enemy, self.cards)}

    def _write_locked(self) -> None:
        if self._closed:
            return
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._payload_locked(), ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def _schedule_locked(self) -> None:
        state = self.state
        captured = state.in_combat and state.combat_round == state.round
        opponent = state.combat_opponent if captured else state.next_opponent
        own = state.combat_board if captured else state.board_stats
        enemy = state.opponent_stats.get(opponent, [])
        tiers = (state.tavern_tier, state.opponent_tiers.get(opponent))
        seen = state.opponent_rounds.get(opponent)
        age = max(0, state.round-seen) if seen is not None else 0
        key = model_key(own, enemy, self.cards, tiers, True, age, True)
        if key != self._model_key:
            self._model_key, self.report = key, None
            # Empty boards cannot yield odds. Do not let a waiting-state task sit
            # ahead of the first revealed combat board in the one-item worker.
            if own and enemy:
                self._worker.submit(own, enemy, self.cards, tiers, True, age, True)

    def publish(self, state: BattlegroundsState) -> None:
        with self._lock:
            self.state = copy.deepcopy(state)
            self._schedule_locked()
            self._write_locked()

    def publish_cards(self, cards: CardsDatabase, message: str) -> None:
        with self._lock:
            self.cards, self.card_status = cards, message
            self._schedule_locked()
            self._write_locked()

    def _receive_report(self, report: CombatReport) -> None:
        with self._lock:
            if not self._closed and report.key == self._model_key:
                self.report = report
                if report.trials and report.stage == "refined" and self.on_prediction:
                    self.on_prediction(copy.deepcopy(self.state), report)
                self._write_locked()

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._worker.close()


def run_native_feed(args, data_dir: Path) -> None:
    """Run a non-GUI local tracker backend until the AppKit host terminates it."""
    paths = HearthstonePaths.current()
    if not args.demo and args.log is None:
        for notice in ensure_power_logging(paths):
            logging.info(notice)
        if sys.platform == "darwin":
            installation = discover_installation()
            if installation:
                logging.info(ensure_client_logging(installation))
    output = args.state_file or data_dir / "native_overlay_state.json"
    publisher = NativeStatePublisher(output, data_dir, args.locale, args.demo)
    stopped = threading.Event()

    def request_stop(*_):
        stopped.set()

    previous_term = signal.signal(signal.SIGTERM, request_stop)
    previous_int = signal.signal(signal.SIGINT, request_stop)
    try:
        try:
            history = HistoryStore(":memory:" if args.demo else data_dir / "tracker.sqlite3")
        except (OSError, sqlite3.Error) as exc:
            logging.warning("Persistent history unavailable (%s); using temporary history", exc)
            history = HistoryStore()
        publisher.on_prediction = lambda state, report: history.record_prediction(state, report)
        storage_failed = False

        def publish(state: BattlegroundsState) -> None:
            nonlocal storage_failed
            try:
                history.record(state)
            except sqlite3.Error as exc:
                if not storage_failed:
                    logging.warning("History write failed; native overlay remains live: %s", exc)
                    storage_failed = True
            publisher.publish(state)

        parser = BattlegroundsParser(publish, "1" if args.demo else args.player_id, publish_interval=.1)

        def load_cards() -> None:
            cards = CardsDatabase(data_dir, args.locale)
            count = 0
            try:
                count = cards.load()
            except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
                logging.warning("Card cache unreadable: %s", exc)
            if args.demo:
                from demo import TRAINING_CARDS
                cards.add(TRAINING_CARDS)
                publisher.publish_cards(cards, "Training cards + local reference · demo history is temporary")
                return
            if count:
                publisher.publish_cards(cards, f"{count} cards cached locally")
            if not count or args.refresh_cards:
                fresh = CardsDatabase(data_dir, args.locale)
                try:
                    count = fresh.refresh()
                    publisher.publish_cards(fresh, f"{count} cards cached locally")
                except Exception as exc:
                    logging.warning("Card download failed: %s", exc)
                    publisher.publish_cards(cards, "Card download failed; using cache" if count else "Card download failed; displaying card IDs")

        threading.Thread(target=load_cards, name="native-card-reference", daemon=True).start()
        tailer = None
        if args.demo:
            from demo import run_demo
            threading.Thread(target=run_demo, args=(parser, stopped), name="native-demo", daemon=True).start()
        else:
            tailer = PowerLogTailer(args.log or paths.logs_dir, parser.consume,
                                   on_status=parser.set_stream_status, on_stream=parser.begin_stream,
                                   on_idle=parser.flush)
            tailer.start()
        while not stopped.wait(.25):
            pass
    finally:
        stopped.set()
        if 'tailer' in locals() and tailer:
            tailer.stop()
        if 'history' in locals():
            history.close()
        publisher.close()
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
