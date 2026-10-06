"""Local, free HearthstoneJSON cache and Battlegrounds card lookup."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


CARDS_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"


@dataclass(frozen=True)
class Card:
    card_id: str
    name: str
    tier: int | None
    attack: int | None
    health: int | None
    minion_type: str
    text: str = ""
    mechanics: tuple[str, ...] = ()
    card_type: str = "MINION"
    races: tuple[str, ...] = ()
    dbf_id: int | None = None
    render_dbf_id: int | None = None
    is_golden: bool = False


class CardsDatabase:
    def __init__(self, data_dir: Path | str = "data", locale: str = "enUS") -> None:
        self.data_dir = Path(data_dir)
        if locale not in {"enUS", "deDE", "esES", "esMX", "frFR", "itIT", "jaJP", "koKR", "plPL", "ptBR", "ruRU", "thTH", "zhCN", "zhTW"}:
            raise ValueError("Unsupported HearthstoneJSON locale")
        self.locale = locale
        self.cache_path = self.data_dir / ("cards.json" if locale == "enUS" else f"cards.{locale}.json")
        self._index: dict[str, Card] = {}
        self._pool: set[str] = set()

    def refresh(self) -> int:
        """Download the public HearthstoneJSON card export and cache it locally."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        request = Request(CARDS_URL.replace("enUS", self.locale), headers={"User-Agent": "OpenBattlegroundsOverlay/1.0"})
        with urlopen(request, timeout=45) as response:
            payload = response.read()
        if not isinstance(json.loads(payload), list):
            raise ValueError("Card download is not a JSON array")
        temporary = self.cache_path.with_suffix(".download")
        temporary.write_bytes(payload)
        temporary.replace(self.cache_path)
        self.load()
        return len(self._index)

    def load(self) -> int:
        if not self.cache_path.exists():
            return 0
        raw: list[dict[str, Any]] = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self._index = {}
        self._pool = set()
        for value in raw:
            card_id = value.get("id", "")
            if card_id:
                card = self._to_card(value)
                self._index[card_id] = card
                if value.get("isBattlegroundsPoolMinion") and value.get("type") == "MINION":
                    self._pool.add(card_id)
        return len(self._index)

    @staticmethod
    def _to_card(value: dict[str, Any]) -> Card:
        # HearthstoneJSON fields have changed across game builds; accept variants.
        tier = value.get("techLevel") or value.get("battlegroundsTier") or value.get("tier")
        return Card(
            card_id=value["id"], name=value.get("name", value["id"]),
            tier=int(tier) if isinstance(tier, (int, float, str)) and str(tier).isdigit() else None,
            attack=value.get("attack"), health=value.get("health"),
            minion_type=" / ".join(value.get("races") or [value.get("race") or "Neutral"]),
            text=value.get("text", ""), mechanics=tuple(value.get("mechanics", [])),
            card_type=value.get("type", ""), races=tuple(value.get("races") or ([value["race"]] if value.get("race") else [])),
            dbf_id=value.get("dbfId"), render_dbf_id=value.get("battlegroundsNormalDbfId") or value.get("dbfId"),
            is_golden=bool(value.get("battlegroundsNormalDbfId")),
        )

    def add(self, cards: list[Card]) -> None:
        """Install explicitly supplied training/test cards; never writes the cache."""
        self._index.update({card.card_id: card for card in cards})
        self._pool.update(card.card_id for card in cards if card.card_type == "MINION" and card.tier is not None)

    def get(self, card_id: str) -> Card | None:
        return self._index.get(card_id)

    def by_tier(self, tier: int) -> list[Card]:
        return sorted((c for c in self._index.values() if c.tier == tier and c.card_id in self._pool), key=lambda c: (c.minion_type, c.name))

    def as_dict(self, card_id: str) -> dict[str, Any] | None:
        card = self.get(card_id)
        return asdict(card) if card else None
