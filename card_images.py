"""On-demand public card art, bounded local cache and native hover previews.

Network/decoding work runs in daemon workers. PhotoImages and widgets are ONLY
created on Tk's main thread. Artwork is Blizzard's, not part of our MIT license.
"""
from __future__ import annotations

import io
import json
import queue
import re
import threading
import time
import tkinter as tk
import weakref
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ui import FONT

try:
    from PIL import Image, ImageDraw, ImageOps, ImageTk
except ImportError:  # Keep the existing tracker usable without the optional dependency.
    Image = ImageDraw = ImageOps = ImageTk = None

ART_ORIGIN = "https://art.hearthstonejson.com"
MAX_BYTES = 3 * 1024 * 1024
MAX_ASSETS = 96
TTL = 7 * 86400
VALID_ID = re.compile(r"[A-Za-z0-9_]{1,100}\Z")
VALID_LOCALES = {"enUS", "deDE", "esES", "esMX", "frFR", "itIT", "jaJP", "koKR",
                 "plPL", "ptBR", "ruRU", "thTH", "zhCN", "zhTW"}


def image_url(card_id, kind, locale="enUS"):
    """Reject path traversal/URLs; never send a user's entity or account name."""
    if not VALID_ID.fullmatch(card_id) or locale not in VALID_LOCALES:
        raise ValueError("Invalid card ID or locale")
    if kind == "portrait":
        return f"{ART_ORIGIN}/v1/256x/{card_id}.jpg"
    if kind == "full":
        return f"{ART_ORIGIN}/v1/render/latest/{locale}/512x/{card_id}.png"
    raise ValueError("Unknown image variant")


def decode_image(payload):
    if Image is None:
        raise ValueError("Install Pillow to display images")
    if len(payload) > MAX_BYTES:
        raise ValueError("Image response is too large")
    with Image.open(io.BytesIO(payload)) as source:
        if source.format not in {"PNG", "JPEG", "WEBP"} or source.width * source.height > 2048 * 2048:
            raise ValueError("Unsupported or oversized image")
        source.load()
        return source.convert("RGBA")


def oval_image(source, size=(56, 74)):
    """A genuine art crop, antialiased in a game-style oval—not invented art."""
    scale = 3
    large = (size[0]*scale, size[1]*scale)
    fitted = ImageOps.fit(source, large, method=Image.Resampling.LANCZOS)
    mask = Image.new("L", large)
    ImageDraw.Draw(mask).ellipse((0, 0, large[0]-1, large[1]-1), fill=255)
    fitted.putalpha(mask)
    return fitted.resize(size, Image.Resampling.LANCZOS)


@dataclass
class Asset:
    image: object = None
    message: str = "Loading artwork…"
    retry_at: float = 0
    source: str = ""


