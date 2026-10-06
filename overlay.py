"""Live, native macOS tracker using the approved utility design.

The parser publishes immutable snapshots through queues. Only Tk's main thread
touches widgets; card loading, log following and combat simulation remain workers.
No sample values are inserted unless main.py was explicitly started with --demo.
"""
from __future__ import annotations
import json
import logging
import queue
import sqlite3
import sys
import time
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path
from datetime import datetime
from typing import Callable

from advisor import compare_shop, economy_notes, recruit_plan, threat_summary
from cards_db import CardsDatabase
from card_images import CardImages, CardPortrait, ImageCache
from combat import CombatWorker, model_key
from history import HistoryStore
from hotkeys import MacHotkey
from insights import (PositioningWorker, browser_cards, card_support, combat_reasons,
                      coverage_inspector, turn_plan)
from parser import BattlegroundsState, MinionStats
from settings import SettingsStore
from ui import UI, DARK, FONT, ScrollArea

# Public palette aliases retained for extensions; widget colors are theme-local.
BG, PANEL, FG, MUTED, ACCENT = (DARK[k] for k in ("window", "panel", "text", "secondary", "accent"))
SECTIONS = {"economy": "Economy", "shop": "Shop comparison", "combat": "Combat model",
            "hand": "Your hand", "decision": "Decision explanations"}
VIEWS = {"live": "Live overlay", "history": "Match history",
         "reference": "Card reference", "coach": "Decision lab", "settings": "Settings"}
GAME_OVERLAY_WIDTH = 330
GAME_OVERLAY_HEIGHT = 700
GAME_PRESETS = ("auto", "recruit", "combat", "minimal")


def number(value):
    return "—" if value is None else str(value)


def history_totals(heroes):
    """Aggregate the whole journal, not just the visible/search-filtered rows."""
    tracked = sum(h["tracked"] for h in heroes)
    ranked = sum(h["ranked"] for h in heroes)
    average = sum((h["average"] or 0) * h["ranked"] for h in heroes) / ranked if ranked else None
    rate = sum(h["top4"] or 0 for h in heroes) / ranked if ranked else None
    return tracked, ranked, average, rate


