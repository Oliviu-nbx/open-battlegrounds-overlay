"""Reproducible synthetic log stream. Training cards are never cached or uploaded."""
from __future__ import annotations
import threading
from cards_db import Card
from parser import BattlegroundsParser

TRAINING_CARDS = [
    Card("DEMO_HERO", "Training hero", None, None, None, "Neutral", card_type="HERO"),
    Card("DEMO_BEAST", "Training beast", 2, 6, 5, "BEAST", races=("BEAST",)),
    Card("DEMO_GUARD", "Training guard", 2, 3, 6, "BEAST", "<b>Taunt</b>", ("TAUNT",), races=("BEAST",)),
    Card("DEMO_SHIELD", "Training shield", 2, 4, 3, "MECHANICAL", "<b>Divine Shield</b>", ("DIVINE_SHIELD",), races=("MECHANICAL",)),
]


def setup_lines() -> list[str]:
    lines = ["CREATE_GAME", "GameType=GT_BATTLEGROUNDS", "GameEntity EntityID=1",
             "tag=CARDTYPE value=GAME", "tag=TURN value=5",
             "Player EntityID=8 PlayerID=1", "tag=CARDTYPE value=PLAYER",
             "tag=TURN value=3", "tag=PLAYER_TECH_LEVEL value=2",
             "tag=RESOURCES value=7", "tag=RESOURCES_USED value=0",
             "tag=NEXT_OPPONENT_PLAYER_ID value=2"]
    def entity(identity, card, kind, controller, **tags):
        lines.extend([f"FULL_ENTITY - Creating ID={identity} CardID={card}",
                      f"tag=CARDTYPE value={kind}", f"tag=CONTROLLER value={controller}", "tag=ZONE value=PLAY"])
        lines.extend(f"tag={key} value={value}" for key, value in tags.items())
    entity(10, "DEMO_HERO", "HERO", 1, HEALTH=30, ARMOR=5)
    entity(20, "DEMO_BEAST", "MINION", 1, ATK=6, HEALTH=5, ZONE_POSITION=1)
    entity(21, "DEMO_GUARD", "MINION", 1, ATK=3, HEALTH=6, ZONE_POSITION=2, TAUNT=1)
    entity(30, "DEMO_SHIELD", "MINION", 2, ATK=4, HEALTH=3, ZONE_POSITION=1, DIVINE_SHIELD=1)
    entity(31, "DEMO_BEAST", "MINION", 2, ATK=5, HEALTH=4, ZONE_POSITION=2)
    entity(32, "DEMO_HERO", "HERO", 2, PLAYER_TECH_LEVEL=2, HEALTH=30)
    entity(50, "TB_BaconShopTechUp03_Button", "GAME_MODE_BUTTON", 1, COST=5)
    entity(51, "TB_BaconShop_8p_Reroll_Button", "GAME_MODE_BUTTON", 1, COST=1)
    entity(52, "TB_BaconShop_DragBuy", "MOVE_MINION_HOVER_TARGET", 1, COST=3)
    return lines


def run_demo(parser: BattlegroundsParser, stopped: threading.Event) -> None:
    parser.set_stream_status("Demo — synthetic training cards; no game config or persistent history writes")
    for line in setup_lines():
        parser.consume(line)
    parser.flush()
    stages = [
        ["TAG_CHANGE Entity=GameEntity tag=TURN value=6", "BLOCK_START BlockType=ATTACK Entity=20"],
        ["TAG_CHANGE Entity=20 tag=DAMAGE value=2", "TAG_CHANGE Entity=30 tag=ZONE value=GRAVEYARD"],
        ["TAG_CHANGE Entity=GameEntity tag=TURN value=7", "TAG_CHANGE Entity=8 tag=TURN value=4",
         "TAG_CHANGE Entity=8 tag=RESOURCES value=8", "TAG_CHANGE Entity=20 tag=DAMAGE value=0",
         "TAG_CHANGE Entity=30 tag=ZONE value=PLAY"],
        ["TAG_CHANGE Entity=8 tag=PLAYER_LEADERBOARD_PLACE value=2",
         "TAG_CHANGE Entity=8 tag=PLAYSTATE value=LOST"],
    ]
    for stage in stages:
        if stopped.wait(4):
            return
        for line in stage:
            parser.consume(line)
        parser.flush()