class ImageCache:
    """Bounded workers, request deduplication, failure backoff and offline reuse."""
    def __init__(self, directory, *, network=True, opener=urlopen):
        self.directory, self.network, self.opener = Path(directory), network, opener
        self._items = OrderedDict()
        self._metadata = {}
        self._pending, self._closed = set(), threading.Event()
        self._lock = threading.RLock()
        self._sequence = 0
        self._requests, self._changes = queue.PriorityQueue(maxsize=64), queue.Queue()
        self._threads = [threading.Thread(target=self._work, name=f"card-art-{i}", daemon=True) for i in range(2)]
        for worker in self._threads:
            worker.start()

    @staticmethod
    def key(card_id, kind, locale="enUS"):
        return card_id, kind, locale if kind == "full" else "art"

    def path(self, card_id, kind, locale="enUS"):
        image_url(card_id, kind, locale)
        return self.directory / (locale if kind == "full" else "art") / f"{kind}-{card_id}.img"

    def register(self, card):
        if card and type(card.render_dbf_id) is int and card.render_dbf_id > 0:
            with self._lock:
                self._metadata[card.card_id] = card.render_dbf_id, card.is_golden

    def _fetch(self, url):
        request = Request(url, headers={"User-Agent": "OpenBattlegroundsOverlay/2.0"})
        with self.opener(request, timeout=6) as response:
            payload = response.read(MAX_BYTES+1)
            fallback = response.headers.get("X-Image-Fallback", "")
        return payload, fallback

    def request(self, card_id, kind, locale="enUS"):
        try:
            image_url(card_id, kind, locale)
        except ValueError:
            return Asset(message="Artwork unavailable for this card")
        if Image is None:
            return Asset(message="Install Pillow for card images")
        if card_id.startswith("DEMO_"):
            return Asset(message="Synthetic training card · no game artwork")
        key = self.key(card_id, kind, locale)
        with self._lock:
            value = self._items.get(key)
            if value:
                self._items.move_to_end(key)
                if value.image is not None or value.retry_at > time.monotonic():
                    return value
            if self._closed.is_set():
                return Asset(message="Artwork loading stopped")
            if key not in self._pending:
                try:
                    self._sequence += 1
                    self._requests.put_nowait((0 if kind == "full" else 1, self._sequence, (card_id, kind, locale)))
                    self._pending.add(key)
                except queue.Full:
                    return Asset(message="Artwork queue busy; will retry")
            return Asset()

    def _load(self, card_id, kind, locale):
        path = self.path(card_id, kind, locale)
        cached = None
        provenance = {}
        try:
            if path.stat().st_size <= MAX_BYTES:
                cached = decode_image(path.read_bytes())
                try:
                    provenance = json.loads(path.with_suffix(path.suffix+".source.json").read_text())
                    if not isinstance(provenance, dict):
                        provenance = {}
                except (OSError, ValueError):
                    pass
                if not self.network or time.time()-path.stat().st_mtime < TTL:
                    return Asset(cached, provenance.get("message", "Cached artwork"), source=provenance.get("source", ""))
        except (OSError, ValueError, Image.DecompressionBombError):
            pass  # Corrupt cache gets a fresh fetch; unavailable disk still permits memory use.
        if not self.network:
            return Asset(message="No cached artwork · offline", retry_at=time.monotonic()+60)
        url = image_url(card_id, kind, locale)
        try:
            message = "HearthstoneJSON · base card render" if kind == "full" else "HearthstoneJSON · card art"
            try:
                payload, fallback = self._fetch(url)
            except HTTPError as exc:
                with self._lock:
                    metadata = self._metadata.get(card_id)
                if exc.code != 404 or kind != "full" or not metadata:
                    raise
                dbf_id, golden = metadata
                url = f"https://hsbg.cards/api/v1/cards/{dbf_id}/image" + ("?golden=true" if golden else "")
                payload, fallback = self._fetch(url)
                message = "BG Card Database · English base render"
                if fallback:
                    message += " · golden artwork unavailable; normal render shown"
            decoded = decode_image(payload)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix+".download")
                temporary.write_bytes(payload)
                temporary.replace(path)
                # Provenance remains beside the runtime cache, not a bundled game asset.
                path.with_suffix(path.suffix+".source.json").write_text(json.dumps({
                    "source": url, "fetched_at": time.time(), "copyright": "Blizzard Entertainment",
                    "variant": kind, "card_id": card_id, "locale": locale if kind == "full" else None, "message": message,
                }), encoding="utf-8")
            except OSError:
                return Asset(decoded, message+" · disk cache unavailable", source=url)
            return Asset(decoded, message, source=url)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            if cached is not None:
                return Asset(cached, provenance.get("message", "Cached artwork")+" · refresh unavailable", source=provenance.get("source", ""))
            message = "Artwork not published for this card" if isinstance(exc, HTTPError) and exc.code == 404 else "Artwork unavailable · offline or download failed"
            return Asset(message=message, retry_at=time.monotonic()+60)

    def _work(self):
        while not self._closed.is_set():
            try:
                _, _, args = self._requests.get(timeout=.2)
            except queue.Empty:
                continue
            key = self.key(*args)
            try:
                value = self._load(*args)
            except Exception:
                value = Asset(message="Artwork could not be decoded", retry_at=time.monotonic()+60)
            with self._lock:
                self._pending.discard(key)
                if not self._closed.is_set():
                    self._items[key] = value
                    self._items.move_to_end(key)
                    while len(self._items) > MAX_ASSETS:
                        self._items.popitem(last=False)
                    self._changes.put(key)

    def changes(self):
        changed = set()
        while True:
            try:
                changed.add(self._changes.get_nowait())
            except queue.Empty:
                return changed

    def close(self):
        self._closed.set()
        for worker in self._threads:
            worker.join(timeout=.25)


