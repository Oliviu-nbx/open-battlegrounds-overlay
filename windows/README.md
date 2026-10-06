# Open Battlegrounds Overlay — Windows

The Windows edition uses the same local parser, combat model, card reference and Tk overlay as the cross-platform tracker. It is a **portable app folder** packaged with PyInstaller, rather than the macOS AppKit host.

## What it does

- Reads local Hearthstone `Power.log`; it does not inject into, automate, or click Hearthstone.
- Uses a topmost Tk window. It works best with Hearthstone in windowed or borderless-windowed mode. Exclusive full-screen behavior is Windows/graphics-driver dependent.
- Stores mutable card cache, history and settings in `%LOCALAPPDATA%\OpenBattlegroundsOverlay` when packaged.
- Creates `%LOCALAPPDATA%\Blizzard\Hearthstone\log.config` only if it is missing, enabling Power logging without overwriting an existing configuration.
- Looks for game logs in `%LOCALAPPDATA%\Blizzard\Hearthstone\Logs` and common `Hearthstone\Logs` installation folders.

## Build the portable release on Windows

Prerequisites: Windows 10/11, Python 3.11+ with Tk, and PowerShell.

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\build_windows.ps1
```

The script installs the Python packaging dependencies, writes the app to `dist\windows\OpenBattlegroundsOverlay\`, and creates `dist\windows\OpenBattlegroundsOverlay-Windows.zip` for distribution.

Run `OpenBattlegroundsOverlay.exe` from the extracted folder. Do not move only the `.exe`; the folder contains its runtime files.

## First run

1. Start Hearthstone, then start the overlay.
2. If no `Power.log` exists, restart Hearthstone after the app reports that it created `log.config`.
3. Keep Hearthstone in borderless/windowed mode for the most reliable always-on-top behavior.
4. Use **Ctrl+Q** to close the focused overlay. **Ctrl+Shift+H** works as a focused-window compact toggle; Windows global hotkeys are deliberately not registered.

## Scope and current limits

This package is built on Windows or Windows CI; a macOS machine cannot reliably produce a Windows `.exe`. The public release should clearly identify it as a Windows portable build until it has been tested on real Windows hardware and signed/notarized for its distribution channel.
