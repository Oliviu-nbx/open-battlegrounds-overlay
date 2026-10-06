# Open Battlegrounds Overlay

Free, local-first macOS and Windows overlay for Hearthstone Battlegrounds.

Open Battlegrounds Overlay reads local `Power.log` files to present observed board, resource, opponent, and match-history information. It is an independent open-source companion project: it is **not affiliated with, approved by, or endorsed by Blizzard, Hearthstone, HSReplay, or HearthSim**.

## Privacy and boundaries

- Reads local `Power.log` files. It does **not** inject into, automate, click, inspect, or modify the Hearthstone process.
- Requires no account and does not upload game logs, match data, account names, or game state.
- Card metadata and artwork can be requested from public sources on demand when they are not already cached locally. This is not a claim of zero network access.
- Free and open source under the [MIT License](LICENSE).
- Public-project scope is macOS and Windows desktop only—not iOS, Android, or a web app.

## Combat estimates

Combat odds are **hypothetical board-only estimates** shown only after both combat boards are revealed in the local log. They are not predictions of hidden information or a complete current-patch combat engine.

The simulator does not implement every card mechanic. When an observed board contains unsupported mechanics, the app labels the result an **Incomplete baseline** and lists excluded effects; it must not be interpreted as exact odds. Missing or invalid board information blocks a percentage rather than inventing one.

## Install and run

### macOS

Download the DMG from [Releases](../../releases), drag **Open Battlegrounds Overlay** to Applications, then open it. The current macOS build is unsigned and not notarized, so macOS may require Control-click → **Open** on another Mac.

The native AppKit host is always-on-top and supports compatible full-screen spaces. It reads only local Power.log data. Source builds require macOS Command Line Tools:

```bash
zsh native_macos/create_dmg.sh
```

### Windows

Download and extract the Windows ZIP from [Releases](../../releases), then run `OpenBattlegroundsOverlay.exe` from the extracted folder. Windows uses a topmost Tk portable overlay and works best with Hearthstone in borderless/windowed mode. Do not expect reliable overlay behavior in exclusive full-screen mode.

To build it on Windows with Python 3.11+ and Tk:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build_windows.ps1
```

### Run from source

Use Python with Tk 8.6 or newer. Pillow is optional; without it, the app retains text and metadata fallbacks for card images.

```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

On first run, the app can create the documented platform-specific Power logging configuration only when it is absent. Existing configuration is not overwritten. Mutable local data—including metadata cache, local history, and settings—stays outside the repository's tracked source files.

## Features

- Local Power.log tailing with no game-client automation or process inspection.
- Observed board, gold, tavern tier, shop costs, next-opponent summaries, and local match history.
- Conservative board-only combat simulation with coverage disclosure and stale-observation warnings.
- A native AppKit always-on-top host on macOS and a portable topmost Tk overlay on Windows.
- Cached, on-demand card metadata and art with offline/name fallbacks.

## Test

```bash
python3 -m unittest discover -s tests -v
```

For a synthetic local demo that does not access game logs or persistent history:

```bash
python3 main.py --demo
```

## Local data and third-party material

The app's local journal stores card IDs, stats, and a hashed match identity—not account names. It never uploads Power.log, journal, account-name, or game-state data. Public card metadata and artwork may be fetched lazily from [HearthstoneJSON](https://hearthstonejson.com/) and, where documented by the app, the [BG Card Database](https://hsbg.cards/). Blizzard artwork, Hearthstone names, and card data are not relicensed under MIT.

## Project layout

- `main.py` — application entry point and local-log orchestration
- `parser.py`, `config.py`, `cards_db.py` — Power.log parsing, configuration, and metadata
- `combat.py` — conservative simulation and coverage reporting
- `overlay.py`, `ui.py`, `native_macos/` — desktop overlay hosts
- `windows/` — Windows portable build scripts and notes
- `tests/` — automated tests

## License

Source code is licensed under the [MIT License](LICENSE). See [SECURITY.md](SECURITY.md) for responsible vulnerability reporting.