class Overlay:
    def __init__(self, cards: CardsDatabase, on_close: Callable[[], None] | None = None,
                 history: HistoryStore | None = None, settings_path: Path | None = None,
                 demo: bool = False, image_cache: ImageCache | None = None) -> None:
        self.cards, self.on_close, self.history, self.demo = cards, on_close, history, demo
        self.events, self.card_events = queue.Queue(maxsize=1), queue.Queue(maxsize=1)
        self.odds_events, self.position_events, self.commands = queue.Queue(maxsize=1), queue.Queue(maxsize=1), queue.Queue()
        self.state, self.card_status = BattlegroundsState(), "Loading card reference…"
        self.settings = SettingsStore(settings_path)
        self.preferences = self.settings.load()
        p = self.preferences
        if p.get("ui_version", 0) < 2:
            # An old 440px-wide saved geometry must not reopen the old text layout.
            p.update(width=1040, height=760, ui_version=2)
            p["collapsed"] = sorted(set(p["collapsed"]) | {"economy", "shop", "combat", "hand"})
        if p.get("ui_version", 0) < 3:
            p.update(ui_version=3)
            p["collapsed"] = sorted(set(p["collapsed"]) | {"decision"})
        self.collapsed = set(p["collapsed"])
        self.ui = UI(p.get("theme", "dark"))
        self.current_view = "live"
        self.selected_opponent, self.selected_match = "", ""
        self.reference_tier, self.history_sort = 1, "date"
        self.compact, self.board_only, self._closed = False, p.get("auto_combat_estimate", True), False
        self.game_overlay = p.get("game_overlay", False)
        self.game_preset = p.get("game_preset", "auto")
        self.odds, self._model_key, self._timer = None, "", None
        self.positioning, self._position_generation, self._position_key = None, 0, ""
        self._history_time, self._history_rows = 0., []
        self.root = tk.Tk()
        self.root.withdraw()
        self.card_images = CardImages(self.root, self.ui, image_cache or ImageCache(cards.data_dir / "images", network=not demo))
        self.root.title("Open Battlegrounds")
        if sys.platform == "win32":
            assets = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
            icon = assets / "OpenBattlegroundsOverlay.ico"
            if icon.is_file():
                try:
                    self.root.iconbitmap(default=str(icon))
                except tk.TclError:
                    pass
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", p.get("topmost", True))
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if self.game_overlay:
            self.root.minsize(GAME_OVERLAY_WIDTH, 560)
            width, height, x, y = self._game_overlay_geometry(screen_w, screen_h)
        else:
            self.root.minsize(800, 580)
            width, height = min(max(800, p["width"]), screen_w-40), min(max(580, p["height"]), screen_h-80)
            x, y = min(p["x"], max(0, screen_w-width)), min(p["y"], max(0, screen_h-height))
            p.update(width=width, height=height)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.wm_attributes("-alpha", 1. if p.get("reduce_transparency") else max(.85, p["opacity"]))
        self.history_query = tk.StringVar(self.root)
        self.reference_query = tk.StringVar(self.root)
        self.reference_tribe = tk.StringVar(self.root)
        self.reference_mechanic = tk.StringVar(self.root)
        self.reference_support = tk.StringVar(self.root)
        self.rank_value = tk.StringVar(self.root)
        self.feedback_value = tk.StringVar(self.root)
        self.history_query.trace_add("write", lambda *_: self._history_refresh())
        self.reference_query.trace_add("write", lambda *_: self._reference_refresh())
        self.reference_tribe.trace_add("write", lambda *_: self._reference_refresh())
        self.reference_mechanic.trace_add("write", lambda *_: self._reference_refresh())
        self.reference_support.trace_add("write", lambda *_: self._reference_refresh())
        self._worker = CombatWorker(lambda report: self._replace(self.odds_events, report))
        self._position_worker = PositioningWorker(lambda generation, result: self._replace(self.position_events, (generation, result)))
        self.hotkey = MacHotkey(lambda: self.commands.put("visibility"))
        self._narrow, self._resize_timer = False, None
        self._build_shell()
        self.root.bind("<Escape>", self._escape)
        shortcut = "Command" if sys.platform == "darwin" else "Control"
        self.root.bind(f"<{shortcut}-q>", lambda event: self.close())
        self.root.bind("<KeyPress-c>", self._compact_key)
        self.root.bind("<MouseWheel>", self._scroll)
        self.root.bind("<Configure>", self._configured)
        if not self.hotkey.registered:
            for key in ("h", "H"):
                self.root.bind(f"<{shortcut}-Shift-KeyPress-{key}>", lambda event: self.toggle_compact())
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.update_idletasks()
        self._narrow = self.root.winfo_width() < 940
        self.show_view("live", focus=False)
        if p["compact"] and not self.game_overlay:
            self.toggle_compact()
        self._timer = self.root.after(100, self._drain)
        self.root.deiconify()

    def _build_shell(self):
        for child in self.root.winfo_children():
            child.destroy()
        u, c = self.ui, self.ui.colors
        self.root.configure(bg=c["window"])
        u.tree_style(self.root)
        if self.game_overlay:
            self._build_game_overlay_shell()
            return
        self.header = u.frame(self.root, "sidebar", padx=14, pady=5)
        self.header.pack(fill="x")
        dots = tk.Canvas(self.header, bg=c["sidebar"], width=56, height=22, highlightthickness=0)
        for index, color in enumerate(("#ff6058", "#ffbd2e", "#28c840")):
            dots.create_oval(3+index*18, 5, 14+index*18, 16, fill=color, outline=color)
        dots.pack(side="left", padx=(0, 8))
        title = u.label(self.header, "Open Battlegrounds", 13, "bold", surface="sidebar")
        title.pack(side="left")
        for widget in (self.header, title, dots):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag)
        self.close_button = u.button(self.header, "Close", self.close, surface="sidebar", role="secondary")
        self.close_button.pack(side="right")
        self.game_button = u.button(self.header, "Game overlay", self.toggle_game_overlay, surface="sidebar", role="secondary")
        self.game_button.pack(side="right", padx=6)
        self.compact_button = u.button(self.header, "Compact", self.toggle_compact, surface="sidebar", role="secondary")
        self.compact_button.pack(side="right", padx=6)
        self.mode_label = u.label(self.header, "DEMO · synthetic" if self.demo else "Local log observations",
                                 11, role="warning" if self.demo else "secondary", surface="sidebar")
        self.mode_label.pack(side="right", padx=12)
        self.compact_summary = u.label(self.root, "", 12, padx=16, pady=7, wraplength=450)

        self.body = u.frame(self.root)
        self.body.pack(fill="both", expand=True)
        self.sidebar = u.frame(self.body, "sidebar", width=154, padx=8, pady=18)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.nav_buttons = {}
        for view, name in VIEWS.items():
            button = u.button(self.sidebar, name, lambda view=view: self.show_view(view),
                              surface="sidebar", role="secondary", icon=view)
            button.pack(fill="x", pady=3)
            self.nav_buttons[view] = button
        u.label(self.sidebar, "Read-only by design\nNo game actions.\nNo uploads.", 11,
                role="secondary", surface="sidebar", wraplength=130).pack(side="bottom", pady=12)
        self.main = u.frame(self.body, padx=22, pady=18)
        self.main.pack(side="left", fill="both", expand=True)
        heading = u.frame(self.main)
        heading.pack(fill="x", pady=(0, 14))
        self.page_title = u.label(heading, "", 23, "bold")
        self.page_title.pack(anchor="w")
        self.meta = u.label(heading, "", 12, role="secondary", wraplength=650)
        self.meta.pack(anchor="w", pady=(5, 0))
        self.area = ScrollArea(self.main, u)
        self.area.pack(fill="both", expand=True)
        self.footer_frame = u.frame(self.root, "sidebar", padx=12, pady=5)
        self.footer_frame.pack(fill="x")
        self.connection = u.label(self.footer_frame, "", 11, role="secondary", surface="sidebar", wraplength=680)
        self.connection.pack(side="left", fill="x", expand=True)
        self.footer = u.label(self.footer_frame, "Drag title · C compact · ⌘⇧H show/hide",
                              11, role="secondary", surface="sidebar")
        self.footer.pack(side="right", padx=8)
        grip = tk.Canvas(self.footer_frame, bg=c["sidebar"], width=18, height=18,
                         highlightthickness=0, cursor="bottom_right_corner")
        for offset in (4, 8, 12):
            grip.create_line(offset, 16, 16, offset, fill=c["secondary"])
        grip.pack(side="right")
        grip.bind("<Button-1>", self._resize_start)
        grip.bind("<B1-Motion>", self._resize)

    def _build_game_overlay_shell(self):
        """A fixed-width, draggable rail designed for the unused screen edge beside Hearthstone."""
        u, c = self.ui, self.ui.colors
        self.header = u.frame(self.root, "sidebar", padx=9, pady=4)
        self.header.pack(fill="x")
        title = u.label(self.header, "BG Side Overlay", 12, "bold", surface="sidebar")
        title.pack(side="left")
        for widget in (self.header, title):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag)
        self.close_button = u.button(self.header, "Close", self.close, surface="sidebar", role="secondary", padx=6, pady=2)
        self.close_button.pack(side="right")
        self.full_button = u.button(self.header, "Full", self.toggle_game_overlay, surface="sidebar", role="secondary", padx=6, pady=2)
        self.full_button.pack(side="right", padx=4)
        self.preset_button = u.button(self.header, self._preset_label(), self.cycle_game_preset,
                                      surface="sidebar", role="secondary", padx=6, pady=2)
        self.preset_button.pack(side="right", padx=4)
        self.game_content = u.frame(self.root, padx=10, pady=8)
        self.game_content.pack(fill="both", expand=True)

    def _game_overlay_geometry(self, screen_w=None, screen_h=None):
        screen_w = self.root.winfo_screenwidth() if screen_w is None else screen_w
        screen_h = self.root.winfo_screenheight() if screen_h is None else screen_h
        width, height = min(GAME_OVERLAY_WIDTH, screen_w-24), min(GAME_OVERLAY_HEIGHT, screen_h-60)
        saved_x, saved_y = self.preferences.get("game_x"), self.preferences.get("game_y")
        x = saved_x if type(saved_x) is int else screen_w-width-20
        y = saved_y if type(saved_y) is int else min(90, max(30, screen_h-height-30))
        return width, height, min(max(0, x), max(0, screen_w-width)), min(max(0, y), max(0, screen_h-height))

    def _label(self, parent, text, **options):
        return self.ui.label(parent, text, **options)

    def _button(self, parent, text, action):
        return self.ui.button(parent, text, action)

    def _text(self, parent, height=10):
        return self.ui.text(parent, height)

    def _line(self, parent, surface="window", pady=8):
        line = tk.Frame(parent, height=1, bg=self.ui.colors["line"])
        line.pack(fill="x", pady=pady)

    @staticmethod
    def _replace(target, value):
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        try:
            target.put_nowait(value)
        except queue.Full:
            pass

    def publish(self, state):
        self._replace(self.events, state)

    def publish_cards(self, cards, message):
        self._replace(self.card_events, (cards, message))

    def _drain(self):
        if self._closed:
            return
        if self._timer:
            self.root.after_cancel(self._timer)
        dirty = False
        for source, target in ((self.events, "state"), (self.card_events, "cards"), (self.odds_events, "odds")):
            try:
                value = source.get_nowait()
            except queue.Empty:
                continue
            if target == "cards":
                self.cards, self.card_status = value
            elif target == "odds":
                if value.key != self._model_key:
                    continue
                self.odds = value
                if value.trials and value.stage == "refined" and self.history:
                    try:
                        self.history.record_prediction(self.state, value)
                    except sqlite3.Error as exc:
                        logging.warning("Prediction calibration write failed: %s", exc)
            else:
                self.state = value
            dirty = True
        try:
            generation, result = self.position_events.get_nowait()
            if generation == self._position_generation:
                self.positioning = result
                dirty = True
        except queue.Empty:
            pass
        try:
            while True:
                if self.commands.get_nowait() == "visibility":
                    self.toggle_visibility()
        except queue.Empty:
            pass
        if dirty:
            self._render()
        self.card_images.poll()
        self._timer = self.root.after(100, self._drain)

    def _combat_inputs(self):
        s = self.state
        captured = s.in_combat and s.combat_round == s.round
        opponent = s.combat_opponent if captured else s.next_opponent
        own = s.combat_board if captured else s.board_stats
        return own, s.opponent_stats.get(opponent, []), (s.tavern_tier, s.opponent_tiers.get(opponent)), opponent

    def _combat_estimate_copy(self):
        """Return truthful, compact text for the automatically requested board-only model."""
        own, enemy, _, opponent = self._combat_inputs()
        if not self.board_only:
            return "Hypothetical win chance off", "Turn it on in Settings to estimate observed boards.", "secondary"
        if not own:
            return "Win chance awaiting your board", "Need observed friendly minions before an estimate can run.", "secondary"
        if not enemy:
            name = self._opponent_name(opponent) if opponent else "an opponent"
            return "Win chance awaiting opponent", f"Need a last-observed board for {name}.", "secondary"
        if self.odds and self.odds.key == self._model_key:
            if self.odds.trials:
                interval = (f" · 95% win interval {self.odds.interval[0]:.1%}–{self.odds.interval[1]:.1%}"
                            if self.odds.interval else "")
                prefix = "Incomplete baseline win chance" if self.odds.baseline else "Hypothetical win chance"
                warning = (f" · {len(self.odds.blockers)} unmodelled effect{'s' if len(self.odds.blockers) != 1 else ''} excluded"
                           if self.odds.baseline else "")
                stage = "Quick estimate" if self.odds.stage == "quick" else "Refined estimate"
                return (f"{prefix} · {self.odds.win:.1%}",
                        f"{stage} · Loss {self.odds.loss:.1%} · Tie {self.odds.tie:.1%} · {self.odds.trials:,} trials · {self.odds.confidence} confidence{interval}{warning}",
                        "warning" if self.odds.baseline else "text")
            if self.odds.blockers:
                more = f" · {len(self.odds.blockers)-1} more in Full → Combat model" if len(self.odds.blockers) > 1 else ""
                return "Win chance unavailable", self.odds.blockers[0] + more, "warning"
        return "Calculating hypothetical win chance…", "Observed boards only; unsupported effects suppress estimates.", "secondary"

    def _combat_age(self, opponent):
        seen = self.state.opponent_rounds.get(opponent)
        return max(0, self.state.round-seen) if seen is not None else 0

    def _render(self):
        s = self.state
        phase = "Combat" if s.in_combat else "Recruit" if s.active else "Match ended" if s.result else "Waiting"
        status = s.stream_status
        short_status = ("Log access error · Open Settings for details" if any(word in status.lower() for word in ("denied", "permission", "cannot", "error"))
                        else "Following Power.log · values are last observed, not game-process status" if "following" in status.lower()
                        else status)
        if not self.game_overlay:
            self.meta.configure(text=f"{phase} · Round {s.round or '—'} · Turn {s.turn} · {s.status}")
            self.connection.configure(text=("DEMO · Synthetic data; no real journal" if self.demo else short_status))
            summary_prefix = "DEMO · Synthetic · R" if self.demo else "Round "
            self.compact_summary.configure(text=f"{summary_prefix}{s.round or '—'} · Tier {s.tavern_tier if s.local_player else '—'} · Gold {number(s.gold)}\nNext: {self._opponent_name(s.next_opponent) if s.next_opponent else 'Not observed'}")
        own, enemy, tiers, _ = self._combat_inputs()
        opponent = self._combat_inputs()[3]
        age = self._combat_age(opponent)
        key = model_key(own, enemy, self.cards, tiers, self.board_only, age, True)
        if key != self._model_key:
            self.odds = None
            self._model_key = self._worker.submit(own, enemy, self.cards, tiers, self.board_only, age, True)
        if self.current_view == "live":
            self._render_live()
        elif self.current_view == "history":
            self._history_refresh()
        elif self.current_view == "reference":
            self._reference_refresh()
        elif self.current_view == "coach":
            self._coach_refresh()
        elif hasattr(self, "diagnostics") and self.diagnostics.winfo_exists():
            self.diagnostics.configure(text=f"{s.stream_status}\n{s.status}\n{self.card_status}\n{self.hotkey.status}")

    def show_view(self, view, focus=True):
        if view not in VIEWS:
            return
        if self.game_overlay:
            if view != "live":
                self.toggle_game_overlay()
                return self.show_view(view, focus)
            self.current_view = "live"
            self._render()
            return
        if self.compact:
            self.toggle_compact()
        self.card_images.preview.hide()
        self.current_view = view
        for child in self.area.inner.winfo_children():
            child.destroy()
        self.area.canvas.yview_moveto(0)
        self.page_title.configure(text=VIEWS[view])
        for key, button in self.nav_buttons.items():
            button.set_selected(key == view)
        if view == "live":
            self.live_host = self.ui.frame(self.area.inner)
            self.live_host.pack(fill="both", expand=True)
        elif view == "history":
            self._build_history()
        elif view == "reference":
            self._build_reference()
        elif view == "coach":
            self._build_coach()
        else:
            self._build_settings()
        self._render()
        if focus:
            self.nav_buttons[view].focus_set()

    def _notice(self, parent, title, detail, surface="window"):
        self._label(parent, title, size=13, weight="bold", surface=surface).pack(anchor="w", pady=(8, 4))
        self._label(parent, detail, role="secondary", surface=surface, wraplength=340).pack(fill="x", pady=(0, 10))

    def _heading(self, parent, title, detail="", surface="window"):
        row = self.ui.frame(parent, surface)
        row.pack(fill="x", pady=(6, 5))
        self._label(row, title, weight="bold", surface=surface).pack(side="left")
        if detail:
            self._label(row, detail, size=11, role="secondary", surface=surface).pack(side="right")

    def _name(self, card_id):
        card = self.cards.get(card_id)
        return card.name if card else (card_id or "Unknown hero")

    def _opponent_name(self, opponent):
        card_id = self.state.opponent_heroes.get(opponent)
        return self._name(card_id) if card_id else f"Opponent {opponent}"

    def _minion(self, minion):
        stats = f"{number(minion.attack)}/{number(minion.health)}"
        card = self.cards.get(minion.card_id)
        name = card.name if card else minion.name or minion.card_id or "Unknown minion"
        return f"{name}  {stats}"

    def _preset_label(self):
        return {"auto": "Auto", "recruit": "Recruit", "combat": "Combat", "minimal": "Minimal"}.get(self.game_preset, "Auto")

    def _game_focus(self):
        if self.game_preset != "auto":
            return self.game_preset
        if not self.state.active:
            return "minimal"
        return "combat" if self.state.in_combat else "recruit"

    def _threat_lines(self, board, opponent):
        summary = threat_summary(board, self.cards)
        seen = self.state.opponent_rounds.get(opponent)
        age = max(0, self.state.round-seen) if seen is not None else None
        prefix = f"Seen R{seen} · {age} rounds old; may have changed." if age is not None else "No dated opponent observation."
        return [prefix, *summary.signals]

    def _combat_insight_lines(self):
        if not self.odds or self.odds.key != self._model_key:
            return ["Checking coverage / simulating in background…"]
        report = self.odds
        if report.trials:
            lines = [report.first_attacker, "Modelled: " + "; ".join(report.modelled)]
            if report.baseline:
                lines.extend(["Incomplete baseline: unmodelled effects are excluded and can change the result.", *report.blockers])
            if report.interval:
                lines.append(f"{report.confidence} confidence · 95% win interval {report.interval[0]:.1%}–{report.interval[1]:.1%}")
            if report.scenario:
                lines.append(f"Stale-board sensitivity · {report.scenario[0]:.1%}–{report.scenario[1]:.1%}")
            if report.dealt or report.received:
                lines.append(f"Conditional damage · deal {report.dealt or '—'} / receive {report.received or '—'}")
            return lines
        if report.blockers:
            return ["Coverage blockers:", *report.blockers, "Modelled when applicable: " + "; ".join(report.modelled)]
        return [report.message]

    @staticmethod
    def _layout_portraits(grid, portraits, width, pitch=84):
        """Ignore a queued <Configure> event when a live rerender removed its grid."""
        try:
            if not grid.winfo_exists():
                return
            columns = max(1, min(7, width//pitch))
            for index, portrait in enumerate(portraits):
                if portrait.winfo_exists() and portrait.master == grid:
                    portrait.grid(row=index//columns, column=index%columns, padx=2, pady=3, sticky="w")
        except tk.TclError:
            # Tk can deliver a final Configure while the old panel is being destroyed.
            return

    def _board(self, parent, board, surface="window", board_key="own", compact=False, show_hint=True):
        grid = self.ui.frame(parent, surface)
        grid.pack(fill="x")
        portraits = []
        for m in board:
            card = self.cards.get(m.card_id)
            portraits.append(CardPortrait(grid, self.card_images, m, card, self.cards.locale, surface, board_key, compact=compact))
        if portraits:
            def layout(event=None):
                width = event.width if event else 340
                self._layout_portraits(grid, portraits, width, 50 if compact else 84)
            grid.bind("<Configure>", layout)
            layout()
            if show_hint:
                self._label(parent, "Hover for full card · badges: logged ATK / HP\nNames appear when artwork is unavailable.",
                            size=10, role="secondary", surface=surface, wraplength=320).pack(anchor="w", pady=5)
        if not board:
            self._label(grid, "No minions observed yet.", role="secondary", surface=surface).pack(anchor="w", pady=8)

    def _render_live(self):
        if self.game_overlay:
            self._render_game_overlay()
            return
        if not hasattr(self, "live_host") or not self.live_host.winfo_exists():
            return
        focused = self.root.focus_get()
        focus_key = getattr(focused, "action_key", None)
        for child in self.live_host.winfo_children():
            child.destroy()
        s, u = self.state, self.ui
        self.live_host.columnconfigure(0, weight=1)
        self.live_host.columnconfigure(1, weight=0, minsize=370 if not self._narrow else 0)
        notebook = u.frame(self.live_host, padx=0, pady=0)
        panel = u.frame(self.live_host, "panel", padx=14, pady=10, highlightthickness=1,
                        highlightbackground=u.colors["line"])
        if self._narrow:
            panel.grid(row=0, column=0, sticky="ew")
            notebook.grid(row=1, column=0, sticky="ew", pady=(24, 0))
        else:
            notebook.grid(row=0, column=0, sticky="new", padx=(0, 24))
            panel.grid(row=0, column=1, sticky="new")
        self._heading(notebook, "Opponent notebook", "Last observed")
        opponents = sorted(set(s.opponent_stats) | set(s.opponent_heroes) | ({s.next_opponent} if s.next_opponent else set()))
        if not opponents:
            self._notice(notebook, "No opponents observed", "Meet an opponent in combat to record a board. Hidden information is never inferred.")
        if self.selected_opponent not in opponents:
            self.selected_opponent = s.next_opponent or (opponents[0] if opponents else "")
        self._opponent_controls = {}
        for opponent in opponents:
            seen = s.opponent_rounds.get(opponent)
            text = self._opponent_name(opponent) + (" · Next" if opponent == s.next_opponent else "")
            text += f"\nTier {number(s.opponent_tiers.get(opponent))} · " + (f"Seen R{seen}" if seen is not None else "Not observed")
            button = u.button(notebook, text, lambda o=opponent: self.select_opponent(o),
                              surface="selected" if opponent == self.selected_opponent else "window")
            button.action_key = ("opponent", opponent)
            self._opponent_controls[opponent] = button
            button.pack(fill="x", pady=2)
        if isinstance(focus_key, tuple) and focus_key[0] == "opponent":
            replacement = self._opponent_controls.get(focus_key[1])
            if replacement:
                replacement.focus_set()
        if self.selected_opponent:
            self._line(notebook)
            opponent = self.selected_opponent
            seen = s.opponent_rounds.get(opponent)
            age = max(0, s.round-seen) if seen is not None else None
            self._heading(notebook, self._opponent_name(opponent), f"{age} rounds ago" if age is not None else "Unknown")
            self._board(notebook, s.opponent_stats.get(opponent, []), board_key=f"opponent:{opponent}")
            self._label(notebook, "\n".join(self._threat_lines(s.opponent_stats.get(opponent, []), opponent)),
                        role="warning", size=10, wraplength=330).pack(fill="x", pady=(0, 6))
            self._label(notebook, "An observation, not their current board.\nLater changes and unobserved slots are unknown.",
                        role="warning", size=11, wraplength=330).pack(fill="x", pady=10)
        self._line(notebook, pady=16)
        self._label(notebook, "Know what you know.", weight="bold").pack(anchor="w")
        self._label(notebook, "Only local logs and cached card metadata. No game actions, no account API and no hidden-board guesses.",
                    role="secondary", wraplength=330).pack(fill="x", pady=6)
        self._heading(panel, "Battlegrounds", "Demo" if self.demo else "Log observations", "panel")
        if not s.active and not s.result:
            error = any(word in s.stream_status.lower() for word in ("denied", "permission", "cannot", "error"))
            self._notice(panel, "Log access needs attention" if error else "Waiting for Hearthstone",
                         "Open Settings for the log path and access details." if error else
                         "Start a Battlegrounds match. This panel updates when readable game-log events arrive.", "panel")
            self._button(panel, "Open log diagnostics", lambda: self.show_view("settings")).pack(fill="x", pady=10)
            self.board_names = []
            self.listing = self._text(panel, 3)
            self.listing.pack(fill="x")
            self._set_text(self.listing, [(s.status, "muted"), (self.card_status, "muted")])
            self.card_images.restore(focus_key)
            return
        phase = "Combat" if s.in_combat else "Recruit" if s.active else "Last match"
        self._heading(panel, f"Round {s.round or '—'} · {phase}",
                      f"{number(s.placement)} place" if s.result else "", "panel")
        metrics = u.frame(panel, "panel")
        metrics.pack(fill="x", pady=(4, 8))
        for index, (value, label) in enumerate(((s.tavern_tier if s.local_player else None, "Tavern tier"),
                                             (s.gold, "Gold"), (s.health, "Health"), (s.armor, "Armor"))):
            metrics.columnconfigure(index, weight=1)
            self._label(metrics, number(value), size=23, weight="bold",
                        role="warning" if label == "Gold" else "text", surface="panel").grid(row=0, column=index, sticky="w")
            self._label(metrics, label, size=11, role="secondary", surface="panel").grid(row=1, column=index, sticky="w")
        self._line(panel)
        opponent = s.combat_opponent if s.in_combat and s.combat_opponent else s.next_opponent
        self._label(panel, ("Facing: " if s.in_combat else "Next: ") + (self._opponent_name(opponent) if opponent else "Not observed"),
                    weight="bold", surface="panel", wraplength=325).pack(anchor="w")
        seen = s.opponent_rounds.get(opponent)
        stale = f"Seen R{seen} · {max(0, s.round-seen)} rounds ago; may have changed." if seen is not None else "No observed opponent board."
        self._label(panel, stale, size=11, role="warning", surface="panel", wraplength=325).pack(anchor="w", pady=(4, 4))
        estimate = u.frame(panel, "raised", padx=10, pady=7)
        estimate.pack(fill="x", pady=(4, 4))
        estimate_title, estimate_detail, estimate_role = self._combat_estimate_copy()
        self.combat_estimate_title = self._label(estimate, estimate_title, size=16, weight="bold", surface="raised")
        self.combat_estimate_title.pack(anchor="w")
        self.combat_estimate_detail = self._label(estimate, estimate_detail, size=10, role=estimate_role,
                                                  surface="raised", wraplength=310)
        self.combat_estimate_detail.pack(anchor="w", pady=(3, 0))
        captured = s.in_combat and s.combat_round == s.round
        board = s.combat_board if captured else s.board_stats
        self._line(panel)
        self._heading(panel, "Your board · pre-combat" if captured else "Your board",
                      f"{len(board)} of 7", "panel")
        self._board(panel, board, "panel")
        self.board_names = [self._name(m.card_id) for m in board]
        # One compact list below the complete board, not a wall above it.
        self._live_controls = {}
        for key, title in SECTIONS.items():
            action = u.button(panel, f"{title} · {'Show' if key in self.collapsed else 'Hide'}",
                              lambda key=key: self.toggle_section(key), surface="panel", icon="chevron", pady=3)
            action.action_key = key
            self._live_controls[key] = action
            action.pack(fill="x", pady=(3, 0))
        self.listing = self._text(panel, 9)
        details = self._live_details()
        if details:
            self.listing.pack(fill="both", expand=True, pady=(8, 0))
        self._set_text(self.listing, details)
        if focus_key in self._live_controls:
            self._live_controls[focus_key].focus_set()
        self.card_images.restore(focus_key)

    def _render_game_overlay(self):
        if not hasattr(self, "game_content") or not self.game_content.winfo_exists():
            return
        focused = self.root.focus_get()
        focus_key = getattr(focused, "action_key", None)
        for child in self.game_content.winfo_children():
            child.destroy()
        s, u = self.state, self.ui
        phase = "Combat" if s.in_combat else "Recruit" if s.active else "Waiting"
        focus = self._game_focus()
        self._heading(self.game_content, f"Round {s.round or '—'} · {phase}", f"{self._preset_label()} · {focus}")
        resources = u.frame(self.game_content, "panel", padx=8, pady=6)
        resources.pack(fill="x", pady=(0, 6))
        for index, (value, label) in enumerate(((s.tavern_tier if s.local_player else None, "Tier"),
                                                (s.gold, "Gold"), (s.health, "HP"), (s.armor, "Armor"))):
            resources.columnconfigure(index, weight=1)
            self._label(resources, number(value), size=17, weight="bold", role="warning" if label == "Gold" else "text",
                        surface="panel").grid(row=0, column=index, sticky="w")
            self._label(resources, label, size=9, role="secondary", surface="panel").grid(row=1, column=index, sticky="w")
        own, enemy, _, opponent = self._combat_inputs()
        opponent_name = self._opponent_name(opponent) if opponent else "Not observed"
        seen = s.opponent_rounds.get(opponent)
        age = f"Seen R{seen} · {max(0, s.round-seen)} rounds ago" if seen is not None else "No last-observed board"
        estimate = u.frame(self.game_content, "raised", padx=8, pady=5)
        estimate.pack(fill="x", pady=(0, 6))
        title, detail, role = self._combat_estimate_copy()
        self.game_estimate_title = self._label(estimate, title, size=14, weight="bold", surface="raised")
        self.game_estimate_title.pack(anchor="w")
        self._label(estimate, detail, size=9, role=role, surface="raised", wraplength=294).pack(anchor="w", pady=(2, 0))
        if focus == "minimal":
            self._label(self.game_content, ("Facing: " if s.in_combat else "Next: ") + opponent_name,
                        weight="bold", wraplength=300).pack(anchor="w")
            self._label(self.game_content, age + "; may have changed.", size=9, role="warning", wraplength=300).pack(anchor="w", pady=(2, 5))
            self.board_names = []
        elif focus == "recruit":
            self._heading(self.game_content, "Recruit planner", "Logged costs + heuristic")
            plan = "\n".join(recruit_plan(s, self.cards)[:7])
            self._label(self.game_content, plan, size=9, role="secondary", wraplength=300).pack(anchor="w", pady=(0, 5))
            captured = s.in_combat and s.combat_round == s.round
            self._heading(self.game_content, "Your board · pre-combat" if captured else "Your board", f"{len(own)} / 7")
            self._board(self.game_content, own, board_key="game:own", compact=True, show_hint=False)
            self.board_names = [self._name(m.card_id) for m in own]
            self._heading(self.game_content, "Next opponent · last observed", f"{len(enemy)} / 7")
            self._label(self.game_content, "\n".join(self._threat_lines(enemy, opponent)[:3]), size=9,
                        role="warning", wraplength=300).pack(anchor="w", pady=(0, 4))
        else:
            self._label(self.game_content, "Facing: " + opponent_name, weight="bold", wraplength=300).pack(anchor="w")
            self._label(self.game_content, age + "; may have changed.", size=9, role="warning", wraplength=300).pack(anchor="w", pady=(2, 3))
            self._heading(self.game_content, "Opponent threat · last observed", f"{len(enemy)} / 7")
            self._label(self.game_content, "\n".join(self._threat_lines(enemy, opponent)[:4]), size=9,
                        role="warning", wraplength=300).pack(anchor="w", pady=(0, 3))
            factors = combat_reasons(own, enemy, self.odds, self.cards)
            self._label(self.game_content, "\n".join(factors[:3]), size=9, role="secondary", wraplength=300).pack(anchor="w", pady=(0, 4))
            captured = s.in_combat and s.combat_round == s.round
            self._heading(self.game_content, "Your board · pre-combat" if captured else "Your board", f"{len(own)} / 7")
            self._board(self.game_content, own, board_key="game:own", compact=True, show_hint=False)
            self.board_names = [self._name(m.card_id) for m in own]
            self._heading(self.game_content, "Opponent · last observed", f"{len(enemy)} / 7")
            self._board(self.game_content, enemy, board_key=f"game:opponent:{opponent or 'unknown'}", compact=True, show_hint=False)
        self._label(self.game_content, "Drag the header to move · Full opens history, cards and settings.",
                    size=9, role="secondary", wraplength=300).pack(anchor="w", pady=(6, 0))
        self.card_images.restore(focus_key)

    def _live_details(self):
        s = self.state
        lines = []
        add = lambda text, tag="": lines.append((text, tag))
        if "economy" not in self.collapsed:
            add("Economy", "heading")
            for note in economy_notes(s):
                add(note)
        if "shop" not in self.collapsed:
            add("Recruit planner", "heading")
            add("Logged affordability plus a transparent shop heuristic; not optimal-play advice.", "muted")
            for note in recruit_plan(s, self.cards):
                add(note)
            add("Shop comparison", "heading")
            add("Heuristic comparison, not optimal-play advice.", "muted")
            suggestions = compare_shop(s, self.cards)
            for suggestion in suggestions:
                add(f"{self._minion(suggestion.minion)} · score {suggestion.score:g}")
                add(" · ".join(suggestion.reasons), "muted")
                if suggestion.text:
                    add(suggestion.text, "muted")
                if suggestion.replacement:
                    add(suggestion.replacement, "warning")
            if not suggestions:
                add("Shop minions are logged during recruit.", "muted")
        if "combat" not in self.collapsed:
            add("Automatic combat estimate", "heading")
            add("MODEL ONLY · Not live full-rules odds. Historical boards may have changed.", "warning")
            if not self.board_only:
                add("Automatic board-only estimate is off in Settings.", "muted")
            elif self.odds and self.odds.key == self._model_key:
                r = self.odds
                if r.trials:
                    add(f"Hypothetical win {r.win:.1%} / loss {r.loss:.1%} / tie {r.tie:.1%}")
                    interval = f" · 95% win interval {r.interval[0]:.1%}–{r.interval[1]:.1%}" if r.interval else ""
                    add(f"{'Quick' if r.stage == 'quick' else 'Refined'} · {r.trials:,} trials · {r.confidence} confidence{interval}", "muted")
                    if r.baseline:
                        add("INCOMPLETE BASELINE · Unmodelled observed effects are excluded; result can be biased.", "warning")
                        for reason in r.blockers:
                            add(reason, "warning")
                    if r.scenario:
                        add(f"Stale-board sensitivity {r.scenario[0]:.1%}–{r.scenario[1]:.1%}", "warning")
                        add(r.scenario_detail, "muted")
                    add(f"Conditional damage · deal {r.dealt or '—'} / receive {r.received or '—'}")
                    add(r.first_attacker, "muted")
                for coverage_line in r.modelled:
                    add("Modelled: " + coverage_line, "muted")
                add(r.message, "muted")
                for reason in r.blockers:
                    add(reason, "warning")
            else:
                add("Checking coverage / simulating in background…", "muted")
            if s.context_effects:
                add("Excluded external effects: " + ", ".join(self._name(c) for c in s.context_effects), "warning")
        if "decision" not in self.collapsed:
            own, enemy, _, _ = self._combat_inputs()
            add("Decision explanations", "heading")
            add("Observed contributors and affordability only; never an optimal-play claim.", "muted")
            for reason in combat_reasons(own, enemy, self.odds, self.cards):
                add(reason)
            for note in turn_plan(s, self.cards)[:5]:
                add(note, "muted")
            if not self.game_overlay:
                add("Open Decision lab for coverage categories, opponent timeline and local positioning comparisons.", "muted")
        if "hand" not in self.collapsed:
            add("Your hand", "heading")
            for m in s.hand_stats:
                add(self._minion(m))
            if not s.hand_stats:
                add("No observed minions in hand.", "muted")
        return lines

    @staticmethod
    def _set_text(widget, lines):
        scroll = widget.yview()[0]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for text, tag in lines:
            widget.insert("end", text + "\n", tag)
        widget.configure(state="disabled")
        widget.yview_moveto(scroll)

    def select_opponent(self, opponent):
        self.selected_opponent = opponent
        self._render_live()

    def toggle_section(self, key):
        if key in self.collapsed:
            self.collapsed.remove(key)
        else:
            self.collapsed.add(key)
        self._render()
        self._save()

    def section_controls(self):
        # Sections are real inline disclosures in the redesigned live view.
        self.show_view("live")

    def toggle_model(self):
        self.board_only = not self.board_only
        self.preferences["auto_combat_estimate"] = self.board_only
        self.odds, self._model_key = None, ""
        if self.board_only:
            self.collapsed.discard("combat")
        self._render()
        if self.current_view == "settings":
            self.show_view("settings")
        self._save()

    def _build_history(self):
        host = self.area.inner
        self.history_metrics = self.ui.frame(host)
        self.history_metrics.pack(fill="x", pady=(0, 14))
        tools = self.ui.frame(host)
        tools.pack(fill="x", pady=(0, 12))
        self._label(tools, "Search by hero", role="secondary").pack(anchor="w")
        self.history_search = self.ui.entry(tools, self.history_query)
        self.history_search.pack(side="left", fill="x", expand=True, pady=6)
        self._button(tools, "Export anonymous summary…", self.export_community_summary).pack(side="right", padx=(12, 0))
        self._button(tools, "Export JSON…", self.export_history).pack(side="right", padx=(12, 0))
        self.history_table = ttk.Treeview(host, columns=("date", "hero", "rank", "source"),
                                         show="headings", style="Tracker.Treeview", height=6, selectmode="browse")
        for key, title, width in (("date", "First tracked", 155), ("hero", "Hero", 220),
                                   ("rank", "Placement", 90), ("source", "Source", 85)):
            self.history_table.heading(key, text=title, command=lambda key=key: self._sort_history(key))
            self.history_table.column(key, width=width, minwidth=60, stretch=True)
        self.history_table.pack(fill="x", pady=(0, 10))
        self.history_table.bind("<<TreeviewSelect>>", lambda event: self._history_selected())
        self._label(host, "Times are first tracked, not verified match starts. Unknown placements are excluded from ranked aggregates.",
                    role="secondary", size=11, wraplength=630).pack(fill="x", pady=8)
        self.history_details = self._text(host, 11)
        self.history_details.pack(fill="both", expand=True)
        controls = self.ui.frame(host)
        controls.pack(fill="x", pady=10)
        self._label(controls, "Manual placement (1–8)").pack(side="left")
        self.ui.entry(controls, self.rank_value, 3).pack(side="left", padx=8)
        self._button(controls, "Save correction", self.save_rank).pack(side="left")
        self._label(host, "", role="warning", textvariable=self.feedback_value, wraplength=640).pack(fill="x")
        self._history_refresh(force=True)

    def _sort_history(self, key):
        self.history_sort = "rank" if key == "rank" else "hero" if key == "hero" else "date"
        self._history_refresh(force=True)

    @staticmethod
    def _date(value):
        try:
            return datetime.fromisoformat(value).astimezone().strftime("%d %b %H:%M")
        except (ValueError, TypeError):
            return value[:16]

    def _history_refresh(self, force=False):
        if self.current_view != "history" or not hasattr(self, "history_table") or not self.history_table.winfo_exists():
            return
        try:
            rows = self.history.recent(200) if self.history else []
            heroes = self.history.by_hero() if self.history else []
            calibration = self.history.calibration() if self.history else {"samples": 0}
        except Exception as exc:
            self.feedback_value.set(f"History read failed: {exc}")
            return
        self._history_rows = rows
        query = self.history_query.get().casefold()
        filtered = [row for row in rows if query in self._name(row["hero"]).casefold()]
        if self.history_sort == "rank":
            filtered.sort(key=lambda row: (row["placement"] is None, row["placement"] or 99))
        elif self.history_sort == "hero":
            filtered.sort(key=lambda row: self._name(row["hero"]).casefold())
        self.history_table.delete(*self.history_table.get_children())
        for row in filtered:
            source = "Manual" if row["placement_source"] == "manual" else "Observed" if row["placement"] is not None else "Incomplete"
            self.history_table.insert("", "end", iid=row["id"], values=(
                self._date(row["tracked_at"]), self._name(row["hero"]), number(row["placement"]), source))
        for child in self.history_metrics.winfo_children():
            child.destroy()
        tracked, ranked, average, rate = history_totals(heroes)
        for value, label in ((tracked, "Tracked"), (ranked, "Ranked"),
                             (f"{average:.2f}" if average is not None else "—", "Average placement"),
                             (f"{rate:.0%}" if rate is not None else "—", "Top 4")):
            item = self.ui.frame(self.history_metrics, padx=10)
            item.pack(side="left", expand=True, fill="x")
            self._label(item, str(value), size=22, weight="bold").pack(anchor="w")
            self._label(item, label, size=11, role="secondary").pack(anchor="w")
        if calibration["samples"]:
            self._label(self.history_metrics,
                        f"Prediction calibration · {calibration['samples']} logged outcomes · predicted {calibration['predicted']:.0%} / actual {calibration['actual']:.0%} · Brier {calibration['brier']:.3f}",
                        size=10, role="secondary", wraplength=640).pack(fill="x", pady=(8, 0))
        else:
            self._label(self.history_metrics,
                        "Prediction calibration appears after a Power.log-unambiguous combat outcome; uncertain fights are excluded.",
                        size=10, role="secondary", wraplength=640).pack(fill="x", pady=(8, 0))
        if filtered:
            selected = self.selected_match if any(row["id"] == self.selected_match for row in filtered) else filtered[0]["id"]
            self.selected_match = selected
            self.history_table.selection_set(selected)
            self._history_selected()
        else:
            self.selected_match = ""
            self._set_text(self.history_details, [("No matching games." if rows else "No recorded games yet.", "heading"),
                                                 ("Clear the search, or finish a tracked Battlegrounds match.", "muted")])

    def _history_selected(self):
        selection = self.history_table.selection()
        if not selection or not self.history:
            return
        self.selected_match = selection[0]
        row = next((row for row in self._history_rows if row["id"] == self.selected_match), None)
        if not row:
            return
        lines = [(self._name(row["hero"]), "heading"),
                 (f"Placement {number(row['placement'])} · source {row['placement_source']} · {row['result'] or 'unfinished / unknown'}", "muted")]
        review = self.history.review(row["id"])
        if review:
            lines.append(("Post-match review · recorded observations only", "heading"))
            lines.append((f"Observed rounds {review['observed_rounds']} · highest recorded tier {number(review['highest_tier'])}", "muted"))
            if review["peak"]:
                peak = review["peak"]
                lines.append((f"Peak recorded board: R{peak['round']} · {peak['attack']}/{peak['board_health']} total stats", ""))
            lines.append(("Board-change timeline", "heading"))
            for item in review["timeline"]:
                change = "" if item["attack_change"] is None else f" · Δ {item['attack_change']:+}/{item['health_change']:+}"
                added = ", ".join(self._name(card_id) for card_id in item["added"])
                removed = ", ".join(self._name(card_id) for card_id in item["removed"])
                movement = (f" · + {added}" if added else "") + (f" · − {removed}" if removed else "")
                lines.append((f"R{item['round']} {item['phase']} · Tier {number(item['tier'])} · board {item['attack']}/{item['board_health']}{change}{movement}", "muted"))
        for snap in self.history.detail(row["id"]):
            lines.append((f"Round {snap['round']} · {snap['phase']} · Tier {snap['tier']} · Health {number(snap['health'])} · Gold {number(snap['gold'])}", "heading"))
            for m in snap["board"]:
                lines.append((f"{self._name(m['card_id'])}  {number(m['attack'])}/{number(m['health'])}", ""))
            for opponent, board in snap["opponents"].items():
                names = ", ".join(f"{self._name(m['card_id'])} {number(m['attack'])}/{number(m['health'])}" for m in board)
                lines.append((f"Opponent {opponent} · seen R{snap['opponent_rounds'].get(opponent, '?')}: {names}", "muted"))
        self._set_text(self.history_details, lines)

    def show_history(self):
        self.show_view("history")

    def save_rank(self):
        try:
            if not self.history or not self.selected_match:
                raise ValueError("Select a recorded match first.")
            self.history.set_placement(self.selected_match, int(self.rank_value.get()))
            self.feedback_value.set("Saved with manual provenance.")
            self._history_refresh(force=True)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.feedback_value.set(f"Could not save: {exc}")

    def export_history(self):
        if not self.history:
            self.feedback_value.set("History storage is unavailable.")
            return
        target = filedialog.asksaveasfilename(parent=self.root, title="Export local match history",
                                              defaultextension=".json", initialfile="battlegrounds-history.json")
        if target:
            try:
                Path(target).write_text(json.dumps(self.history.export(), indent=2, ensure_ascii=False), encoding="utf-8")
                self.feedback_value.set(f"Exported to {target}")
            except (OSError, sqlite3.Error) as exc:
                self.feedback_value.set(f"Export failed: {exc}")

    def export_community_summary(self):
        if not self.history:
            self.feedback_value.set("History storage is unavailable.")
            return
        target = filedialog.asksaveasfilename(parent=self.root, title="Export anonymous community summary",
                                              defaultextension=".json", initialfile="open-battlegrounds-anonymous-summary.json")
        if target:
            try:
                Path(target).write_text(json.dumps(self.history.community_summary(), indent=2, ensure_ascii=False), encoding="utf-8")
                self.feedback_value.set("Exported aggregate-only summary. Nothing was uploaded.")
            except (OSError, sqlite3.Error) as exc:
                self.feedback_value.set(f"Anonymous export failed: {exc}")

    def _build_coach(self):
        host = self.area.inner
        self._label(host, "Local-only decision support from observed logs. It never clicks, moves, or inspects the game window.",
                    role="secondary", wraplength=640).pack(anchor="w", pady=(0, 10))
        actions = self.ui.frame(host)
        actions.pack(fill="x", pady=(0, 10))
        self.position_button = self._button(actions, "Compare local board positions", self.analyze_positioning)
        self.position_button.pack(side="left")
        self.position_status = self._label(actions, "", role="secondary", wraplength=430)
        self.position_status.pack(side="left", padx=10)
        self.coach_listing = self._text(host, 30)
        self.coach_listing.pack(fill="both", expand=True)
        self._coach_refresh()

    def analyze_positioning(self):
        own, enemy, tiers, opponent = self._combat_inputs()
        if not own or not enemy:
            if hasattr(self, "position_status"):
                self.position_status.configure(text="Need both observed boards before local position comparison can run.")
            return
        self.positioning = None
        self._position_key = model_key(own, enemy, self.cards, tiers, True, self._combat_age(opponent), True)
        self._position_generation = self._position_worker.submit(own, enemy, self.cards, tiers, self._combat_age(opponent))
        if hasattr(self, "position_status"):
            self.position_status.configure(text="Comparing up to 15 legal local arrangements…")
        self._coach_refresh()

    def _coach_refresh(self):
        if self.current_view != "coach" or not hasattr(self, "coach_listing") or not self.coach_listing.winfo_exists():
            return
        own, enemy, tiers, opponent = self._combat_inputs()
        lines = [("TURN PLAN · observed costs only", "heading")]
        lines.extend((line, "") for line in turn_plan(self.state, self.cards))
        lines.append(("", ""))
        lines.append(("COMBAT EXPLANATION · observed factors, not hidden-board inference", "heading"))
        lines.extend((line, "") for line in combat_reasons(own, enemy, self.odds, self.cards))
        lines.append(("", ""))
        lines.append(("COVERAGE INSPECTOR", "heading"))
        inspected = coverage_inspector(own + enemy, self.cards)
        if inspected:
            labels = {"missing": "Missing/invalid data", "dynamic": "Unimplemented dynamic mechanics", "text": "Unimplemented card text"}
            for category, blockers in inspected.items():
                lines.append((labels[category], "warning"))
                lines.extend((f"• {blocker}", "warning") for blocker in blockers)
        else:
            lines.append(("Current observed board is covered by the full-rules subset.", ""))
        lines.append(("", ""))
        lines.append(("POSITIONING SANDBOX · local simulation only", "heading"))
        if self.positioning:
            names = {minion.entity_id: self._name(minion.card_id) for minion in own}
            current = " → ".join(names.get(identifier, identifier) for identifier in self.positioning.current.order)
            best = " → ".join(names.get(identifier, identifier) for identifier in self.positioning.best.order)
            lines.extend([(self.positioning.note, "secondary"),
                          (f"Current checked order · {self.positioning.current.win:.1%} win · {current}", ""),
                          (f"Best checked order · {self.positioning.best.win:.1%} win · {best}", "")])
            alternatives = sorted(self.positioning.options, key=lambda option: option.win + option.tie*.5, reverse=True)[:4]
            for option in alternatives:
                order = " → ".join(names.get(identifier, identifier) for identifier in option.order)
                lines.append((f"{option.win:.1%} win / {option.loss:.1%} loss / {option.tie:.1%} tie · {order}", "secondary"))
            if hasattr(self, "position_status"):
                self.position_status.configure(text=f"Compared {len(self.positioning.options)} local arrangements.")
        else:
            lines.append(("Choose Compare local board positions after both boards are observed.", "secondary"))
        if self.history and self.state.game_id and opponent:
            timeline = self.history.opponent_timeline(self.state.game_id, opponent)
            if timeline:
                lines.append(("", ""))
                lines.append((f"OPPONENT TIMELINE · {self._opponent_name(opponent)}", "heading"))
                for item in timeline[-5:]:
                    changed = []
                    if item["added"]: changed.append(f"+{len(item['added'])} cards")
                    if item["removed"]: changed.append(f"−{len(item['removed'])} cards")
                    lines.append((f"R{item['round']} · {item['count']} minions · {item['attack']}/{item['health']}" + (" · " + ", ".join(changed) if changed else ""), ""))
        self._set_text(self.coach_listing, lines)

    def _build_reference(self):
        host = self.area.inner
        self._label(host, "Search the local Battlegrounds pool by name, tribe, mechanic, or model-support badge.", role="secondary").pack(anchor="w")
        self.reference_search = self.ui.entry(host, self.reference_query)
        self.reference_search.pack(fill="x", pady=(6, 12))
        filters = self.ui.frame(host)
        filters.pack(fill="x", pady=(0, 10))
        for label, variable, width in (("Tribe", self.reference_tribe, 14), ("Mechanic", self.reference_mechanic, 18),
                                       ("Support", self.reference_support, 18)):
            group = self.ui.frame(filters)
            group.pack(side="left", padx=(0, 8))
            self._label(group, label, size=10, role="secondary").pack(anchor="w")
            entry = self.ui.entry(group, variable, width=width)
            entry.pack()
        tiers = self.ui.frame(host)
        tiers.pack(fill="x", pady=(0, 10))
        for tier in range(1, 7):
            button = self.ui.button(tiers, f"Tier {tier}", lambda tier=tier: self._select_tier(tier),
                                    surface="selected" if tier == self.reference_tier else "button")
            button.pack(side="left", padx=(0, 6))
        self.reference_count = self._label(host, "", role="secondary", wraplength=620)
        self.reference_count.pack(fill="x", pady=10)
        self.reference_listing = self._text(host, 23)
        self.reference_listing.pack(fill="both", expand=True)
        self._reference_refresh()

    def _select_tier(self, tier):
        self.reference_tier = tier
        query_focus = self.reference_search == self.root.focus_get()
        self.show_view("reference", focus=False)
        if query_focus:
            self.reference_search.focus_set()

    def _reference_refresh(self):
        if self.current_view != "reference" or not hasattr(self, "reference_listing") or not self.reference_listing.winfo_exists():
            return
        cards = browser_cards(self.cards, self.reference_query.get(), self.reference_tier,
                              self.reference_tribe.get(), self.reference_mechanic.get(), self.reference_support.get())
        self.reference_count.configure(text=f"{len(cards)} tier-{self.reference_tier} locally cached pool-reference cards · Base stats, not live buffs.\nFilters use only cached metadata; lobby tribe exclusions are not inferred. {self.card_status}")
        lines, category = [], None
        for card in cards:
            if card.minion_type != category:
                category = card.minion_type
                lines.append((category.replace("_", " ").title(), "heading"))
            badge = card_support(card)
            mechanics = ", ".join(card.mechanics) if card.mechanics else "No listed mechanics"
            lines.append((f"{card.name}   {number(card.attack)} ATK / {number(card.health)} HP · {badge}", ""))
            lines.append((f"  {mechanics} · {card.text or 'No card text cached'}", "muted"))
        if not cards:
            lines = [("No matching cached cards.", "heading"),
                     ("Clear the search or choose another tier. Missing metadata never becomes a made-up card.", "muted")]
        self._set_text(self.reference_listing, lines)

    def _build_settings(self):
        host = self.area.inner
        self._heading(host, "Appearance")
        appearance = self.ui.frame(host, "panel", padx=14, pady=10)
        appearance.pack(fill="x", pady=(0, 18))
        self._label(appearance, "Color appearance", weight="bold", surface="panel").pack(anchor="w")
        choices = self.ui.frame(appearance, "panel")
        choices.pack(fill="x", pady=8)
        for theme in ("dark", "light"):
            self.ui.button(choices, theme.title(), lambda theme=theme: self.set_theme(theme),
                           surface="selected" if self.preferences["theme"] == theme else "button").pack(side="left", padx=(0, 8))
        self._label(appearance, "Window opacity · Tk fades the whole native window", surface="panel").pack(anchor="w", pady=(8, 0))
        self.opacity_scale = tk.Scale(appearance, from_=85, to=100, orient="horizontal",
                                      bg=self.ui.colors["panel"], fg=self.ui.colors["text"],
                                      activebackground=self.ui.colors["accent"], troughcolor=self.ui.colors["line"],
                                      highlightbackground=self.ui.colors["panel"], highlightcolor=self.ui.colors["accent"],
                                      font=(FONT, 11), relief="flat", length=280, borderwidth=0,
                                      command=self._set_opacity)
        self.opacity_scale.set(round(max(.85, self.preferences["opacity"])*100))
        self.opacity_scale.pack(anchor="w", pady=8)
        self._button(appearance, "Use opaque window" if not self.preferences["reduce_transparency"] else "Allow transparency",
                     self.toggle_transparency).pack(anchor="w", pady=5)
        self._label(appearance, "No decorative animations. Updates are immediate.", role="secondary", surface="panel").pack(anchor="w", pady=5)
        self._heading(host, "Overlay")
        controls = self.ui.frame(host, "panel", padx=14, pady=12)
        controls.pack(fill="x", pady=(0, 18))
        self._button(controls, "Use game-side overlay", self.toggle_game_overlay).pack(anchor="w", pady=4)
        self._label(controls, "Game-side overlay preset", weight="bold", surface="panel").pack(anchor="w", pady=(8, 2))
        presets = self.ui.frame(controls, "panel")
        presets.pack(anchor="w", pady=(0, 5))
        for preset, title in (("auto", "Auto"), ("recruit", "Recruit"), ("combat", "Combat"), ("minimal", "Minimal")):
            self.ui.button(presets, title, lambda preset=preset: self.set_game_preset(preset),
                           surface="selected" if preset == self.game_preset else "button").pack(side="left", padx=(0, 6))
        self._button(controls, "Compact mode", self.toggle_compact).pack(anchor="w", pady=4)
        self._button(controls, "Stop floating above other apps" if self.preferences["topmost"] else "Float above other apps",
                     self.toggle_topmost).pack(anchor="w", pady=4)
        self.model_button = self._button(controls, "Turn off automatic combat estimate" if self.board_only else "Turn on automatic combat estimate", self.toggle_model)
        self.model_button.pack(anchor="w", pady=4)
        self._label(controls, "Auto switches the rail between Recruit planning and Combat scouting. Recruit emphasizes logged affordability and shop heuristics; Combat emphasizes chance, coverage and last-observed threats. Minimal keeps only the core metrics. The model publishes a quick result then refines it; valid boards with excluded effects show an explicit incomplete baseline.\n⌘⇧H shows/hides the window. C toggles compact mode when focused.",
                    role="secondary", surface="panel", wraplength=620).pack(fill="x", pady=8)
        self._heading(host, "Log diagnostics & privacy")
        self.diagnostics = self._label(host, "", role="secondary", wraplength=630)
        self.diagnostics.pack(fill="x", pady=8)
        self._label(host, "No uploads. Your existing journal and log files are retained.\nDemo mode uses temporary history and does not save preferences.",
                    role="secondary", wraplength=620).pack(fill="x", pady=10)
        tools = self.ui.frame(host)
        tools.pack(fill="x", pady=8)
        self._button(tools, "Reset window position", self.reset_position).pack(side="left")
        self._button(tools, "Reset appearance", self.reset_appearance).pack(side="left", padx=8)

    def set_theme(self, theme):
        if theme not in ("dark", "light"):
            return
        view = self.current_view
        self.card_images.preview.hide()
        self.preferences["theme"] = theme
        self.ui = UI(theme)
        self.card_images.ui = self.ui
        self._build_shell()
        self.show_view(view, focus=False)
        self._save()

    def set_game_preset(self, preset):
        if preset not in GAME_PRESETS:
            return
        self.game_preset = preset
        self.preferences["game_preset"] = preset
        if self.game_overlay:
            if hasattr(self, "preset_button") and self.preset_button.winfo_exists():
                self.preset_button.set_text(self._preset_label())
            self._render()
        elif self.current_view == "settings":
            self.show_view("settings", focus=False)
        self._save()

    def cycle_game_preset(self):
        index = (GAME_PRESETS.index(self.game_preset) + 1) % len(GAME_PRESETS)
        self.set_game_preset(GAME_PRESETS[index])

    def _set_opacity(self, value):
        self.preferences["opacity"] = round(max(.85, min(1., float(value)/100)), 2)
        self.root.wm_attributes("-alpha", 1. if self.preferences["reduce_transparency"] else self.preferences["opacity"])
        self._save()

    def change_opacity(self, delta):
        self._set_opacity((self.preferences["opacity"] + delta)*100)

    def toggle_transparency(self):
        self.preferences["reduce_transparency"] = not self.preferences["reduce_transparency"]
        self.root.wm_attributes("-alpha", 1. if self.preferences["reduce_transparency"] else max(.85, self.preferences["opacity"]))
        self._save()
        self.show_view("settings")

    def toggle_topmost(self):
        self.preferences["topmost"] = not self.preferences["topmost"]
        self.root.wm_attributes("-topmost", self.preferences["topmost"])
        self._save()
        self.show_view("settings")

    def reset_appearance(self):
        self.preferences.update(opacity=.96, reduce_transparency=False)
        self.root.wm_attributes("-alpha", .96)
        self.set_theme("dark")

    def reset_position(self):
        if self.game_overlay:
            self.preferences.update(game_x=None, game_y=None)
            width, height, x, y = self._game_overlay_geometry()
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        else:
            self.root.geometry("+30+60")
        self._save()

    def toggle_game_overlay(self):
        """Switch between the detailed tracker and a screen-edge game rail."""
        self.card_images.preview.hide()
        if self.game_overlay:
            self.game_overlay = False
            self.preferences["game_overlay"] = False
            self.root.minsize(800, 580)
            self.root.geometry(f"{self.preferences['width']}x{self.preferences['height']}+{self.preferences['x']}+{self.preferences['y']}")
        else:
            if self.compact:
                self.toggle_compact()
            self.preferences.update(x=max(0, self.root.winfo_x()), y=max(0, self.root.winfo_y()),
                                    width=max(800, self.root.winfo_width()), height=max(580, self.root.winfo_height()))
            self.game_overlay = True
            self.preferences["game_overlay"] = True
            self.root.minsize(GAME_OVERLAY_WIDTH, 560)
            width, height, x, y = self._game_overlay_geometry()
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.current_view = "live"
        self._build_shell()
        self.show_view("live", focus=False)
        self._save()

    def toggle_visibility(self):
        self.card_images.preview.hide()
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.lift()
            self.root.wm_attributes("-topmost", self.preferences["topmost"])
        else:
            self.root.withdraw()

    def _compact_key(self, event):
        if self.game_overlay:
            return "break"
        if isinstance(event.widget, (tk.Entry, tk.Text, ttk.Treeview)):
            return
        self.toggle_compact()
        return "break"

    def toggle_compact(self):
        if self.game_overlay:
            return
        self.card_images.preview.hide()
        self.compact = not self.compact
        if self.compact:
            self.preferences.update(width=max(800, self.root.winfo_width()), height=max(580, self.root.winfo_height()))
            self.body.pack_forget()
            self.footer_frame.pack_forget()
            self.compact_summary.pack(fill="x")
            self.mode_label.pack_forget()
            self.compact_button.set_text("Expand")
            self.root.minsize(480, 96)
            self.root.geometry("480x96")
        else:
            self.compact_summary.pack_forget()
            self.body.pack(fill="both", expand=True)
            self.footer_frame.pack(fill="x")
            self.mode_label.pack(side="right", padx=12)
            self.compact_button.set_text("Compact")
            self.root.minsize(800, 580)
            self.root.geometry(f"{self.preferences['width']}x{self.preferences['height']}")
        self.root.update_idletasks()
        self._save()

    def _save(self):
        self.preferences.update(collapsed=sorted(self.collapsed), compact=self.compact,
                                game_overlay=self.game_overlay, game_preset=self.game_preset, ui_version=3)
        if self.game_overlay:
            self.preferences.update(game_x=max(0, self.root.winfo_x()), game_y=max(0, self.root.winfo_y()))
        elif not self.compact and self.root.winfo_width() > 100:
            self.preferences.update(x=max(0, self.root.winfo_x()), y=max(0, self.root.winfo_y()))
            self.preferences.update(width=max(800, self.root.winfo_width()), height=max(580, self.root.winfo_height()))
        try:
            self.settings.save(self.preferences)
        except OSError as exc:
            logging.warning("Cannot save overlay settings: %s", exc)

    def _scroll(self, event):
        if not isinstance(event.widget, (tk.Text, tk.Entry, ttk.Treeview)) and not self.compact:
            self.card_images.preview.hide()
            if not self.game_overlay:
                self.area.canvas.yview_scroll(-int(event.delta or 0), "units")

    def _escape(self, event=None):
        if self.card_images.preview.visible or self.card_images.preview._show_timer:
            return self.card_images.preview.dismiss_preview()
        self.close()
        return "break"

    def _configured(self, event):
        if event.widget != self.root or self.compact or self.game_overlay or self._closed:
            return
        narrow = event.width < 940
        if narrow != self._narrow:
            self._narrow = narrow
            if self._resize_timer:
                self.root.after_cancel(self._resize_timer)
            self._resize_timer = self.root.after(120, self._responsive)

    def _responsive(self):
        self._resize_timer = None
        if self.current_view == "live":
            self._render_live()

    def _drag_start(self, event):
        self.card_images.preview.hide()
        self._drag_offset = (event.x_root-self.root.winfo_x(), event.y_root-self.root.winfo_y())

    def _drag(self, event):
        x, y = self._drag_offset
        self.root.geometry(f"+{max(0, event.x_root-x)}+{max(0, event.y_root-y)}")

    def _resize_start(self, event):
        self.card_images.preview.hide()
        self._resize_origin = (event.x_root, event.y_root, self.root.winfo_width(), self.root.winfo_height())

    def _resize(self, event):
        x, y, width, height = self._resize_origin
        self.root.geometry(f"{max(800, width+event.x_root-x)}x{max(580, height+event.y_root-y)}")

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._save()
        for timer in (self._timer, self._resize_timer):
            if timer:
                self.root.after_cancel(timer)
        self.hotkey.close()
        self.card_images.close()
        self._worker.close()
        self._position_worker.close()
        if self.on_close:
            self.on_close()
        self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            if not self._closed:
                self.close()
