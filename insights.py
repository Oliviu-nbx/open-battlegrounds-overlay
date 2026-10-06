"""Explainable, local-only decision support built from observed Battlegrounds state.

Nothing in this module performs a game action, assumes an unseen opponent board,
or sends a match to a service.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import queue
import threading
from typing import Iterable

from advisor import threat_summary
from cards_db import Card, CardsDatabase
from combat import CombatReport, coverage, simulate
from parser import BattlegroundsState, MinionStats


def _total(board: Iterable[MinionStats]) -> tuple[int | None, int | None]:
    board = list(board)
    attacks = [m.attack for m in board]
    health = [m.health for m in board]
    return (sum(attacks), sum(health)) if all(isinstance(v, int) for v in attacks + health) else (None, None)


def combat_reasons(friendly: list[MinionStats], enemy: list[MinionStats], report: CombatReport | None,
                   cards: CardsDatabase) -> list[str]:
    """Observed contributors to a combat result, not a causal proof or hidden-data guess."""
    lines = []
    own_attack, own_health = _total(friendly)
    enemy_attack, enemy_health = _total(enemy)
    if own_attack is not None and enemy_attack is not None:
        lines.append(f"Observed board stats · you {own_attack}/{own_health} vs opponent {enemy_attack}/{enemy_health}.")
    own_keywords = Counter(keyword for minion in friendly for keyword in minion.keywords)
    enemy_keywords = Counter(keyword for minion in enemy for keyword in minion.keywords)
    for keyword, label in (("TAUNT", "Taunt"), ("DIVINE_SHIELD", "Divine Shield"),
                           ("POISONOUS", "Poisonous"), ("VENOMOUS", "Venomous"),
                           ("REBORN", "Reborn"), ("WINDFURY", "Windfury")):
        if own_keywords[keyword] != enemy_keywords[keyword]:
            lines.append(f"{label} count · you {own_keywords[keyword]} vs opponent {enemy_keywords[keyword]}.")
    if report:
        if report.first_attacker:
            lines.append(report.first_attacker)
        if report.dealt or report.received:
            lines.append(f"Conditional damage · deal {report.dealt or '—'} / receive {report.received or '—'}.")
        if report.baseline:
            lines.append("Incomplete baseline: listed effects were excluded, so this is a directional scenario rather than full-rules odds.")
    return lines or ["Waiting for complete observed board stats before explaining combat factors."]


def coverage_inspector(board: list[MinionStats], cards: CardsDatabase) -> dict[str, tuple[str, ...]]:
    """Group every coverage limitation so users know why a baseline is incomplete."""
    groups: dict[str, list[str]] = {"missing": [], "dynamic": [], "text": []}
    for blocker in coverage(board, cards):
        lowered = blocker.lower()
        if "missing" in lowered or "invalid" in lowered or "not a minion" in lowered:
            groups["missing"].append(blocker)
        elif "unsupported" in lowered:
            groups["dynamic"].append(blocker)
        else:
            groups["text"].append(blocker)
    return {name: tuple(values) for name, values in groups.items() if values}


def turn_plan(state: BattlegroundsState, cards: CardsDatabase) -> list[str]:
    """Compare logged Recruit choices without declaring a hidden-state optimum."""
    if state.in_combat:
        return ["Combat is active; Recruit planning resumes when the next logged shop appears."]
    if state.gold is None:
        return ["Gold has not been logged; buy / level / roll comparisons are unavailable."]
    if not state.action_costs:
        return ["Waiting for logged action costs; no fixed-cost assumptions are used."]
    lines = [f"Turn planner · {state.gold} logged gold · {len(state.board_stats)}/7 board slots."]
    labels = {"Buy": "buy", "Upgrade": "level", "Refresh": "roll", "Hero power": "use hero power"}
    for action, cost in sorted(state.action_costs.items(), key=lambda item: (item[1], item[0])):
        if cost <= state.gold:
            suffix = f"leaves {state.gold-cost} gold"
            if action == "Buy" and len(state.board_stats) >= 7:
                suffix += "; board is full, so compare a replacement"
            lines.append(f"{labels.get(action, action)} · affordable ({cost} gold, {suffix}).")
        else:
            lines.append(f"{labels.get(action, action)} · need {cost-state.gold} more gold.")
    buy, level, roll = (state.action_costs.get(key) for key in ("Buy", "Upgrade", "Refresh"))
    for first, second in (("Buy", "Upgrade"), ("Buy", "Refresh"), ("Upgrade", "Buy"), ("Refresh", "Buy")):
        first_cost, second_cost = state.action_costs.get(first), state.action_costs.get(second)
        if first_cost is not None and second_cost is not None:
            total = first_cost + second_cost
            outcome = f"leaves {state.gold-total} gold" if total <= state.gold else f"needs {total-state.gold} more gold"
            lines.append(f"{first} → {second} · {outcome}.")
    opponent = state.next_opponent
    enemy = state.opponent_stats.get(opponent, [])
    if enemy:
        threat = threat_summary(enemy, cards)
        if threat.highest_attack is not None:
            lines.append(f"Risk context · next opponent was observed with {threat.highest_attack} highest ATK; board may have changed.")
    return lines


def card_support(card: Card) -> str:
    """Compact browser badge; avoids claiming a card is fully simulated when it is not."""
    known_keywords = {"TAUNT", "DIVINE_SHIELD", "POISONOUS", "VENOMOUS", "WINDFURY", "REBORN"}
    mechanics = set(card.mechanics)
    if mechanics and mechanics - known_keywords:
        return "Baseline only"
    text = "".join(ch for ch in card.text.lower() if ch.isalpha())
    for word in ("battlecry", "deathrattle", "rally", "avenge", "summon", "combat", "attack", "adjacent"):
        if word in text:
            return "Baseline only"
    return "Generic rules"


def browser_cards(cards: CardsDatabase, query: str = "", tier: int | None = None,
                  tribe: str = "", mechanic: str = "", support: str = "") -> list[Card]:
    """Filter only the local Battlegrounds pool cache; lobby availability is never inferred."""
    query, tribe, mechanic = query.casefold(), tribe.upper(), mechanic.upper()
    selected = cards.by_tier(tier) if tier else [card for level in range(1, 7) for card in cards.by_tier(level)]
    output = []
    for card in selected:
        haystack = " ".join((card.name, card.minion_type, card.text, " ".join(card.mechanics))).casefold()
        if query and query not in haystack:
            continue
        if tribe and tribe not in set(card.races) and tribe not in card.minion_type.upper():
            continue
        if mechanic and mechanic not in set(card.mechanics) and mechanic not in card.text.upper():
            continue
        if support and card_support(card) != support:
            continue
        output.append(card)
    return sorted(output, key=lambda card: (card.tier or 99, card.minion_type, card.name))


@dataclass(frozen=True)
class PositioningOption:
    order: tuple[str, ...]
    win: float
    loss: float
    tie: float
    baseline: bool


@dataclass(frozen=True)
class PositioningAnalysis:
    current: PositioningOption
    best: PositioningOption
    options: tuple[PositioningOption, ...]
    note: str


def _candidate_orders(board: list[MinionStats]) -> list[list[MinionStats]]:
    """Bounded legal alternatives: current plus front/back moves and front swaps."""
    result: list[list[MinionStats]] = [list(board)]
    for index, minion in enumerate(board):
        remaining = list(board)
        remaining.pop(index)
        result.append([minion, *remaining])
        result.append([*remaining, minion])
    for index in range(1, len(board)):
        candidate = list(board)
        candidate[0], candidate[index] = candidate[index], candidate[0]
        result.append(candidate)
    unique, keys = [], set()
    for candidate in result:
        key = tuple(m.entity_id for m in candidate)
        if key not in keys:
            keys.add(key)
            unique.append(candidate)
    return unique[:15]


def positioning_analysis(friendly: list[MinionStats], enemy: list[MinionStats], cards: CardsDatabase,
                         tiers: tuple[int | None, int | None], trials: int = 220,
                         opponent_age: int = 0) -> PositioningAnalysis | None:
    """Evaluate bounded local arrangements against an observed opponent board only."""
    if not friendly or not enemy or len(friendly) > 7 or len(enemy) > 7:
        return None
    options = []
    for index, order in enumerate(_candidate_orders(friendly)):
        report = simulate(order, enemy, cards, tiers, trials=trials, seed=7300 + index,
                          board_only=True, opponent_age=opponent_age, allow_baseline=True)
        if not report.trials:
            return None
        options.append(PositioningOption(tuple(m.entity_id for m in order), report.win, report.loss, report.tie, report.baseline))
    current = options[0]
    best = max(options, key=lambda option: (option.win + option.tie * .5, option.win, -option.loss))
    note = "Observed-board positioning sandbox; it does not move minions in Hearthstone."
    if best.order == current.order:
        note += " Current order is best among the checked local alternatives."
    else:
        note += f" Best checked alternative changes expected outcome by {(best.win + best.tie*.5) - (current.win + current.tie*.5):+.1%}."
    if best.baseline:
        note += " Incomplete baseline effects remain excluded."
    return PositioningAnalysis(current, best, tuple(options), note)


class PositioningWorker:
    """Latest-only worker for local board-order comparisons."""
    def __init__(self, on_result) -> None:
        self.on_result = on_result
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop, self._lock = threading.Event(), threading.Lock()
        self._generation = 0
        self._thread = threading.Thread(target=self._run, name="positioning-model", daemon=True)
        self._thread.start()

    def submit(self, friendly, enemy, cards, tiers, opponent_age=0) -> int:
        with self._lock:
            self._generation += 1
            generation = self._generation
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        self._queue.put_nowait((generation, friendly, enemy, cards, tiers, opponent_age))
        return generation

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                generation, friendly, enemy, cards, tiers, age = self._queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                result = positioning_analysis(friendly, enemy, cards, tiers, opponent_age=age)
            except Exception:
                result = None
            with self._lock:
                current = self._generation
            if not self._stop.is_set() and generation == current:
                self.on_result(generation, result)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
