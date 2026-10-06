"""Conservative Monte Carlo engine for observed Battlegrounds board scenarios.

Only auditable rules are simulated. Unknown card text, hidden hand state and
external effects block predictions instead of being approximated as game truth.
"""
from __future__ import annotations

import copy
import hashlib
import json
import queue
import random
import re
import threading
from dataclasses import asdict, dataclass, field, replace
from typing import Callable

from cards_db import CardsDatabase
from parser import MinionStats

SUPPORTED = {"TAUNT", "DIVINE_SHIELD", "POISONOUS", "VENOMOUS", "WINDFURY", "REBORN"}
PRESENTATION_MECHANICS = {"TRIGGER_VISUAL"}
TRANSIENT_EFFECTS = {"CANT_ATTACK"}
GENERIC_EFFECTS = {"CLEAVE", "MEGA_WINDFURY", "NONSTANDARD_WINDFURY", "IMMUNE",
                   "IMMUNE_WHILE_ATTACKING", "CANT_BE_ATTACKED", "STEALTH"}

# Effects already reflected in logged pre-combat stats or relevant only outside combat.
OBSERVED_STAT_CARD_IDS = {"BG21_015", "BG21_015_G", "BG36_354", "BG36_354_G",
                          "BG36_243", "BG36_243_G", "BG36_511", "BG36_511_G",
                          "BG32_324", "BG32_324_G"}
ELECTRIC_BUFFS = {"BG26_963": (1, 1), "BG26_963_G": (2, 2)}
RUNIC_RINGS = {"BG36_245": 2, "BG36_245_G": 4}
RECRUITER_BUFFS = {"BG29_816": (3, 1), "BG29_816_G": (6, 2)}
MUMMIFIER_TARGETS = {"BG28_309": 1, "BG28_309_G": 2}
HOPEBRINGER_BUFFS = {"BG36_364": (3, 3), "BG36_364_G": (6, 6)}
ETERNAL_KNIGHT_BUFFS = {"BG25_008": (4, 2), "BG25_008_G": (8, 4)}

# Additional, exact text rules audited against the bundled HearthstoneJSON cache.
HUMMING_BIRD_BUFFS = {"BG26_805": 1, "BG26_805_G": 2}
PAPER_DRAKE_TARGETS = {"BG29_810": 1, "BG29_810_G": 2}
EVOKER_BUFFS = {"BG32_822": (2, 2), "BG32_822_G": (4, 4)}
AMBER_TARGETS = {"BG24_500": 1, "BG24_500_G": 2}
BOOM_REPEATS = {"BG36_620": 1, "BG36_620_G": 2}
TITUS_EXTRAS = {"BG25_354": 1, "BG25_354_G": 2}

# Logged Blood-Gem size is attached to each frozen combat minion as
# BLOOD_GEM_ATTACK / BLOOD_GEM_HEALTH by parser.py. These effects resolve only
# after an attack; hand-only gem duplication remains deliberately out of combat.
BONKER_GEMS = {"BG20_104": 1, "BG20_104_G": 2}
VINEWEAVER_GEMS = {"BG33_883": 3, "BG33_883_G": 6}
SANGUINE_REFINER_GEMS = {"BG33_885": (1, 2), "BG33_885_G": (2, 4)}
HAND_GEM_ONLY = {"BG30_121", "BG30_121_G"}

