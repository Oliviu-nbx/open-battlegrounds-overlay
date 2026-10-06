# Open Battlegrounds — design preview

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users and purpose

Confirmed in the user's brief: a macOS Hearthstone Battlegrounds player who needs a readable floating tracker and honest, local statistics. This browser artifact previews the proposed macOS interface; it is not the running Tkinter tracker.

## Constraints

The user approved a local interactive preview after Figma's free MCP limit prevented screen composition. Preserve the existing tracker, its log reader, configuration, and private history. Use sample gameplay data, no paid tools, no external dependencies, and no game-client interactions. The underlying tracker uses Python's standard library.

## Brand commitments

Apple-inspired macOS utility, based on the user's Human Interface Guidelines reference and the previously selected dark semantic palette. Interface typography uses the installed system font, not redistributed Apple font files.

## Evidence and truth

Existing product functionality is documented in ../../README.md. Public card names, base stats, and tiers in the preview were checked against the existing HearthstoneJSON cache. Gameplay stats and match records are explicitly synthetic. Missing information remains unknown; partial combat coverage must not turn into live win probabilities.

## Open decisions

This preview does not decide a future production UI framework or implement a native AppKit window, full combat engine, new log permissions, or live web streaming.
