"""Private SQLite match journal. No account names or network uploads are stored."""
from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from combat import CombatReport
from parser import BattlegroundsState


class HistoryStore:
    def __init__(self, path: Path | str = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), timeout=2, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY, tracked_at TEXT NOT NULL, hero TEXT NOT NULL,
                result TEXT NOT NULL DEFAULT '', placement INTEGER, last_round INTEGER NOT NULL,
                placement_source TEXT NOT NULL DEFAULT 'log');
            CREATE TABLE IF NOT EXISTS rounds (
                match_id TEXT NOT NULL REFERENCES matches(id), round INTEGER NOT NULL,
                phase TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(match_id, round, phase));
            CREATE TABLE IF NOT EXISTS predictions (
                match_id TEXT NOT NULL, round INTEGER NOT NULL, model_key TEXT NOT NULL,
                predicted_win REAL NOT NULL, predicted_loss REAL NOT NULL, predicted_tie REAL NOT NULL,
                confidence TEXT NOT NULL, opponent_age INTEGER NOT NULL, trials INTEGER NOT NULL,
                outcome TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                PRIMARY KEY(match_id, round, model_key));
        """)
        self._last: dict[tuple, str] = {}

    def record(self, state: BattlegroundsState) -> None:
        if not state.game_id or not state.local_player or not state.hero_card_id or state.round <= 0:
            return
        if not state.active and not state.result:
            return
        # Use frozen, pre-attack boards, never the partially destroyed live board.
        if state.in_combat and state.combat_round != state.round:
            return
        phase = "combat" if state.in_combat else "recruit"
        board = state.combat_board if state.in_combat else state.board_stats
        payload = json.dumps({"tier": state.tavern_tier, "health": state.health,
                              "armor": state.armor, "gold": state.gold,
                              "board": [asdict(m) for m in board],
                              "next_opponent": state.next_opponent,
                              "opponents": {k: [asdict(m) for m in v] for k, v in state.opponent_stats.items()},
                              "opponent_rounds": state.opponent_rounds,
                              "opponent_heroes": state.opponent_heroes}, sort_keys=True)
        key = (state.game_id, state.round, phase)
        signature = payload + state.result + str(state.placement)
        with self._lock:
            if self._last.get(key) == signature:
                return
            with self._db:
                self._db.execute("""INSERT INTO matches(id,tracked_at,hero,result,placement,last_round)
                    VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    hero=excluded.hero, result=CASE WHEN excluded.result='' THEN matches.result ELSE excluded.result END,
                    placement=CASE WHEN matches.placement_source='manual' THEN matches.placement
                        ELSE COALESCE(excluded.placement,matches.placement) END,
                    last_round=MAX(excluded.last_round,matches.last_round)""",
                    (state.game_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     state.hero_card_id, state.result, state.placement, state.round))
                # A repeated replay may revisit a finished snapshot. Upserts are intentional.
                self._db.execute("""INSERT INTO rounds VALUES(?,?,?,?)
                    ON CONFLICT(match_id,round,phase) DO UPDATE SET payload=excluded.payload""",
                    (state.game_id, state.round, phase, payload))
            self._last[key] = signature
            if len(self._last) > 128:
                self._last.pop(next(iter(self._last)))
            if state.combat_outcome and state.combat_outcome_round:
                with self._db:
                    self._db.execute("UPDATE predictions SET outcome=? WHERE match_id=? AND round=? AND outcome=''",
                                     (state.combat_outcome, state.game_id, state.combat_outcome_round))

    def record_prediction(self, state: BattlegroundsState, report: CombatReport) -> None:
        """Save an observed-board estimate; outcome remains blank until the log proves it."""
        if not (report.trials and state.game_id and state.combat_round and state.local_player):
            return
        opponent = state.combat_opponent or state.next_opponent
        seen = state.opponent_rounds.get(opponent)
        age = max(0, state.combat_round-seen) if seen is not None else 0
        with self._lock, self._db:
            self._db.execute("""INSERT INTO predictions VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(match_id,round,model_key) DO NOTHING""",
                             (state.game_id, state.combat_round, report.key, report.win, report.loss, report.tie,
                              report.confidence, age, report.trials, "",
                              datetime.now(timezone.utc).isoformat(timespec="seconds")))

    def calibration(self) -> dict:
        """Local calibration from outcomes the Power.log made unambiguous; no inference."""
        with self._lock:
            rows = list(self._db.execute("SELECT predicted_win,predicted_tie,confidence,opponent_age,outcome FROM predictions WHERE outcome!=''"))
        if not rows:
            return {"samples": 0, "predicted": None, "actual": None, "brier": None, "by_confidence": {}}
        expected = [row["predicted_win"] + row["predicted_tie"] / 2 for row in rows]
        actuals = [1. if row["outcome"] == "win" else .5 if row["outcome"] == "tie" else 0. for row in rows]
        groups: dict[str, list[tuple[float, float]]] = {}
        for row, prediction, outcome in zip(rows, expected, actuals):
            groups.setdefault(row["confidence"], []).append((prediction, outcome))
        return {"samples": len(rows), "predicted": sum(expected)/len(expected), "actual": sum(actuals)/len(actuals),
                "brier": sum((prediction-outcome)**2 for prediction, outcome in zip(expected, actuals))/len(rows),
                "by_confidence": {key: {"samples": len(values),
                                           "predicted": sum(v[0] for v in values)/len(values),
                                           "actual": sum(v[1] for v in values)/len(values)}
                                  for key, values in groups.items()}}

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self._db.execute(
                "SELECT * FROM matches ORDER BY tracked_at DESC, id DESC LIMIT ?", (limit,))]

    def by_hero(self) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self._db.execute("""SELECT hero, COUNT(*) AS tracked,
                COUNT(placement) AS ranked, AVG(placement) AS average,
                SUM(CASE WHEN placement<=4 THEN 1 ELSE 0 END) AS top4
                FROM matches GROUP BY hero ORDER BY ranked DESC, hero""")]

    def detail(self, match_id: str) -> list[dict]:
        with self._lock:
            return [{"round": row["round"], "phase": row["phase"], **json.loads(row["payload"])}
                    for row in self._db.execute("SELECT * FROM rounds WHERE match_id=? ORDER BY round,phase DESC", (match_id,))]

    def timeline(self, match_id: str) -> list[dict]:
        """Summarize observed board changes round by round without inventing actions."""
        by_round: dict[int, dict] = {}
        for snapshot in self.detail(match_id):
            # Prefer the frozen pre-combat board when both phase snapshots exist.
            existing = by_round.get(snapshot["round"])
            if existing is None or snapshot["phase"] == "combat":
                by_round[snapshot["round"]] = snapshot
        previous_cards: Counter[str] = Counter()
        previous_attack = previous_health = 0
        output = []
        for round_number in sorted(by_round):
            snapshot = by_round[round_number]
            board = snapshot["board"]
            cards = Counter(minion["card_id"] for minion in board if minion.get("card_id"))
            attack = sum(minion["attack"] for minion in board if isinstance(minion.get("attack"), int))
            health = sum(minion["health"] for minion in board if isinstance(minion.get("health"), int))
            added = tuple(sorted((cards - previous_cards).elements()))
            removed = tuple(sorted((previous_cards - cards).elements()))
            output.append({"round": round_number, "phase": snapshot["phase"], "tier": snapshot.get("tier"),
                           "health": snapshot.get("health"), "armor": snapshot.get("armor"),
                           "gold": snapshot.get("gold"), "attack": attack, "board_health": health,
                           "attack_change": attack-previous_attack if output else None,
                           "health_change": health-previous_health if output else None,
                           "added": added, "removed": removed,
                           "opponents_seen": len(snapshot.get("opponents", {}))})
            previous_cards, previous_attack, previous_health = cards, attack, health
        return output

    def opponent_timeline(self, match_id: str, opponent: str) -> list[dict]:
        """Evidence-only changes for one observed opponent in one local match."""
        previous = Counter()
        output = []
        for snapshot in self.detail(match_id):
            board = snapshot.get("opponents", {}).get(opponent)
            if board is None:
                continue
            cards = Counter(minion.get("card_id") for minion in board if minion.get("card_id"))
            attack = sum(minion.get("attack", 0) for minion in board if isinstance(minion.get("attack"), int))
            health = sum(minion.get("health", 0) for minion in board if isinstance(minion.get("health"), int))
            output.append({"round": snapshot["round"], "count": len(board), "attack": attack, "health": health,
                           "added": tuple(sorted((cards - previous).elements())),
                           "removed": tuple(sorted((previous - cards).elements()))})
            previous = cards
        return output

    def community_summary(self) -> dict:
        """Manual, aggregate-only share export. It contains no account, match ID, time or board data."""
        matches = self.recent(100000)
        heroes, placements, observed_rounds = Counter(), Counter(), []
        for match in matches:
            heroes[match["hero"]] += 1
            if match["placement"] is not None:
                placements[str(match["placement"])] += 1
            observed_rounds.append(len(self.timeline(match["id"])))
        return {"schema": 1, "kind": "open-battlegrounds-anonymous-summary",
                "privacy": "Manual export only; contains no account, player name, match ID, timestamp or board records.",
                "match_count": len(matches), "hero_counts": dict(sorted(heroes.items())),
                "placement_counts": dict(sorted(placements.items())),
                "mean_observed_rounds": sum(observed_rounds)/len(observed_rounds) if observed_rounds else None}

    def review(self, match_id: str) -> dict | None:
        """Return an evidence-only post-match review derived from stored snapshots."""
        with self._lock:
            row = self._db.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        if not row:
            return None
        timeline = self.timeline(match_id)
        peak = max(timeline, key=lambda item: item["attack"] + item["board_health"], default=None)
        final = timeline[-1] if timeline else None
        return {"placement": row["placement"], "placement_source": row["placement_source"],
                "result": row["result"], "observed_rounds": len(timeline),
                "highest_tier": max((item["tier"] or 0 for item in timeline), default=None) or None,
                "peak": peak, "final": final, "timeline": timeline}

    def set_placement(self, match_id: str, placement: int) -> None:
        """User correction is explicit and retains a 'manual' provenance marker."""
        if not 1 <= placement <= 8:
            raise ValueError("Placement must be 1–8")
        with self._lock, self._db:
            self._db.execute("UPDATE matches SET placement=?, placement_source='manual' WHERE id=?",
                             (placement, match_id))

    def export(self) -> dict:
        matches = self.recent(100000)
        return {"schema": 1, "matches": [{**m, "rounds": self.detail(m["id"])} for m in matches]}

    def close(self) -> None:
        with self._lock:
            self._db.close()