# (count, attack, health, races, reborn, generated card id). Only fixed-output
# deathrattles are included; hand/random generation remains a visible blocker.
DEATHRATTLE_SUMMONS = {
    "BG28_300": (2, 1, 1, {"UNDEAD"}, False, "BG28_300_TOKEN"),
    "BG28_300_G": (4, 1, 1, {"UNDEAD"}, False, "BG28_300_TOKEN"),
    "BG30_125": (3, 1, 1, {"UNDEAD"}, False, "BG28_300_TOKEN"),
    "BG30_125_G": (6, 1, 1, {"UNDEAD"}, False, "BG28_300_TOKEN"),
    "BG25_010": (1, 2, 1, {"UNDEAD"}, True, "BG25_010_TOKEN"),
    "BG25_010_G": (2, 2, 1, {"UNDEAD"}, True, "BG25_010_TOKEN"),
    "BG29_611": (1, 1, 1, {"MECH"}, False, "BG29_611_TOKEN"),
    "BG29_611_G": (1, 2, 2, {"MECH"}, False, "BG29_611_TOKEN"),
    "BG31_801": (1, 2, 2, {"BEAST"}, False, "BG31_801_TOKEN"),
    "BG31_801_G": (2, 2, 2, {"BEAST"}, False, "BG31_801_TOKEN"),
    "BG31_803": (1, 2, 2, {"BEAST"}, False, "BG31_801_TOKEN"),
    "BG31_803_G": (2, 2, 2, {"BEAST"}, False, "BG31_801_TOKEN"),
    "BG31_809": (1, 2, 2, {"BEAST"}, False, "BG31_801_TOKEN"),
    "BG31_809_G": (2, 2, 2, {"BEAST"}, False, "BG31_801_TOKEN"),
    "BG25_009": (1, 4, 2, {"UNDEAD"}, False, "BG25_008"),
    "BG25_009_G": (1, 8, 4, {"UNDEAD"}, False, "BG25_008_G"),
}

MODELLED_CARD_IDS = (set(ELECTRIC_BUFFS) | set(RUNIC_RINGS) | set(RECRUITER_BUFFS)
                    | set(MUMMIFIER_TARGETS) | set(HOPEBRINGER_BUFFS) | set(ETERNAL_KNIGHT_BUFFS)
                    | set(HUMMING_BIRD_BUFFS) | set(PAPER_DRAKE_TARGETS) | set(EVOKER_BUFFS)
                    | set(AMBER_TARGETS) | set(BOOM_REPEATS) | set(TITUS_EXTRAS)
                    | set(BONKER_GEMS) | set(VINEWEAVER_GEMS) | set(SANGUINE_REFINER_GEMS) | HAND_GEM_ONLY
                    | set(DEATHRATTLE_SUMMONS))
SAFE_TEXT_CARD_IDS = OBSERVED_STAT_CARD_IDS | MODELLED_CARD_IDS


@dataclass(frozen=True)
class CombatReport:
    key: str
    message: str
    trials: int = 0
    win: float = 0
    loss: float = 0
    tie: float = 0
    dealt: tuple[int, int] | None = None
    received: tuple[int, int] | None = None
    blockers: tuple[str, ...] = ()
    modelled: tuple[str, ...] = ()
    first_attacker: str = ""
    interval: tuple[float, float] | None = None
    sample_error: float | None = None
    confidence: str = "Unavailable"
    scenario: tuple[float, float] | None = None
    scenario_detail: str = ""
    baseline: bool = False
    stage: str = "refined"


@dataclass
class Unit:
    position: float
    attack: int
    health: int
    keywords: set[str]
    tier: int | None
    card_id: str = ""
    races: set[str] = field(default_factory=set)
    reborn: bool = False
    script_data: dict[str, int] = field(default_factory=dict)
    effects: set[str] = field(default_factory=set)


