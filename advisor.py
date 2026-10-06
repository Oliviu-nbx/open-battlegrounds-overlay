"""Explainable, local heuristics. These are comparisons, not optimal-play claims."""
from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass

from cards_db import CardsDatabase
from parser import BattlegroundsState, MinionStats


def plain_text(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\n", " ")


def _name(minion: MinionStats, cards: CardsDatabase) -> str:
    card = cards.get(minion.card_id)
    return card.name if card else minion.name or minion.card_id or "Unknown minion"


def _stat_total(minion: MinionStats) -> int | None:
    if minion.attack is None or minion.health is None:
        return None
    return minion.attack + minion.health


@dataclass(frozen=True)
class ShopSuggestion:
    minion: MinionStats
    score: float
    reasons: tuple[str, ...]
    text: str
    replacement: str = ""


@dataclass(frozen=True)
class ThreatSummary:
    total_attack: int | None
    total_health: int | None
    highest_attack: int | None
    highest_health: int | None
    signals: tuple[str, ...]


def compare_shop(state: BattlegroundsState, cards: CardsDatabase) -> list[ShopSuggestion]:
    """Rank observed shop minions with explicitly limited, visible heuristics."""
    copies = Counter(m.card_id for m in state.board_stats + state.hand_stats)
    board_tribes = [set(card.races) for m in state.board_stats if (card := cards.get(m.card_id))]
    weakest = min((m for m in state.board_stats if _stat_total(m) is not None),
                  key=lambda minion: _stat_total(minion), default=None)
    result = []
    for minion in state.shop_stats:
        card = cards.get(minion.card_id)
        reasons = []
        score = 0.
        current_total = _stat_total(minion)
        if current_total is not None:
            score = current_total
            reasons.append(f"{minion.attack}/{minion.health} current stats")
            if len(state.board_stats) >= 7 and weakest is not None:
                delta = current_total - _stat_total(weakest)
                reasons.append(f"{delta:+g} raw stat total vs weakest logged slot (effects excluded)")
        else:
            reasons.append("Stats incomplete; score is partial")
        replacement = ""
        if len(state.board_stats) >= 7 and weakest is not None:
            weakest_name = _name(weakest, cards)
            replacement = f"Compare with {weakest_name} ({weakest.attack}/{weakest.health}); effects are not compared."
        if card:
            races = set(card.races)
            matches = sum(bool(races and other and (races & other or "ALL" in races or "ALL" in other))
                          for other in board_tribes)
            if matches:
                score += 2 * matches
                reasons.append(f"Shares a tribe with {matches} board minions (+{2 * matches})")
            reasons.append(card.minion_type.replace("_", " ").title())
        if copies[minion.card_id]:
            reasons.append(f"{copies[minion.card_id]} matching card IDs already on board/in hand")
        bonuses = {"DIVINE_SHIELD": 3, "TAUNT": 1, "WINDFURY": 2,
                   "VENOMOUS": 3, "POISONOUS": 3, "REBORN": 2}
        for keyword in minion.keywords:
            bonus = bonuses.get(keyword, 0)
            score += bonus
            reasons.append(f"{keyword.replace('_', ' ').title()} (+{bonus})")
        result.append(ShopSuggestion(minion, score, tuple(reasons),
                                     plain_text(card.text) if card else "Card text unavailable", replacement))
    return sorted(result, key=lambda suggestion: (-suggestion.score, suggestion.minion.entity_id))


def economy_notes(state: BattlegroundsState) -> list[str]:
    """Use only costs observed in the current log; never assume a patch's economy."""
    if state.in_combat:
        return ["Combat: spending reminders paused."]
    if state.gold is None:
        return ["Gold has not been logged yet; affordability is unknown."]
    output = [f"{state.gold} gold available · {len(state.board_stats)}/7 board slots"]
    if not state.action_costs:
        output.append("Waiting for logged action costs; no fixed-cost assumptions.")
    for action, cost in sorted(state.action_costs.items()):
        suffix = f"affordable; {state.gold - cost} gold left" if cost <= state.gold else f"need {cost - state.gold} more gold"
        output.append(f"{action}: {cost} gold — {suffix}")
    # Show only sequences made from actions that were actually logged this turn.
    for first, second in (("Buy", "Refresh"), ("Refresh", "Buy"), ("Buy", "Upgrade"), ("Upgrade", "Buy")):
        first_cost, second_cost = state.action_costs.get(first), state.action_costs.get(second)
        if first_cost is None or second_cost is None:
            continue
        total = first_cost + second_cost
        if total <= state.gold:
            output.append(f"{first} → {second}: affordable; {state.gold-total} gold left")
        else:
            output.append(f"{first} → {second}: need {total-state.gold} more gold")
    buy = state.action_costs.get("Buy")
    if buy and state.gold >= buy:
        output.append(f"Budget for up to {state.gold // buy} buys, before other spending.")
    if state.gold > 0:
        output.append("Remember remaining gold before ending recruit; unused gold normally does not carry over.")
    if len(state.board_stats) >= 7:
        output.append("Board full: compare card effects before replacing a slot.")
    if len(state.hand_stats) >= 10:
        output.append("At least 10 minions in hand; check hand space before buying.")
    output.append("Affordability does not prove an action is legal (targets, hand space, or power charges).")
    return output


def recruit_plan(state: BattlegroundsState, cards: CardsDatabase) -> list[str]:
    """Short Recruit surface combining logged affordability and shop heuristics."""
    lines = list(economy_notes(state))
    if state.in_combat:
        return lines
    suggestions = compare_shop(state, cards)
    if not suggestions:
        lines.append("No shop minions observed yet; no buy recommendation.")
        return lines
    best = suggestions[0]
    lines.append(f"Heuristic shop lead: {_name(best.minion, cards)} · score {best.score:g}")
    lines.extend(f"  {reason}" for reason in best.reasons[:3])
    if best.replacement:
        lines.append("  " + best.replacement)
    return lines


def threat_summary(board: list[MinionStats], cards: CardsDatabase) -> ThreatSummary:
    """Describe only visible, last-observed threats; no hidden-board inference."""
    attack_values = [m.attack for m in board if m.attack is not None]
    health_values = [m.health for m in board if m.health is not None]
    if not board:
        return ThreatSummary(None, None, None, None, ("No observed opponent board.",))
    total_attack = sum(attack_values) if len(attack_values) == len(board) else None
    total_health = sum(health_values) if len(health_values) == len(board) else None
    highest_attack = max(attack_values, default=None)
    highest_health = max(health_values, default=None)
    keywords = Counter(keyword for minion in board for keyword in minion.keywords)
    signals = []
    if total_attack is not None and total_health is not None:
        signals.append(f"Observed board total {total_attack}/{total_health}.")
    if highest_attack is not None and highest_attack >= 20:
        signals.append(f"High-attack threat: {highest_attack} ATK observed.")
    if highest_health is not None and highest_health >= 30:
        signals.append(f"Large health wall: {highest_health} HP observed.")
    for keyword, title in (("POISONOUS", "Poisonous"), ("VENOMOUS", "Venomous"),
                           ("DIVINE_SHIELD", "Divine Shield"), ("TAUNT", "Taunt"),
                           ("WINDFURY", "Windfury"), ("REBORN", "Reborn")):
        if keywords[keyword]:
            signals.append(f"{title} ×{keywords[keyword]}.")
    if not signals:
        signals.append("Visible stats are incomplete; no numeric threat summary.")
    return ThreatSummary(total_attack, total_health, highest_attack, highest_health, tuple(signals))
