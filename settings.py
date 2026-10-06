"""Small, validated local overlay preferences; corrupt files are recoverable."""
from __future__ import annotations

import json
import logging
from pathlib import Path

DEFAULTS = {"x": 30, "y": 100, "width": 440, "height": 720, "opacity": .96,
            "collapsed": ["hand", "opponents", "reference", "history", "decision"], "compact": False,
            "theme": "dark", "topmost": True, "reduce_transparency": False,
            "auto_combat_estimate": True, "game_overlay": False,
            "game_x": None, "game_y": None, "game_preset": "auto", "ui_version": 0}


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def load(self) -> dict:
        values = {**DEFAULTS, "collapsed": list(DEFAULTS["collapsed"])}
        if self.path:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("Settings are not an object")
                for key in ("x", "y", "width", "height", "game_x", "game_y"):
                    if type(raw.get(key)) is int:
                        values[key] = max(0, min(6000, raw[key]))
                opacity = raw.get("opacity")
                if type(opacity) in (int, float) and .45 <= opacity <= 1:
                    values["opacity"] = opacity
                if isinstance(raw.get("collapsed"), list):
                    values["collapsed"] = [v for v in raw["collapsed"] if isinstance(v, str)]
                if type(raw.get("compact")) is bool:
                    values["compact"] = raw["compact"]
                if raw.get("theme") in ("dark", "light"):
                    values["theme"] = raw["theme"]
                if raw.get("game_preset") in ("auto", "recruit", "combat", "minimal"):
                    values["game_preset"] = raw["game_preset"]
                for key in ("topmost", "reduce_transparency", "auto_combat_estimate", "game_overlay"):
                    if type(raw.get(key)) is bool:
                        values[key] = raw[key]
                if type(raw.get("ui_version")) is int and raw["ui_version"] >= 0:
                    values["ui_version"] = raw["ui_version"]
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as exc:
                logging.warning("Using default overlay settings: %s", exc)
        values["width"] = max(380, values["width"])
        values["height"] = max(440, values["height"])
        return values

    def save(self, values: dict) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(values, indent=2), encoding="utf-8")
            temporary.replace(self.path)