def _allowed_mechanics(card_id: str) -> set[str]:
    allowed = set(PRESENTATION_MECHANICS)
    if card_id in ELECTRIC_BUFFS:
        allowed.add("BATTLECRY")
    if card_id in (set(RUNIC_RINGS) | set(HOPEBRINGER_BUFFS) | set(HUMMING_BIRD_BUFFS)
                   | set(PAPER_DRAKE_TARGETS) | set(EVOKER_BUFFS) | set(AMBER_TARGETS) | set(BOOM_REPEATS)):
        allowed.add("START_OF_COMBAT")
    if card_id in DEATHRATTLE_SUMMONS or card_id in MUMMIFIER_TARGETS:
        allowed.add("DEATHRATTLE")
    if card_id in TITUS_EXTRAS or card_id in ETERNAL_KNIGHT_BUFFS:
        allowed.add("AURA")
    if card_id in ETERNAL_KNIGHT_BUFFS:
        allowed.add("InvisibleDeathrattle")
    if card_id in HAND_GEM_ONLY:
        allowed.add("AURA")
    if card_id in set(BONKER_GEMS) | set(VINEWEAVER_GEMS) | set(SANGUINE_REFINER_GEMS):
        allowed.add("BACON_RALLY")
    if card_id in {"BG32_324", "BG32_324_G"}:
        allowed.add("AVENGE")  # produces a later Recruit-phase spell, not combat state
    return allowed


def _allowed_effects(card_id: str) -> set[str]:
    allowed = set(GENERIC_EFFECTS)
    if card_id in DEATHRATTLE_SUMMONS or card_id in MUMMIFIER_TARGETS:
        allowed.add("DEATHRATTLE")
    if card_id in TITUS_EXTRAS or card_id in ETERNAL_KNIGHT_BUFFS:
        allowed.add("AURA")
    if card_id in HAND_GEM_ONLY:
        allowed.add("AURA")
    return allowed


def modelled_effects(board: list[MinionStats], cards: CardsDatabase) -> tuple[str, ...]:
    ids = {m.card_id for m in board}
    effects = ["Vanilla attack order, Taunt, Divine Shield, Poisonous/Venomous, Windfury/Reborn",
               "Cleave, Mega Windfury, immunity/untargetability and board positions"]
    if ids & set(OBSERVED_STAT_CARD_IDS): effects.append("Observed retained stats / tavern-only effects")
    if ids & set(ELECTRIC_BUFFS): effects.append("Electric Synthesizer Start of Combat Dragon buffs")
    if ids & set(RUNIC_RINGS): effects.append("Runic Arcanist Shiny Ring casts")
    if ids & set(RECRUITER_BUFFS): effects.append("Roaring Recruiter Dragon-attack buffs")
    if ids & set(MUMMIFIER_TARGETS): effects.append("Mummifier Deathrattle Reborn grants")
    if ids & set(HOPEBRINGER_BUFFS): effects.append("Hopebringer logged Start of Combat board buff")
    if ids & set(ETERNAL_KNIGHT_BUFFS): effects.append("Eternal Knight in-combat death increments")
    if ids & set(HUMMING_BIRD_BUFFS): effects.append("Humming Bird Beast combat attack aura")
    if ids & set(PAPER_DRAKE_TARGETS): effects.append("Thousandth Paper Drake left-most Dragon targeting")
    if ids & set(EVOKER_BUFFS): effects.append("Fire-forged Evoker Dragon Start of Combat buffs")
    if ids & set(AMBER_TARGETS): effects.append("Amber Guardian random other-Dragon shield buffs")
    if ids & set(BOOM_REPEATS): effects.append("Boom-in-a-Box Start of Combat board damage")
    if ids & set(DEATHRATTLE_SUMMONS): effects.append("Audited fixed-token Deathrattle summon chains")
    if ids & set(TITUS_EXTRAS): effects.append("Titus Rivendare repeated Deathrattles")
    if ids & set(BONKER_GEMS): effects.append("Bonker Rally Blood-Gem board buffs")
    if ids & set(VINEWEAVER_GEMS): effects.append("Razorfen Vineweaver Rally permanent Blood Gems")
    if ids & set(SANGUINE_REFINER_GEMS): effects.append("Sanguine Refiner Rally Blood-Gem size increases")
    if ids & HAND_GEM_ONLY: effects.append("Hot-Air Surveyor hand-only Blood-Gem effect excluded from combat")
    return tuple(effects)


