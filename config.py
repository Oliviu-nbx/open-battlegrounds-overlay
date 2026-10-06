"""Platform-aware Hearthstone Power-log paths and safe logging setup."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys


POWER_LOG_CONFIG = """[Power]\nLogLevel=1\nFilePrinting=True\nConsolePrinting=True\nScreenPrinting=False\nVerbose=True\n"""


def discover_installation() -> Path | None:
    """Find custom Battle.net installations through macOS Spotlight."""
    candidates = []
    try:
        result = subprocess.run(
            ["mdfind", 'kMDItemCFBundleIdentifier == "unity.Blizzard Entertainment.Hearthstone"'],
            capture_output=True, text=True, timeout=5, check=False,
        )
        candidates.extend(Path(line).parent for line in result.stdout.splitlines() if line.endswith("Hearthstone.app"))
    except (OSError, subprocess.TimeoutExpired):
        pass
    candidates.extend([Path("/Applications/Hearthstone"), Path.home() / "Applications/Hearthstone",
                       Path.home() / "Documents/Hearthstone"])
    return next((path for path in candidates if (path / "Hearthstone.app").is_dir()), None)


def discover_windows_installation(roots: list[Path] | None = None) -> Path | None:
    """Find common Windows Hearthstone installs without scanning a whole drive."""
    if roots is None:
        roots = [Path(value) for value in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")) if value]
        roots.extend([Path.home() / "Games", Path.home() / "Documents"])
    candidates = [root / "Hearthstone" for root in roots]
    return next((path for path in candidates if (path / "Hearthstone.exe").is_file()), None)


def ensure_client_logging(installation: Path) -> str:
    """Remove the game's 10 MB cap; preserve unrelated client settings.

    HSTracker uses [Log] FileSizeLimit.Int=-1. Hearthstone reads this at launch.
    Existing files are backed up before changing just this one setting.
    """
    target = installation / "client.config"
    try:
        original = target.read_text(encoding="utf-8") if target.exists() else ""
        section = re.search(r"(?im)^\[Log\][^\n]*\n", original)
        if section:
            end = re.search(r"(?m)^\[", original[section.end():])
            stop = section.end() + end.start() if end else len(original)
            body = original[section.end():stop]
            setting = re.compile(r"(?im)^\s*FileSizeLimit\.Int\s*=.*$")
            if setting.search(body):
                body = setting.sub("FileSizeLimit.Int=-1", body)
            else:
                body = body.rstrip("\n") + "\nFileSizeLimit.Int=-1\n"
            updated = original[:section.end()] + body + original[stop:]
        else:
            updated = original.rstrip("\n") + ("\n\n" if original else "") + "[Log]\nFileSizeLimit.Int=-1\n"
        if updated != original:
            if original:
                backup = target.with_name("client.config.tracker-backup")
                if not backup.exists():
                    backup.write_text(original, encoding="utf-8")
            target.write_text(updated, encoding="utf-8")
            return f"Updated {target}. Restart Hearthstone to enable continuous logging."
        return "Continuous logging configuration is already enabled."
    except OSError as exc:
        return f"Cannot update {target}: {exc}"


@dataclass(frozen=True)
class HearthstonePaths:
    preferences_dir: Path
    log_config: Path
    logs_dir: Path
    power_log: Path

    @classmethod
    def macos(cls) -> "HearthstonePaths":
        home = Path.home()
        preferences = home / "Library/Preferences/Blizzard/Hearthstone"
        logs = home / "Library/Application Support/Blizzard/Hearthstone/Logs"
        installation = discover_installation()
        if installation:
            logs = installation / "Logs"
        return cls(preferences, preferences / "log.config", logs, logs / "Power.log")

    @classmethod
    def windows(cls, local_app_data: Path | None = None, installation: Path | None = None) -> "HearthstonePaths":
        """Resolve the documented LocalAppData config plus common game log roots.

        Hearthstone's Windows `log.config` belongs in LocalAppData. Depending on
        installation and Battle.net version, Power.log can be in that profile
        folder or beside the installed game, so use the most recently observed
        log root and keep the profile folder as the safe initial fallback.
        """
        profile = local_app_data or Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        preferences = profile / "Blizzard" / "Hearthstone"
        installation = installation if installation is not None else discover_windows_installation()
        candidates = [preferences / "Logs"]
        if installation:
            candidates.append(installation / "Logs")
        existing = [path for path in candidates if path.is_dir()]
        def newest(path: Path) -> int:
            logs = [entry for entry in [path / "Power.log", *path.glob("*/Power.log")] if entry.is_file()]
            return max((entry.stat().st_mtime_ns for entry in logs), default=-1)
        logs = max(existing, key=newest) if existing else candidates[0]
        return cls(preferences, preferences / "log.config", logs, logs / "Power.log")

    @classmethod
    def current(cls) -> "HearthstonePaths":
        return cls.windows() if sys.platform == "win32" else cls.macos()


def ensure_power_logging(paths: HearthstonePaths | None = None) -> list[str]:
    """Create the opt-in Power logger config if absent. Returns user-facing notices.

    Existing user configuration is deliberately never overwritten.
    """
    paths = paths or HearthstonePaths.current()
    notices: list[str] = []
    try:
        paths.preferences_dir.mkdir(parents=True, exist_ok=True)
        if not paths.log_config.exists():
            paths.log_config.write_text(POWER_LOG_CONFIG, encoding="utf-8")
            notices.append(f"Created {paths.log_config}. Restart Hearthstone to apply it.")
        else:
            notices.append(f"Using existing logging configuration: {paths.log_config}")
    except PermissionError:
        notices.append("Cannot create log.config. Grant Full Disk Access to this app/Terminal, then retry.")

    try:
        candidates = [paths.power_log]
        if paths.logs_dir.is_dir():
            candidates.extend(entry / "Power.log" for entry in paths.logs_dir.iterdir() if entry.is_dir())
        existing = [(path.stat().st_mtime_ns, path) for path in candidates if path.exists()]
        if existing:
            power_log = max(existing, key=lambda item: item[0])[1]
            with power_log.open("rb"):
                pass
            notices.append(f"Power.log is accessible: {power_log}")
        else:
            notices.append("Power.log is not present yet. Start a Hearthstone match; the overlay will wait for it.")
    except PermissionError:
        notices.append("Power.log is blocked by macOS privacy controls. Grant Full Disk Access, then restart.")
    except OSError as exc:
        notices.append(f"Cannot inspect Hearthstone logs: {exc}")
    return notices
