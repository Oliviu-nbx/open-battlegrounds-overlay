# Open Battlegrounds Overlay v0.1.0

Initial public release of Open Battlegrounds Overlay, a free, local-first macOS and Windows desktop companion overlay for Hearthstone Battlegrounds.

## What it does

- Reads local `Power.log` files; it does not inject into, automate, click, inspect, or modify the Hearthstone process.
- Requires no account and does not upload game logs, match data, account names, or game state.
- Provides local board, opponent, resource, history, and card-reference views.
- Includes a native AppKit always-on-top host on macOS and a topmost Tk portable overlay on Windows.

## Platform notes

- macOS supports compatible full-screen spaces through its AppKit host.
- Windows works best with Hearthstone in borderless/windowed mode. Reliable overlay behavior is not promised for exclusive full-screen mode.
- This release supports macOS and Windows desktop only; it is not an iOS, Android, or web app.

## Combat estimates

Combat odds are hypothetical board-only estimates after both combat boards are revealed. The current simulator does not implement every card mechanic. Unsupported mechanics are labelled **Incomplete baseline**, not exact odds.

## Privacy, attribution, and license

Card metadata or artwork may be requested from public sources on demand if absent locally; this project does not claim zero network access. It is independent and is not affiliated with, approved by, or endorsed by Blizzard, Hearthstone, HSReplay, or HearthSim.

Open Battlegrounds Overlay is free and open source under the MIT License.