def coverage(board: list[MinionStats], cards: CardsDatabase) -> list[str]:
    blockers = []
    for m in board:
        card = cards.get(m.card_id)
        name = m.name or (card.name if card else m.card_id)
        if m.attack is None or m.health is None or m.attack < 0 or m.health <= 0:
            blockers.append(f"{name}: missing/invalid current stats")
        if card is None:
            blockers.append(f"{name}: card reference missing")
            continue
        if card.card_type != "MINION": blockers.append(f"{name}: not a minion in the card reference")
        if card.card_id in set(BONKER_GEMS) | set(VINEWEAVER_GEMS) | set(SANGUINE_REFINER_GEMS):
            logged = dict(m.script_data)
            if "BLOOD_GEM_ATTACK" not in logged or "BLOOD_GEM_HEALTH" not in logged:
                blockers.append(f"{name}: Blood-Gem size was not logged for this board")
        unsupported = ((set(m.keywords) - SUPPORTED)
                       | (set(m.effects) - TRANSIENT_EFFECTS - SUPPORTED - _allowed_effects(card.card_id))
                       | (set(card.mechanics) - SUPPORTED - _allowed_mechanics(card.card_id)))
        if unsupported: blockers.append(f"{name}: unsupported {', '.join(sorted(unsupported))}")
        if card.card_id not in SAFE_TEXT_CARD_IDS:
            text = re.sub(r"<[^>]*>", "", card.text).lower()
            text = re.sub(r"\b(taunt|divine shield|poisonous|venomous|windfury|reborn)\b", "", text)
            if re.sub(r"[\s.,;!]+", "", text): blockers.append(f"{name}: card text has unimplemented effects")
    return list(dict.fromkeys(blockers))


def model_key(friendly: list[MinionStats], enemy: list[MinionStats], cards: CardsDatabase,
              tiers: tuple[int | None, int | None], board_only: bool, opponent_age: int = 0,
              allow_baseline: bool = False) -> str:
    payload = ([asdict(m) for m in friendly], [asdict(m) for m in enemy],
               [cards.as_dict(m.card_id) for m in friendly + enemy], tiers, board_only, opponent_age, allow_baseline)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def first_attacker(friendly: list[MinionStats], enemy: list[MinionStats]) -> str:
    if len(friendly) > len(enemy): return "Friendly board attacks first (more minions)."
    if len(enemy) > len(friendly): return "Opponent board attacks first (more minions)."
    return "First attacker is a 50/50 random choice (equal minion counts)."


def _hit(target: Unit, damage: int, lethal: bool, attacking: bool = False) -> bool:
    """Return true only if health damage occurs; shields/immune do not spend Venomous."""
    if damage <= 0 or "IMMUNE" in target.effects or (attacking and "IMMUNE_WHILE_ATTACKING" in target.effects): return False
    if "DIVINE_SHIELD" in target.keywords:
        target.keywords.remove("DIVINE_SHIELD")
        return False
    target.health = 0 if lethal else target.health - damage
    return True