class CardImages:
    """Main-thread coordinator; cache decoded PhotoImages across live rerenders."""
    def __init__(self, root, ui, cache):
        self.root, self.ui, self.cache = root, ui, cache
        self.tiles, self.photos = weakref.WeakSet(), OrderedDict()
        self.preview = CardPreview(self)

    def photo(self, card_id, kind, locale, portrait_size=(56, 74)):
        asset = self.cache.request(card_id, kind, locale)
        if asset.image is None:
            return None, asset.message
        key = (*self.cache.key(card_id, kind, locale), portrait_size if kind == "portrait" else None, id(asset.image))
        if key not in self.photos:
            image = (oval_image(asset.image, portrait_size) if kind == "portrait"
                     else ImageOps.contain(asset.image, (256, 384), Image.Resampling.LANCZOS))
            self.photos[key] = ImageTk.PhotoImage(image, master=self.root)
            while len(self.photos) > MAX_ASSETS:
                self.photos.popitem(last=False)
        self.photos.move_to_end(key)
        return self.photos[key], asset.message

    def poll(self):
        changed = self.cache.changes()
        if changed:
            for tile in list(self.tiles):
                if tile.winfo_exists() and self.cache.key(tile.card_id, "portrait", tile.locale) in changed:
                    tile.paint()
            if self.preview.visible:
                self.preview.refresh()

    def find(self, key):
        return next((tile for tile in self.tiles if tile.winfo_exists() and tile.action_key == key), None)

    def restore(self, focus_key=None):
        focused = self.find(focus_key) if focus_key else None
        if focused:
            focused.focus_set()
        if self.preview.visible:
            replacement = self.find(self.preview.key)
            if replacement:
                self.preview.anchor = replacement
                self.preview.refresh()
            else:
                self.preview.hide()

    def close(self):
        self.preview.close()
        self.cache.close()
        self.photos.clear()


