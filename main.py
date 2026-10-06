"""Start the macOS overlay, or use --demo without running Hearthstone."""
from __future__ import annotations

import argparse
import logging
import json
import os
import shutil
import sys
import threading
import sqlite3
from pathlib import Path

from cards_db import CardsDatabase
from config import HearthstonePaths, discover_installation, ensure_client_logging, ensure_power_logging
from parser import BattlegroundsParser, PowerLogTailer
from history import HistoryStore


def runtime_resource(relative: str) -> Path:
    """Locate a bundled resource under PyInstaller or beside source files."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative


def application_data_dir() -> Path:
    """Keep packaged-app state writable and separate from temporary bundles."""
    override = os.environ.get("OPEN_BATTLEGROUNDS_DATA_DIR")
    if override:
        return Path(override)
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent / "data"
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path.home() / "Library" / "Application Support"
    data_dir = root / "OpenBattlegroundsOverlay"
    data_dir.mkdir(parents=True, exist_ok=True)
    seed = runtime_resource("data/cards.json")
    target = data_dir / "cards.json"
    if seed.is_file() and not target.exists():
        try:
            shutil.copy2(seed, target)
        except OSError:
            pass
    return data_dir


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--log", type=Path, help="Power.log file or session-log directory")
    cli.add_argument("--player-id", default="", help="Your local controller/PlayerID, if known")
    cli.add_argument("--demo", action="store_true", help="Show simulated updates without the game")
    cli.add_argument("--refresh-cards", action="store_true", help="Refresh the cached card reference")
    cli.add_argument("--locale", default="enUS", help="Card reference language, e.g. enUS, frFR, deDE")
    cli.add_argument("--history", action="store_true", help="Print local match history as JSON without starting Tk")
    cli.add_argument("--replay", type=Path, help="Parse a recorded Power.log and print stats; no GUI or configuration changes")
    cli.add_argument("--native-feed", action="store_true", help="Run the private JSON feed for the native AppKit overlay")
    cli.add_argument("--state-file", type=Path, help="Native overlay JSON state file (used with --native-feed)")
    args = cli.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    data_dir = application_data_dir()
    if args.history:
        if not (data_dir / "tracker.sqlite3").exists():
            print(json.dumps({"schema": 1, "matches": []}))
            return
        history = HistoryStore(data_dir / "tracker.sqlite3")
        try:
            print(json.dumps(history.export(), indent=2, ensure_ascii=False))
        finally:
            history.close()
        return
    if args.replay:
        parser = BattlegroundsParser(lambda state: None, args.player_id, publish_interval=.2)
        parser.begin_stream(args.replay)
        with args.replay.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                parser.consume(line)
        parser.flush()
        print(json.dumps(parser.state.summary(), indent=2, ensure_ascii=False))
        return
    if args.native_feed:
        from native_feed import run_native_feed
        run_native_feed(args, data_dir)
        return
    try:
        import tkinter as tk
        if tk.TkVersion < 8.6:
            raise RuntimeError("Tk 8.6+ is required. Use a current Python.org macOS Python with Tk; Apple's Tk 8.5 is obsolete.")
        from overlay import Overlay
    except (ImportError, RuntimeError) as exc:
        cli.exit(1, f"Cannot start overlay: {exc}\n")

    paths = HearthstonePaths.current()
    if not args.demo and args.log is None:
        for notice in ensure_power_logging(paths):
            logging.info(notice)
        if sys.platform == "darwin":
            installation = discover_installation()
            if installation:
                logging.info(ensure_client_logging(installation))
    stopped = threading.Event()
    try:
        initial_cards = CardsDatabase(data_dir, args.locale)
    except ValueError as exc:
        cli.exit(2, str(exc) + "\n")
    try:
        history = HistoryStore(":memory:" if args.demo else data_dir / "tracker.sqlite3")
    except (OSError, sqlite3.Error) as exc:
        logging.warning("Persistent history unavailable (%s); using temporary history", exc)
        history = HistoryStore()
    overlay = Overlay(initial_cards, on_close=stopped.set, history=history,
                      settings_path=None if args.demo else data_dir / "ui_settings.json", demo=args.demo)
    storage_failed = False
    def publish(state):
        nonlocal storage_failed
        try:
            history.record(state)
        except sqlite3.Error as exc:
            if not storage_failed:
                logging.warning("History write failed; live overlay still works: %s", exc)
                storage_failed = True
        overlay.publish(state)
    parser = BattlegroundsParser(publish, "1" if args.demo else args.player_id, publish_interval=.1)
    tailer = None

    def load_cards() -> None:
        cards = CardsDatabase(data_dir, args.locale)
        count = 0
        try:
            count = cards.load()
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            logging.warning("Card cache unreadable: %s", exc)
        if args.demo:
            from demo import TRAINING_CARDS
            cards.add(TRAINING_CARDS)
            overlay.publish_cards(cards, "Training cards + local reference · demo history is temporary")
            return
        if count:
            overlay.publish_cards(cards, f"{count} cards cached locally")
        if not count or args.refresh_cards:
            fresh = CardsDatabase(data_dir, args.locale)
            try:
                count = fresh.refresh()
                overlay.publish_cards(fresh, f"{count} cards cached locally")
            except Exception as exc:
                logging.warning("Card download failed: %s", exc)
                overlay.publish_cards(cards, "Card download failed; using cache" if count else "Card download failed; displaying card IDs")

    threading.Thread(target=load_cards, name="card-reference", daemon=True).start()
    if args.demo:
        from demo import run_demo
        threading.Thread(target=run_demo, args=(parser, stopped), name="demo", daemon=True).start()
    else:
        tailer = PowerLogTailer(args.log or paths.logs_dir, parser.consume,
                               on_status=parser.set_stream_status, on_stream=parser.begin_stream,
                               on_idle=parser.flush)
        tailer.start()
    try:
        overlay.run()
    except KeyboardInterrupt:
        overlay.close()
    finally:
        stopped.set()
        if tailer:
            tailer.stop()
        # Worker threads are daemons, but wait for the demo producer before closing SQLite.
        if args.demo:
            for worker in threading.enumerate():
                if worker.name == "demo":
                    worker.join(timeout=2)
        history.close()


if __name__ == "__main__":
    main()