def _apply_start_of_combat(sides: list[list[Unit]], rng: random.Random | None = None) -> list[list[Unit]]:
    rng = rng or random.Random()
    for side in sides:
        for source in list(side):
            buff = ELECTRIC_BUFFS.get(source.card_id)
            if buff:
                for target in side:
                    if target is not source and "DRAGON" in target.races: target.attack += buff[0]; target.health += buff[1]
        for source in list(side):
            if source.card_id in HUMMING_BIRD_BUFFS:
                for target in side:
                    if "BEAST" in target.races: target.attack += HUMMING_BIRD_BUFFS[source.card_id]
            rings = RUNIC_RINGS.get(source.card_id, 0)
            if rings:
                for target in side: target.attack += rings; target.health += rings
            default = HOPEBRINGER_BUFFS.get(source.card_id)
            if default:
                buff = (source.script_data.get("TAG_SCRIPT_DATA_NUM_1", default[0]), source.script_data.get("TAG_SCRIPT_DATA_NUM_2", default[1]))
                for target in side: target.attack += buff[0]; target.health += buff[1]
            buff = EVOKER_BUFFS.get(source.card_id)
            if buff:
                for target in side:
                    if "DRAGON" in target.races: target.attack += buff[0]; target.health += buff[1]
            count = AMBER_TARGETS.get(source.card_id, 0)
            if count:
                choices = [target for target in side if target is not source and "DRAGON" in target.races]
                for target in rng.sample(choices, min(count, len(choices))):
                    target.attack += 2; target.health += 2; target.keywords.add("DIVINE_SHIELD")
            count = PAPER_DRAKE_TARGETS.get(source.card_id, 0)
            if count:
                dragons = [target for target in sorted(side, key=lambda u: u.position) if "DRAGON" in target.races]
                for target in dragons[:count]: target.attack += 1; target.health += 2; target.keywords.add("WINDFURY")
    # Boom resolves after the listed board-start buffs. It is explicit and deterministic
    # within each board; deaths are then resolved before normal attack order.
    for side in sides:
        for source in list(side):
            for _ in range(BOOM_REPEATS.get(source.card_id, 0)):
                for group in sides:
                    for target in list(group):
                        if target is not source: _hit(target, 3, False)
        sides = _resolve_deaths(sides, rng)
    return sides


def _before_attack(side: list[Unit], attacker: Unit) -> None:
    if "DRAGON" in attacker.races:
        for source in side:
            buff = RECRUITER_BUFFS.get(source.card_id)
            if buff and source is not attacker: attacker.attack += buff[0]; attacker.health += buff[1]


def _gem_size(side: list[Unit]) -> list[int]:
    """Read parser-frozen gem stats; legacy/test boards correctly fall back to +1/+1."""
    for unit in side:
        attack = unit.script_data.get("BLOOD_GEM_ATTACK")
        health = unit.script_data.get("BLOOD_GEM_HEALTH")
        if isinstance(attack, int) and isinstance(health, int) and attack >= 0 and health >= 0:
            return [attack, health]
    return [1, 1]


def _apply_gems(target: Unit, gems: list[int], count: int) -> None:
    target.attack += gems[0] * count
    target.health += gems[1] * count


def _after_attack(side: list[Unit], attacker: Unit, gems: list[int]) -> None:
    """Apply audited Rally effects after each attack using current logged gem size."""
    count = BONKER_GEMS.get(attacker.card_id, 0)
    if count:
        for target in side:
            if target is not attacker and target.health > 0:
                _apply_gems(target, gems, count)
    count = VINEWEAVER_GEMS.get(attacker.card_id, 0)
    if count:
        count = attacker.script_data.get("TAG_SCRIPT_DATA_NUM_1", count)
        _apply_gems(attacker, gems, count)
    bonus = SANGUINE_REFINER_GEMS.get(attacker.card_id)
    if bonus:
        gems[0] += attacker.script_data.get("TAG_SCRIPT_DATA_NUM_1", bonus[0])
        gems[1] += attacker.script_data.get("TAG_SCRIPT_DATA_NUM_2", bonus[1])


def _deathrattle_multiplier(live: list[Unit]) -> int:
    return 1 + sum(TITUS_EXTRAS.get(unit.card_id, 0) for unit in live)


def _spawn(live: list[Unit], fallen: Unit, spec: tuple[int, int, int, set[str], bool, str], multiplier: int) -> None:
    count, attack, health, races, reborn, card_id = spec
    slot = 0
    for _ in range(count * multiplier):
        if len(live) >= 7: break
        slot += 1
        live.append(Unit(fallen.position + slot / 100, attack, health, set(), fallen.tier, card_id, set(races), reborn))