class CardPortrait(tk.Canvas):
    """Compact oval art with live numeric badges and a named text fallback."""
    def __init__(self, parent, manager, minion, card, locale, surface, board_key, compact=False):
        self.manager, self.minion, self.card = manager, minion, card
        self.card_id, self.locale = minion.card_id, locale
        self.name = card.name if card else minion.name or minion.card_id or "Unknown minion"
        self.compact = compact
        if compact:
            self.canvas_size, self.art_size = (46, 66), (36, 47)
            self.art_box, self.tier_box = (4, 2, 42, 51), (16, 0, 30, 14)
            self.badges, self.badge_box, self.badge_y = (9, 37), 10, (44, 64)
        else:
            self.canvas_size, self.art_size = (76, 100), (56, 74)
            self.art_box, self.tier_box = (9, 3, 67, 80), (28, 0, 48, 18)
            self.badges, self.badge_box, self.badge_y = (15, 61), 14, (68, 96)
        manager.cache.register(card)
        self.action_key = ("portrait", board_key, minion.entity_id)
        c = manager.ui.colors
        super().__init__(parent, width=self.canvas_size[0], height=self.canvas_size[1], bg=c[surface], borderwidth=0,
                         highlightthickness=2, highlightbackground=c[surface], highlightcolor=c["accent"],
                         takefocus=True, cursor="hand2")
        self.photo_image = None
        manager.tiles.add(self)
        self.bind("<Enter>", lambda event: manager.preview.schedule(self))
        self.bind("<Leave>", lambda event: manager.preview.schedule_hide())
        self.bind("<FocusIn>", lambda event: manager.preview.schedule(self))
        self.bind("<FocusOut>", lambda event: manager.preview.schedule_hide())
        self.bind("<Button-1>", self.open)
        self.bind("<Return>", self.open)
        self.bind("<space>", self.open)
        self.paint()

    def open(self, event=None):
        self.focus_set()
        self.manager.preview.show(self)
        return "break"

    def paint(self):
        c = self.manager.ui.colors
        self.delete("all")
        self.create_oval(*self.art_box, fill=c["raised"], outline=c["secondary"], width=2)
        self.photo_image, self.art_status = self.manager.photo(self.card_id, "portrait", self.locale, self.art_size)
        if self.photo_image:
            self.create_image(self.canvas_size[0]//2, (self.art_box[1]+self.art_box[3])//2, image=self.photo_image)
            self.create_oval(*self.art_box, outline=c["secondary"], width=2)
        else:
            self.create_text(self.canvas_size[0]//2, (self.art_box[1]+self.art_box[3])//2, text=self.name,
                             width=self.art_box[2]-self.art_box[0]-6, fill=c["text"],
                             font=(FONT, 7 if self.compact else 10), justify="center")
        if self.card and self.card.tier is not None:
            self.create_oval(*self.tier_box, fill=c["button"], outline=c["secondary"])
            self.create_text(self.canvas_size[0]//2, (self.tier_box[1]+self.tier_box[3])//2, text=str(self.card.tier),
                             fill=c["text"], font=(FONT, 7 if self.compact else 9, "bold"))
        # The numeric values are logged stats, never copied from a static render.
        for x, value, fill in ((self.badges[0], self.minion.attack, "#594212"), (self.badges[1], self.minion.health, "#702d36")):
            text = badge_number(value)
            self.create_oval(x-self.badge_box, self.badge_y[0], x+self.badge_box, self.badge_y[1],
                             fill=fill, outline="#d7c89a", width=1)
            self.create_text(x, (self.badge_y[0]+self.badge_y[1])//2, text=text, fill="#ffffff",
                             font=(FONT, 6 if self.compact and len(text) > 3 else 7 if self.compact else 9 if len(text) > 3 else 10, "bold"))


class CardPreview:
    """Non-modal, hoverable, dismissible full-card popover with a text fallback."""
    def __init__(self, manager):
        self.manager, self.root = manager, manager.root
        self.window, self.anchor, self.key = None, None, None
        self._show_timer, self._hide_timer = None, None
        self._suppressed_key, self._hiding, self._closed = None, False, False
        self.photo_image = None

    @property
    def visible(self):
        return self.window is not None and bool(self.window.winfo_exists())

    def _cancel(self, name):
        timer = getattr(self, name)
        if timer:
            try:
                self.root.after_cancel(timer)
            except tk.TclError:
                pass
            setattr(self, name, None)

    def schedule(self, anchor):
        if self._closed or self._hiding:
            return
        self._cancel("_hide_timer")
        self._cancel("_show_timer")
        if self._suppressed_key == anchor.action_key:
            return
        self._show_timer = self.root.after(250, lambda: self.show(anchor))

    def schedule_hide(self):
        if self._closed or self._hiding:
            return
        self._cancel("_show_timer")
        self._cancel("_hide_timer")
        self._hide_timer = self.root.after(160, self._maybe_hide)

    def _inside(self, widget, ancestor):
        while widget:
            if widget == ancestor:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _maybe_hide(self):
        # Usually invoked by this very timer; cancelling also covers a direct
        # dismissal while a duplicate leave callback is still queued.
        self._cancel("_hide_timer")
        if self.visible:
            x, y = self.root.winfo_pointerxy()
            under = self.root.winfo_containing(x, y)
            focus = self.root.focus_get()
            if self._inside(under, self.window) or self._inside(focus, self.window):
                return
            if self.anchor and self.anchor.winfo_exists() and (under == self.anchor or focus == self.anchor):
                return
        self.hide()
        self._suppressed_key = None

    def show(self, anchor):
        self._cancel("_show_timer")
        self._cancel("_hide_timer")
        if self._closed or self._hiding or not anchor.winfo_exists() or self.root.state() == "withdrawn":
            return
        self.anchor, self.key, self._suppressed_key = anchor, anchor.action_key, None
        if not self.visible:
            u, c = self.manager.ui, self.manager.ui.colors
            self.window = tk.Toplevel(self.root, bg=c["panel"])
            self.window.withdraw()
            self.window.overrideredirect(True)
            self.window.wm_attributes("-topmost", True)
            self.window.transient(self.root)
            self.window.title("Card preview")
            host = u.frame(self.window, "panel", padx=10, pady=10, highlightthickness=1, highlightbackground=c["line"])
            host.pack(fill="both", expand=True)
            self.title = u.label(host, "", 12, "bold", surface="panel", wraplength=256)
            self.title.pack(anchor="w")
            # Reserve pixel geometry, not Label character units.
            image_box = u.frame(host, "panel", width=256, height=384)
            image_box.pack(fill="x", pady=6)
            image_box.pack_propagate(False)
            self.image = u.label(image_box, "Loading full card…", surface="panel", wraplength=240)
            self.image.pack(fill="both", expand=True)
            self.stats = u.label(host, "", 11, surface="panel", wraplength=256)
            self.stats.pack(anchor="w")
            self.note = u.label(host, "", 10, role="secondary", surface="panel", wraplength=256)
            self.note.pack(anchor="w", pady=5)
            self.dismiss = u.button(host, "Dismiss · Esc", self.dismiss_preview, surface="button")
            self.dismiss.pack(anchor="w")
            for widget in (self.window, host, self.title, image_box, self.image, self.stats, self.note, self.dismiss, self.dismiss.label):
                widget.bind("<Enter>", lambda event: self._cancel("_hide_timer"), add="+")
                widget.bind("<Leave>", lambda event: self.schedule_hide(), add="+")
            self.window.bind("<Escape>", lambda event: self.dismiss_preview())
        self.refresh()
        self.window.update_idletasks()
        width, height = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        x, y = anchor.winfo_rootx()+anchor.winfo_width()+10, anchor.winfo_rooty()-40
        if x+width > self.root.winfo_screenwidth()-8:
            x = anchor.winfo_rootx()-width-10
        x = max(8, min(x, self.root.winfo_screenwidth()-width-8))
        y = max(28, min(y, self.root.winfo_screenheight()-height-8))
        self.window.geometry(f"+{x}+{y}")
        self.window.deiconify()
        self.window.lift()

    def refresh(self):
        if not self.visible or not self.anchor or not self.anchor.winfo_exists():
            return
        tile = self.anchor
        self.title.configure(text=tile.name)
        self.photo_image, message = self.manager.photo(tile.card_id, "full", tile.locale)
        if self.photo_image:
            self.image.configure(image=self.photo_image, text="")
        else:
            card_text = re.sub(r"<[^>]+>", "", tile.card.text) if tile.card else "Card metadata not cached."
            self.image.configure(image="", text=f"{message}\n\n{tile.name}\n\n{card_text}")
        m = tile.minion
        attack, health = ("—" if v is None else str(v) for v in (m.attack, m.health))
        self.stats.configure(text=f"Logged ATK {attack} · HP {health}")
        context = f"{tile.card.minion_type.title()} · Tier {tile.card.tier}" if tile.card else "Metadata unavailable"
        self.note.configure(text=f"{context}\n{message}\nPrinted base values may lag a game patch.\nOpponent portraits are last observed.\nArtwork © Blizzard Entertainment.")

    def dismiss_preview(self):
        self._suppressed_key = self.key
        self.hide()
        return "break"

    def hide(self):
        self._hiding = True
        try:
            self._cancel("_show_timer")
            self._cancel("_hide_timer")
            window = self.window
            self.window, self.anchor, self.key, self.photo_image = None, None, None, None
            if window is not None and window.winfo_exists():
                window.destroy()
            # Destroying a hoverable popup can emit <Leave>; do not retain its timer.
            self._cancel("_hide_timer")
        finally:
            self._hiding = False

    def close(self):
        self._closed = True
        self.hide()


def badge_number(value):
    """Compact only large badge values; preview always exposes the exact integer."""
    if value is None:
        return "—"
    if abs(value) < 10000:
        return str(value)
    for magnitude, suffix in ((10**12, "T"), (10**9, "B"), (10**6, "M"), (10**3, "k")):
        if abs(value) >= magnitude:
            return f"{value/magnitude:.1f}".rstrip("0").rstrip(".")+suffix
    return str(value)
