"""Non-locking Power.log reader and entity-based Battlegrounds parser."""
from __future__ import annotations

import copy
import hashlib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ID = re.compile(r"\b(?:id|EntityID|Entity)=(\d+)", re.I)
CARD = re.compile(r"\bcardId=([^\s\]]*)", re.I)
CREATE = re.compile(r"\b(?:FULL_ENTITY|SHOW_ENTITY)\b", re.I)
TRANSFORM = re.compile(r"\bCHANGE_ENTITY\b")
CHANGE = re.compile(r"TAG_CHANGE\s+Entity=(.*?)\s+tag=(\w+)\s+value=(\S+)")
TAG = re.compile(r"^tag=(\w+)\s+value=(\S+)")
PLAYER = re.compile(r"Player\s+EntityID=(\d+)\s+PlayerID=(\d+)")
PLAYER_INFO = re.compile(r"PlayerID=(\d+),\s+PlayerName=(.+)")


def number(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


@dataclass(frozen=True)
class MinionStats:
    entity_id: str
    card_id: str
    name: str
    attack: int | None
    health: int | None
    max_health: int | None
    keywords: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    script_data: tuple[tuple[str, int], ...] = ()


@dataclass
class Entity:
    entity_id: str
    card_id: str = ""
    name: str = ""
    zone: str = ""
    controller: str = ""
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def is_minion(self) -> bool:
        kind = self.tags.get("CARDTYPE", "")
        return kind in {"MINION", "4"} or (
            not kind and self.card_id.startswith("BG") and "HERO" not in self.card_id
            and "ATK" in self.tags and "HEALTH" in self.tags
        )


@dataclass
class BattlegroundsState:
    active: bool = False
    turn: int = 0
    tavern_tier: int = 1
    health: int | None = None
    armor: int | None = None
    hero_card_id: str = ""
    local_player: str = ""
    in_combat: bool = False
    entities: dict[str, Entity] = field(default_factory=dict)
    shop: list[str] = field(default_factory=list)
    board: list[str] = field(default_factory=list)
    opponent_boards: dict[str, list[str]] = field(default_factory=dict)
    known_boards: dict[str, list[str]] = field(default_factory=dict)
    status: str = "Waiting for Battlegrounds…"
    stream_status: str = "Looking for Power.log…"
    round: int = 0
    gold: int | None = None
    player_name: str = ""
    next_opponent: str = ""
    board_stats: list[MinionStats] = field(default_factory=list)
    shop_stats: list[MinionStats] = field(default_factory=list)
    hand_stats: list[MinionStats] = field(default_factory=list)
    opponent_stats: dict[str, list[MinionStats]] = field(default_factory=dict)
    opponent_rounds: dict[str, int] = field(default_factory=dict)
    board_attack: int | None = None
    board_health: int | None = None
    log_capped: bool = False
    game_id: str = ""
    result: str = ""
    placement: int | None = None
    action_costs: dict[str, int] = field(default_factory=dict)
    opponent_heroes: dict[str, str] = field(default_factory=dict)
    opponent_tiers: dict[str, int] = field(default_factory=dict)
    combat_board: list[MinionStats] = field(default_factory=list)
    combat_round: int = 0
    combat_opponent: str = ""
    combat_outcome: str = ""
    combat_outcome_round: int = 0
    context_effects: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        """Compact diagnostics; raw entity/account records stay out of reports."""
        from dataclasses import asdict
        fields = ("active", "local_player", "hero_card_id", "round", "turn", "tavern_tier",
                  "health", "armor", "gold", "in_combat", "next_opponent", "board_attack",
                  "board_health", "log_capped", "stream_status", "game_id", "result",
                  "placement", "action_costs", "opponent_heroes", "opponent_tiers",
                  "combat_outcome", "combat_outcome_round")
        output = {name: getattr(self, name) for name in fields}
        output["board"] = [asdict(card) for card in self.board_stats]
        output["shop"] = [asdict(card) for card in self.shop_stats]
        output["hand"] = [asdict(card) for card in self.hand_stats]
        output["opponents"] = {key: [asdict(card) for card in cards]
                               for key, cards in self.opponent_stats.items()}
        return output


class PowerLogTailer:
    """Replay existing contents and follow complete lines through rotation.

    A directory supports Logs/<session>/Power.log. Partial UTF-8 lines stay
    buffered until the game finishes writing them. No file is locked.
    """
    def __init__(self, path: Path, on_line: Callable[[str], None],
                 interval: float = .25, on_status: Callable[[str], None] | None = None,
                 on_reset: Callable[[], None] | None = None,
                 on_idle: Callable[[], None] | None = None,
                 on_stream: Callable[[Path], None] | None = None) -> None:
        self.path = Path(path)
        self.on_line, self.on_status, self.on_reset = on_line, on_status, on_reset
        self.interval = interval
        self.on_idle = on_idle
        self.on_stream = on_stream
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_status = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="power-log", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _status(self, message: str) -> None:
        if message != self._last_status:
            self._last_status = message
            logging.info(message)
            if self.on_status:
                self.on_status(message)

    def _resolve(self) -> Path:
        if self.path.suffix.lower() == ".log":
            return self.path
        candidates = []
        # Explicit directory reads surface access errors that glob may suppress.
        entries = list(self.path.iterdir())
        paths = [self.path / "Power.log"]
        for entry in entries:
            if entry.is_dir():
                paths.append(entry / "Power.log")
        for candidate in paths:
            try:
                candidates.append((candidate.stat().st_mtime_ns, str(candidate), candidate))
            except FileNotFoundError:
                continue
        if not candidates:
            raise FileNotFoundError(self.path)
        return max(candidates)[2]

    def _run(self) -> None:
        handle = None
        identity = None
        offset, pending, checkpoint = 0, b"", b""
        capped = False
        try:
            while not self._stop.is_set():
                try:
                    path = self._resolve()
                    stat = path.stat()
                    current = (path, stat.st_dev, stat.st_ino)
                    replaced = current != identity
                    truncated = stat.st_size < offset
                    if handle and not replaced and not truncated and checkpoint:
                        handle.seek(offset - len(checkpoint))
                        truncated = handle.read(len(checkpoint)) != checkpoint
                    if replaced or truncated:
                        if handle:
                            handle.close()
                        handle = None
                        offset, pending, checkpoint = 0, b"", b""
                        capped = False
                        identity = current
                        if self.on_reset:
                            self.on_reset()
                        if self.on_stream:
                            self.on_stream(path)
                    if handle is None:
                        handle = path.open("rb")
                    handle.seek(offset)
                    if not capped:
                        self._status(f"Connected: {path.parent.name}/Power.log")
                    chunk = handle.read(65536)
                    if chunk:
                        offset += len(chunk)
                        pending += chunk
                        lines = pending.split(b"\n")
                        pending = lines.pop()
                        for line in lines:
                            if self._stop.is_set():
                                break
                            decoded = line.rstrip(b"\r").decode("utf-8", errors="replace")
                            self.on_line(decoded)
                            if "Truncating log, which has reached the size limit" in decoded:
                                capped = True
                                self._status("Logging stopped at size limit — restart Hearthstone.")
                        handle.seek(max(0, offset - 128))
                        checkpoint = handle.read(min(128, offset))
                        continue
                    if self.on_idle:
                        self.on_idle()
                except FileNotFoundError:
                    self._status(f"Waiting for Power.log in {self.path}")
                except PermissionError:
                    self._status("Log access denied — check macOS privacy/file permissions.")
                except OSError as exc:
                    self._status(f"Log read error (retrying): {exc}")
                except Exception as exc:
                    logging.exception("Log callback failed")
                    self._status(f"Parser error: {exc}")
                else:
                    self._stop.wait(self.interval)
                    continue
                if handle:
                    handle.close()
                    handle = None
                self._stop.wait(self.interval)
        finally:
            if handle:
                handle.close()


class BattlegroundsParser:
    """Parse entity headers, inline references, and following indented tags.

    Unknown ownership is shown as observed controller boards. Health and tier
    are attributed only when the local controller is known.
    """
    def __init__(self, on_update: Callable[[BattlegroundsState], None],
                 local_player: str = "", publish_interval: float = 0) -> None:
        self.on_update = on_update
        self._local_player = local_player
        self.state = BattlegroundsState(local_player=local_player)
        self._current: Entity | None = None
        self._source = ""
        self._player_names: dict[str, str] = {}
        self._pending_choice = ""
        self._history: dict[str, list[MinionStats]] = {}
        self._combat_snapshot_taken = False
        self._publish_interval = publish_interval
        self._last_publish = 0.0
        self._dirty = False
        self._session_key = "unattached"
        self._match_number = 0

    def begin_stream(self, path: Path) -> None:
        """Stable replay identity prevents importing the same match twice."""
        self._session_key = str(path.resolve())
        self._match_number = 0
        self.reset()

    def _emit(self, force: bool = False) -> None:
        self._dirty = True
        now = time.monotonic()
        if not force and now - self._last_publish < self._publish_interval:
            return
        self._rebuild()
        # The UI needs summary fields, not thousands of raw entity tag records.
        snapshot = copy.copy(self.state)
        snapshot.entities = {}
        self.on_update(copy.deepcopy(snapshot))
        self._last_publish, self._dirty = now, False

    def flush(self) -> None:
        if self._dirty:
            self._emit(force=True)

    def reset(self) -> None:
        self.state = BattlegroundsState(local_player=self._local_player,
                                       stream_status=self.state.stream_status)
        self._current = None
        self._player_names = {}
        self._source = ""
        self._pending_choice = ""
        self._history = {}
        self._combat_snapshot_taken = False
        self._emit(force=True)

    def set_stream_status(self, message: str) -> None:
        self.state.stream_status = message
        self._emit(force=True)

    def _entity(self, target: str) -> Entity:
        match = ID.search(target)
        key = match.group(1) if match else target.strip()
        if not match and not key.isdigit():
            key = next((e.entity_id for e in self.state.entities.values()
                        if e.name == key), key)
        entity = self.state.entities.setdefault(key, Entity(key))
        card = CARD.search(target)
        if card and card.group(1):
            entity.card_id = card.group(1)
        name = re.search(r"(?:entityName|name)=(.*?)(?=\s+id=)", target, re.I)
        if name:
            entity.name = name.group(1)
        for prop, value in re.findall(r"\b(zone|player)=(\w+)", target, re.I):
            if prop.lower() == "zone" and not entity.zone:
                entity.zone = value.upper()
            elif prop.lower() == "player" and not entity.controller:
                entity.controller = value
        return entity

    def consume(self, line: str) -> None:
        # Both loggers repeat the same packets. Use one source per file/session.
        source = re.search(r"\b(GameState|PowerTaskList)\.DebugPrintPower\(\)", line)
        if source:
            if not self._source:
                self._source = source.group(1)
            if source.group(1) != self._source:
                return
        payload = re.sub(r"^.*?\(\)\s+-\s*", "", line).strip()
        if "Truncating log, which has reached the size limit" in payload:
            self.state.log_capped = True
            self.set_stream_status("Logging stopped at size limit — restart Hearthstone.")
            return
        if "CREATE_GAME" in payload:
            self._match_number += 1
            self.reset()
            identity = f"{self._session_key}|{self._match_number}|{line.strip()}"
            self.state.game_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        info = PLAYER_INFO.search(payload)
        if info:
            controller, name = info.groups()
            self._player_names[controller] = name.strip()
            for entity in self.state.entities.values():
                if entity.tags.get("CARDTYPE") in {"PLAYER", "2"} and entity.controller == controller:
                    entity.name = name.strip()
            self._emit()
            return
        # MULLIGAN choices are addressed to the client's player. Map the exact
        # name through DebugPrintGame metadata, rather than assuming player 1.
        if "DebugPrintEntityChoices" in line and "ChoiceType=MULLIGAN" in payload:
            choice = re.search(r"Player=(.*?)\s+TaskList=", payload)
            if choice:
                self._pending_choice = choice.group(1)
                if not self._local_player:
                    self.state.local_player = next((pid for pid, name in self._player_names.items()
                                                    if name == self._pending_choice), "")
                self._emit()
            return
        if self._pending_choice and "DebugPrintEntityChoices" in line and "Entities[" in payload:
            entity = self._entity(payload)
            if not self._local_player and entity.controller:
                self.state.local_player = entity.controller
            self._emit()
            return
        changed = False
        if "GT_BATTLEGROUNDS" in line:
            self.state.active = True
            self.state.status = "Battlegrounds detected"
            changed = True
        player = PLAYER.search(payload)
        if "GameEntity EntityID=" in payload:
            self._current = self._entity(payload)
            self._current.name = "GameEntity"
            changed = True
        elif player:
            entity = self._entity(player.group(1))
            entity.controller = player.group(2)
            entity.tags["CARDTYPE"] = "PLAYER"
            self._current = entity
            changed = True
        elif CREATE.search(payload) or TRANSFORM.search(payload):
            self._current = self._entity(payload)
            changed = True
        else:
            change = CHANGE.search(payload)
            tag = TAG.match(payload)
            if change:
                target, key, value = change.groups()
                self._current = None
                self._tag(self._entity(target), key, value)
                changed = True
            elif tag and self._current:
                self._tag(self._current, *tag.groups())
                changed = True
            else:
                self._current = None
        if "BLOCK_START" in payload and "BlockType=ATTACK" in payload:
            self._combat()
            self._capture_combat()
            changed = True
        if changed:
            self._emit()

    def _tag(self, entity: Entity, key: str, value: str) -> None:
        entity.tags[key] = value
        if key == "ZONE":
            entity.zone = {"1": "PLAY", "3": "HAND", "4": "GRAVEYARD"}.get(value, value)
        elif key == "CONTROLLER":
            entity.controller = value
        elif key in {"LOCAL_PLAYER", "IS_LOCAL_PLAYER"} and value in {"1", "TRUE"}:
            self.state.local_player = entity.controller or entity.tags.get("PLAYER_ID", "")
        elif key == "TURN" and value.isdigit():
            if entity.name == "GameEntity" or entity.entity_id == "GameEntity" or entity.tags.get("CARDTYPE") == "GAME":
                self.state.turn = int(value)
                if self.state.active:
                    self.state.round = (self.state.turn + 1) // 2
                    self.state.in_combat = self.state.turn > 0 and self.state.turn % 2 == 0
                    self._combat_snapshot_taken = False
                    self._emit(force=True)
            elif entity.controller == self.state.local_player:
                self.state.round = int(value)
                self._emit(force=True)
        elif key == "STEP":
            if value == "MAIN_COMBAT":
                self._combat()
                self._capture_combat()
            elif value in {"MAIN_ACTION", "MAIN_START", "MAIN_START_TRIGGERS"}:
                self._finish_combat()
                self.state.in_combat = False
                self._combat_snapshot_taken = False
        elif key == "PLAYSTATE" and value in {"WON", "LOST"}:
            if entity.entity_id == "GameEntity" or entity.name == "GameEntity" or (
                self.state.local_player and entity.controller == self.state.local_player
            ):
                self.state.status = f"Match {value.lower()}"
                self.state.active = False
                self.state.result = value
                self._emit(force=True)
        if key.startswith("BACON_") or entity.card_id.startswith(("BG", "TB_BaconShop")):
            if self.state.status.startswith("Waiting"):
                self.state.active = True
                self.state.status = "Battlegrounds hero observed"

    def _combat(self) -> None:
        if not self.state.in_combat:
            self.state.known_boards.update(self._boards())
        self.state.in_combat = True

    def _finish_combat(self) -> None:
        """Record a result only when the final logged combat board is unambiguous."""
        if not self.state.in_combat or not self.state.combat_round or not self.state.local_player:
            return
        opponent = self.state.combat_opponent
        if not opponent:
            return
        alive = lambda controller: [entity for entity in self.state.entities.values()
                                    if entity.zone == "PLAY" and entity.is_minion
                                    and entity.controller == controller
                                    and entity.tags.get("BACON_IS_SHOP_ENTITY") != "1"]
        friendly, enemy = alive(self.state.local_player), alive(opponent)
        if friendly and not enemy:
            outcome = "win"
        elif enemy and not friendly:
            outcome = "loss"
        elif not friendly and not enemy:
            outcome = "tie"
        else:
            # The post-combat log can already have restored boards. Do not guess.
            return
        self.state.combat_outcome, self.state.combat_outcome_round = outcome, self.state.combat_round

    @staticmethod
    def _stats(entity: Entity) -> MinionStats:
        tags = entity.tags
        maximum, damage = number(tags.get("HEALTH")), number(tags.get("DAMAGE")) or 0
        return MinionStats(entity.entity_id, entity.card_id, entity.name,
                           number(tags.get("ATK")), None if maximum is None else maximum - damage,
                           maximum, tuple(key for key in ("TAUNT", "DIVINE_SHIELD", "POISONOUS",
                                                          "VENOMOUS", "REBORN", "WINDFURY")
                                          if tags.get(key) == "1"),
                           # CANT_ATTACK is a current-turn readiness tag. It is set during
                           # the recruit phase and after attacks, then resets for combat;
                           # it is not a permanent Battlegrounds combat ability.
                           tuple(key for key in ("DEATHRATTLE", "AURA", "IMMUNE", "IMMUNE_WHILE_ATTACKING",
                                                  "CANT_BE_ATTACKED", "STEALTH", "MEGA_WINDFURY",
                                                  "CLEAVE", "EXTRA_DEATHRATTLES", "REBORN")
                                 if (number(tags.get(key)) or 0) > 0)
                           + (("NONSTANDARD_WINDFURY",) if (number(tags.get("WINDFURY")) or 0) > 1 else ()),
                           tuple((key, value) for key in ("TAG_SCRIPT_DATA_NUM_1", "TAG_SCRIPT_DATA_NUM_2")
                                 if (value := number(tags.get(key))) is not None))

    def _blood_gem_sizes(self) -> dict[str, tuple[int, int]]:
        """Read current player Blood-Gem parameters when the client logs them."""
        output = {}
        for entity in self.state.entities.values():
            if entity.card_id != "BG26_159pe" or not entity.controller or entity.zone == "REMOVEDFROMGAME":
                continue
            attack, health = number(entity.tags.get("TAG_SCRIPT_DATA_NUM_1")), number(entity.tags.get("TAG_SCRIPT_DATA_NUM_2"))
            if attack is not None and health is not None and attack >= 0 and health >= 0:
                output[entity.controller] = (attack, health)
        return output

    @staticmethod
    def _with_blood_gems(minions: list[MinionStats], size: tuple[int, int] | None) -> list[MinionStats]:
        if size is None:
            return list(minions)
        result = []
        for minion in minions:
            data = dict(minion.script_data)
            data.update(BLOOD_GEM_ATTACK=size[0], BLOOD_GEM_HEALTH=size[1])
            result.append(MinionStats(minion.entity_id, minion.card_id, minion.name, minion.attack,
                                      minion.health, minion.max_health, minion.keywords, minion.effects,
                                      tuple(sorted(data.items()))))
        return result

    def _capture_combat(self) -> None:
        """Capture once before damage, after combat entities have been revealed."""
        if self._combat_snapshot_taken:
            return
        self._rebuild()
        local = self.state.local_player
        opposing = [e for e in self.state.entities.values() if e.zone == "PLAY"
                    and e.is_minion and e.controller != local and e.card_id]
        opposing.sort(key=lambda e: number(e.tags.get("ZONE_POSITION")) or 0)
        if opposing and local:
            key = self.state.next_opponent or opposing[0].controller
            source_controller = opposing[0].controller
            gem_sizes = self._blood_gem_sizes()
            self._history[key] = self._with_blood_gems([self._stats(e) for e in opposing], gem_sizes.get(source_controller))
            # _rebuild() ran before this first combat snapshot existed. Publish it
            # immediately so the prediction worker can calculate this encounter,
            # rather than waiting until a later combat rebuild.
            self.state.opponent_stats = dict(self._history)
            self.state.opponent_rounds[key] = self.state.round
            self.state.combat_board = self._with_blood_gems(self.state.board_stats, gem_sizes.get(local))
            self.state.combat_round = self.state.round
            self.state.combat_opponent = key
            heroes = [e for e in self.state.entities.values() if e.zone == "PLAY"
                      and e.controller == source_controller and e.tags.get("CARDTYPE") in {"HERO", "3"}]
            if heroes:
                self.state.opponent_heroes[key] = heroes[0].card_id
                tier = number(heroes[0].tags.get("PLAYER_TECH_LEVEL"))
                if tier is not None:
                    self.state.opponent_tiers[key] = tier
            self._combat_snapshot_taken = True
            self._emit(force=True)

    def _boards(self) -> dict[str, list[str]]:
        boards: dict[str, list[str]] = {}
        entities = sorted(self.state.entities.values(),
                          key=lambda e: int(e.tags.get("ZONE_POSITION", "0"))
                          if e.tags.get("ZONE_POSITION", "0").isdigit() else 0)
        for entity in entities:
            if (entity.zone == "PLAY" and entity.is_minion and entity.card_id
                    and entity.controller and entity.tags.get("BACON_IS_SHOP_ENTITY") != "1"):
                boards.setdefault(entity.controller, []).append(entity.card_id)
        return boards

    def _rebuild(self) -> None:
        # The BG client exposes its human PLAYER plus BACON_DUMMY_PLAYER for
        # Bob/combat. Only infer ownership when that pattern is unambiguous.
        players = [e for e in self.state.entities.values() if e.tags.get("CARDTYPE") in {"PLAYER", "2"}]
        if not self.state.local_player and any(e.tags.get("BACON_DUMMY_PLAYER") == "1" for e in players):
            humans = [e for e in players if e.tags.get("BACON_DUMMY_PLAYER") != "1"]
            if len(humans) == 1:
                self.state.local_player = humans[0].controller
        local = self.state.local_player
        boards = self._boards()
        self.state.board = boards.get(local, []) if local else []
        self.state.shop = [e.card_id for e in self.state.entities.values()
                           if e.is_minion and e.tags.get("BACON_IS_SHOP_ENTITY") == "1"]
        observed = dict(boards)
        observed.update(self.state.known_boards)  # Combat deaths do not erase history.
        self.state.opponent_boards = {p: cards[:] for p, cards in observed.items() if p != local}
        if not local:
            return
        player = next((e for e in players if e.controller == local), None)
        self.state.player_name = self._player_names.get(local, "")
        heroes = [e for e in self.state.entities.values() if e.controller == local and e.zone == "PLAY"
                  and e.tags.get("CARDTYPE") in {"HERO", "3"}]
        hero = next((e for e in heroes if player and e.entity_id == player.tags.get("HERO_ENTITY")),
                    heroes[0] if heroes else None)
        player_tags = player.tags if player else {}
        hero_tags = hero.tags if hero else {}
        # A leaderboard position is not a final placement until PLAYSTATE ends.
        place = number(player_tags.get("PLAYER_LEADERBOARD_PLACE", hero_tags.get("PLAYER_LEADERBOARD_PLACE")))
        if self.state.result and place is not None and 1 <= place <= 8:
            self.state.placement = place
        tier = number(player_tags.get("PLAYER_TECH_LEVEL", hero_tags.get("PLAYER_TECH_LEVEL")))
        if tier is not None and 1 <= tier <= 7:
            self.state.tavern_tier = tier
        resources = number(player_tags.get("RESOURCES"))
        if resources is not None:
            self.state.gold = max(0, resources + (number(player_tags.get("TEMP_RESOURCES")) or 0)
                                  - (number(player_tags.get("RESOURCES_USED")) or 0))
        if player_tags.get("TURN", "").isdigit():
            self.state.round = max(int(player_tags["TURN"]), (self.state.turn + 1) // 2)
        self.state.next_opponent = player_tags.get("NEXT_OPPONENT_PLAYER_ID",
                                                  hero_tags.get("NEXT_OPPONENT_PLAYER_ID", self.state.next_opponent))
        if hero:
            self.state.hero_card_id = hero.card_id
            maximum = number(hero_tags.get("HEALTH"))
            if maximum is not None:
                self.state.health = maximum - (number(hero_tags.get("DAMAGE")) or 0)
            self.state.armor = number(hero_tags.get("ARMOR")) or 0
        minions = sorted((e for e in self.state.entities.values() if e.is_minion and e.card_id),
                         key=lambda e: number(e.tags.get("ZONE_POSITION")) or 0)
        self.state.board_stats = [self._stats(e) for e in minions if e.zone == "PLAY" and e.controller == local]
        self.state.hand_stats = [self._stats(e) for e in minions if e.zone == "HAND" and e.controller == local]
        self.state.shop_stats = [self._stats(e) for e in minions if e.zone == "PLAY" and e.controller != local] if not self.state.in_combat else []
        self.state.shop = [e.card_id for e in self.state.shop_stats]
        self.state.board = [e.card_id for e in self.state.board_stats]
        self.state.opponent_stats = dict(self._history)
        self.state.board_attack = sum(e.attack for e in self.state.board_stats) if all(e.attack is not None for e in self.state.board_stats) else None
        self.state.board_health = sum(e.health for e in self.state.board_stats) if all(e.health is not None for e in self.state.board_stats) else None
        buttons = [e for e in self.state.entities.values() if e.controller == local and e.zone == "PLAY"]
        costs = {}
        for entity in buttons:
            cost = number(entity.tags.get("COST"))
            if cost is None or cost < 0:
                continue
            card_id = entity.card_id
            if f"TechUp{self.state.tavern_tier + 1:02d}_Button" in card_id:
                costs["Upgrade"] = cost
            elif "Reroll_Button" in card_id:
                costs["Refresh"] = cost
            elif entity.tags.get("CARDTYPE") in {"HERO_POWER", "10"} and not any(
                part in card_id for part in ("DragBuy", "DragSell", "TechUp", "Reroll_Button", "LockAll_Button")
            ):
                costs["Hero power"] = cost
        buys = [number(e.tags.get("COST")) for e in buttons
                if "DragBuy" in e.card_id and "Spell" not in e.card_id]
        known_buys = {v for v in buys if v is not None and v >= 0}
        if len(known_buys) == 1:
            costs["Buy"] = known_buys.pop()
        self.state.action_costs = costs
        self.state.context_effects = sorted({e.card_id for e in buttons if e.card_id and
            e.tags.get("CARDTYPE") in {"HERO_POWER", "10", "BATTLEGROUND_TRINKET", "44",
                                       "BATTLEGROUND_QUEST_REWARD", "40", "BATTLEGROUND_ANOMALY", "43"}})