def _resolve_deaths(sides: list[list[Unit]], rng: random.Random) -> list[list[Unit]]:
    """Resolve fixed output Deathrattles, Auras and Reborn with the seven-minion cap."""
    resolved = []
    for side in sides:
        dead = [unit for unit in side if unit.health <= 0]
        live = [unit for unit in side if unit.health > 0]
        multiplier = _deathrattle_multiplier(live)
        for fallen in dead:
            if fallen.card_id in ETERNAL_KNIGHT_BUFFS:
                for knight in live:
                    buff = ETERNAL_KNIGHT_BUFFS.get(knight.card_id)
                    if buff: knight.attack += buff[0]; knight.health += buff[1]
        for fallen in dead:
            target_count = MUMMIFIER_TARGETS.get(fallen.card_id, 0)
            if target_count:
                candidates = [unit for unit in live if "UNDEAD" in unit.races and not unit.reborn]
                for target in rng.sample(candidates, min(target_count * multiplier, len(candidates))): target.reborn = True
            spec = DEATHRATTLE_SUMMONS.get(fallen.card_id)
            if spec: _spawn(live, fallen, spec, multiplier)
            # Turquoise Skitterer buffs only the Beetles it has made permanent; this
            # pre-combat amount is already logged, while its new fixed token gains it here.
            if fallen.card_id in {"BG31_809", "BG31_809_G"}:
                bonus = 5 if fallen.card_id == "BG31_809" else 10
                for token in live:
                    if token.card_id == "BG31_801_TOKEN": token.attack += bonus; token.health += bonus
        for fallen in dead:
            if fallen.reborn and len(live) < 7:
                returned = copy.deepcopy(fallen)
                returned.health, returned.reborn = 1, False
                returned.position += .005
                live.append(returned)
        resolved.append(sorted(live, key=lambda unit: unit.position))
    return resolved


def _targets(enemy: list[Unit], defender: Unit, cleave: bool) -> list[Unit]:
    if not cleave: return [defender]
    index = enemy.index(defender)
    return enemy[max(0, index-1):min(len(enemy), index+2)]


def fight(initial: list[list[Unit]], rng: random.Random,
          cancelled: Callable[[], bool] | None = None) -> tuple[int, list[Unit]] | None:
    sides = _apply_start_of_combat(copy.deepcopy(initial), rng)
    gems = [_gem_size(side) for side in sides]
    side = 0 if len(sides[0]) > len(sides[1]) else 1 if len(sides[1]) > len(sides[0]) else rng.randrange(2)
    cursors = [0.0, 0.0]
    for step in range(1500):
        # A log can reveal a newer board while an older, high-trigger fight is
        # still resolving. Stop inside the attack loop, not only between trials.
        if step % 25 == 0 and cancelled and cancelled():
            return None
        if not sides[0] or not sides[1]: break
        if not any(m.attack > 0 for group in sides for m in group): return 0, []
        eligible = [m for m in sides[side] if m.attack > 0]
        if not eligible: side = 1-side; continue
        attacker = next((m for m in eligible if m.position >= cursors[side]), eligible[0])
        cursors[side] = attacker.position + .001
        attacker.effects.discard("STEALTH")
        _before_attack(sides[side], attacker)
        attacks = 4 if "MEGA_WINDFURY" in attacker.effects else 2 if "WINDFURY" in attacker.keywords else 1
        for _ in range(attacks):
            if attacker not in sides[side] or not sides[1-side]: break
            targetable = [m for m in sides[1-side] if "CANT_BE_ATTACKED" not in m.effects and "STEALTH" not in m.effects]
            targets = [m for m in targetable if "TAUNT" in m.keywords] or targetable
            if not targets: break
            defender = rng.choice(targets)
            lethal = bool(attacker.keywords & {"VENOMOUS", "POISONOUS"})
            retaliation = bool(defender.keywords & {"VENOMOUS", "POISONOUS"})
            dealt = False
            for target in _targets(sides[1-side], defender, "CLEAVE" in attacker.effects):
                dealt = _hit(target, attacker.attack, lethal) or dealt
            taken = _hit(attacker, defender.attack, retaliation, attacking=True)
            if dealt: attacker.keywords.discard("VENOMOUS")
            if taken: defender.keywords.discard("VENOMOUS")
            _after_attack(sides[side], attacker, gems[side])
            sides = _resolve_deaths(sides, rng)
        side = 1-side
    else:
        raise RuntimeError("Simulation attack limit reached; no odds published")
    if sides[0] and not sides[1]: return 1, sides[0]
    if sides[1] and not sides[0]: return -1, sides[1]
    return 0, []


