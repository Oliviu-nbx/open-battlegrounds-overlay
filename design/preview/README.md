# Local interactive design preview

Double-click **Start Preview.command** in Finder, or run:

```sh
python3 design/preview/serve.py --open
```

If the default port is busy, add `--port 0`. The server prints the URL, binds only to `127.0.0.1`, and exposes only the three public preview assets. Press Ctrl+C to stop it. There are no pip or npm dependencies and no external fonts, images, or scripts.

You can also open `index.html` directly in a browser. Its HTML, CSS and JavaScript are plain editable source, not a screenshot or a Figma embed.

Try:

- Recruit, combat, waiting, and log-access-error states.
- Opponent selection, including an opponent with no recorded board.
- Expanded / compact overlay, the focused-preview `C` shortcut and window controls.
- Match selection, hero search, date / placement sorting, and synthetic JSON export.
- Five-card reference search and tier filters. The reference is explicitly a subset, not the current full minion pool.
- Dark, light, or system appearance; background opacity; reduced transparency/motion; model opt-in; reset. Preferences use a preview-only browser storage key.

All gameplay and journal values are synthetic. Names and reference base stats were checked against the existing public HearthstoneJSON cache. This prototype does not tail logs, download card data, upload anything, alter game/client settings, or access the real SQLite history. It does not provide actual native always-on-top behavior or macOS materials; those are future implementation work. The Tkinter tracker remains unchanged.

The design follows Apple's [typography](https://developer.apple.com/design/human-interface-guidelines/typography), [materials](https://developer.apple.com/design/human-interface-guidelines/materials), and [accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility) guidance: system typography, clear hierarchy, readable content surfaces, explicit observation age, keyboard-operable controls and reduced-motion behavior. Browser system-font selection does not bundle or redistribute SF Pro.

Source inherits the project's MIT license. Hearthstone card names and data remain the property of their respective owners. This is an independent design proposal, not an official Blizzard or Apple product.

## Verification

Run the isolated server checks with Python's standard library:

```sh
python3 -m unittest discover -s design/preview -p 'test_preview.py' -v
```

Optional logic checks use Node.js (no packages required):

```sh
node --test design/preview/test_app.cjs
```

The UI was exercised in the local browser for navigation, all four phase states,
unknown/stale opponents, compact mode, keyboard controls, filtering, provenance,
appearance, opacity, reduced motion/transparency, persistence and reset.
Desktop, narrow and in-app-width screenshots are retained in `.impeccable/review/`.
Export payload logic is tested separately; the in-app browser did not expose a
download-completion event, so an actual saved download was not verified there.