def _units(board: list[MinionStats], cards: CardsDatabase) -> list[Unit]:
    units = []
    for index, minion in enumerate(board):
        card = cards.get(minion.card_id)
        units.append(Unit(index, minion.attack, minion.health, set(minion.keywords) - {"REBORN"}, card.tier,
                          minion.card_id, set(card.races), "REBORN" in minion.keywords,
                          dict(minion.script_data), set(minion.effects)))
    return units


def _confidence(age: int) -> str:
    return "High" if age <= 0 else "Medium" if age == 1 else "Low"


def _half_width(win: float, trials: int) -> float:
    return 1.96 * ((max(0.000001, win * (1-win)) / max(1, trials)) ** .5)


def simulate(friendly: list[MinionStats], enemy: list[MinionStats], cards: CardsDatabase,
             tiers: tuple[int | None, int | None] = (None, None), trials: int | None = None,
             seed: int | None = None, board_only: bool = False,
             cancelled: Callable[[], bool] | None = None, opponent_age: int = 0,
             _sensitivity: bool = True, allow_baseline: bool = False) -> CombatReport:
    key = model_key(friendly, enemy, cards, tiers, board_only, opponent_age, allow_baseline)
    blockers = coverage(friendly + enemy, cards)
    if not friendly or not enemy: blockers.append("Need two nonempty, observed boards")
    if len(friendly) > 7 or len(enemy) > 7: blockers.append("Boards exceed the supported 7-minion limit")
    if not board_only: blockers.append("Automatic board-only estimate is disabled in Settings")
    modelled = modelled_effects(friendly + enemy, cards)
    opener = first_attacker(friendly, enemy) if friendly and enemy else ""
    fatal_markers = ("missing/invalid", "card reference missing", "not a minion", "Need two nonempty",
                     "Boards exceed", "Automatic board-only estimate is disabled")
    fatal = [blocker for blocker in blockers if any(marker in blocker for marker in fatal_markers)]
    if fatal or (blockers and not allow_baseline):
        return CombatReport(key, "Odds unavailable", blockers=tuple(blockers), modelled=modelled, first_attacker=opener)
    baseline = bool(blockers)
    if baseline:
        modelled = (*modelled, "Incomplete baseline: logged stats and generic combat rules only")
    adaptive = trials is None
    if trials is not None and not 1 <= trials <= 100000: raise ValueError("Trials must be 1–100000")
    minimum, maximum = (800, 6000) if adaptive else (trials, trials)
    units = [_units(friendly, cards), _units(enemy, cards)]
    rng, counts = random.Random(seed), {1: 0, -1: 0, 0: 0}
    damage: dict[int, list[int]] = {1: [], -1: []}
    damage_known = all(m.tier is not None for group in units for m in group) and all(t is not None for t in tiers)
    completed = 0
    while completed < maximum:
        if cancelled and cancelled(): return CombatReport(key, "Superseded simulation", modelled=modelled, first_attacker=opener)
        result = fight(units, rng, cancelled)
        if result is None: return CombatReport(key, "Superseded simulation", modelled=modelled, first_attacker=opener)
        outcome, survivors = result
        counts[outcome] += 1; completed += 1
        if outcome and damage_known:
            tier = tiers[0 if outcome == 1 else 1]
            damage[outcome].append(tier + sum(max(1, m.tier) for m in survivors))
        if adaptive and completed >= minimum and completed % 100 == 0 and _half_width(counts[1]/completed, completed) <= .015: break
    def bounds(values: list[int]) -> tuple[int, int] | None: return (min(values), max(values)) if values else None
    win = counts[1] / completed
    half = _half_width(win, completed)
    scenario = None
    scenario_detail = ""
    if _sensitivity and opponent_age > 0 and len(enemy) < 7:
        ordered = sorted(enemy, key=lambda m: ((m.attack or 0) + (m.health or 0), m.card_id))
        median = ordered[len(ordered)//2]
        extra = MinionStats("scenario-observed-median", median.card_id, median.name, median.attack, median.health,
                            median.max_health, median.keywords, median.effects, median.script_data)
        changed = simulate(friendly, enemy + [extra], cards, tiers, min(1000, completed), seed, True,
                           cancelled, 0, False, allow_baseline)
        if changed.trials:
            scenario = (min(win, changed.win), max(win, changed.win))
            scenario_detail = "Sensitivity only: unchanged board versus one extra minion with observed-board median stats; not a hidden-board prediction."
    note = "Incomplete baseline: unmodelled observed effects are excluded; this result can be biased." if baseline else "Board-only estimate; hero/trinket/quest/spell effects excluded."
    note += " Damage is conditional on winning/losing, before caps and armor; sampled ranges, not guarantees."
    note += f" {_confidence(opponent_age)} confidence: opponent observation is {opponent_age} round{'s' if opponent_age != 1 else ''} old."
    if adaptive: note += " Adaptive simulation stopped when the 95% win interval was narrow enough, or at 6,000 trials."
    if not damage_known: note += " Damage unavailable: one or more tiers are unknown."
    return CombatReport(key, note, completed, win, counts[-1]/completed, counts[0]/completed,
                        bounds(damage[1]), bounds(damage[-1]), tuple(blockers), modelled, opener,
                        (max(0., win-half), min(1., win+half)), half, _confidence(opponent_age), scenario, scenario_detail, baseline)


class CombatWorker:
    """Latest-only background work; replacement boards cancel stale simulations."""
    def __init__(self, on_result: Callable[[CombatReport], None]) -> None:
        self.on_result = on_result; self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._stop = threading.Event(); self._generation = 0; self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="combat-model", daemon=True); self._thread.start()

    def submit(self, friendly, enemy, cards, tiers, board_only, opponent_age: int = 0,
               allow_baseline: bool = False) -> str:
        with self._lock:
            self._generation += 1; generation = self._generation
        try: self._queue.get_nowait()
        except queue.Empty: pass
        self._queue.put_nowait((generation, friendly, enemy, cards, tiers, board_only, opponent_age, allow_baseline))
        return model_key(friendly, enemy, cards, tiers, board_only, opponent_age, allow_baseline)

    def _run(self) -> None:
        while not self._stop.is_set():
            try: generation, friendly, enemy, cards, tiers, board_only, age, allow_baseline = self._queue.get(timeout=.2)
            except queue.Empty: continue
            cancelled = lambda: self._stop.is_set() or generation != self._generation
            try:
                quick = simulate(friendly, enemy, cards, tiers, trials=100, board_only=board_only,
                                 cancelled=cancelled, opponent_age=age, _sensitivity=False,
                                 allow_baseline=allow_baseline)
                if not quick.trials:
                    if not cancelled(): self.on_result(quick)
                    continue
                if not cancelled(): self.on_result(replace(quick, stage="quick"))
                if cancelled(): continue
                report = simulate(friendly, enemy, cards, tiers, board_only=board_only, cancelled=cancelled,
                                  opponent_age=age, allow_baseline=allow_baseline)
            except Exception as exc:
                report = CombatReport(model_key(friendly, enemy, cards, tiers, board_only, age, allow_baseline), f"Simulation failed: {exc}")
            if not cancelled(): self.on_result(report)

    def close(self) -> None:
        self._stop.set(); self._thread.join(timeout=2)
