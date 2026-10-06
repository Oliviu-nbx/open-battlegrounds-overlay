# Open Battlegrounds — native macOS tracker

<!-- impeccable:product-schema 1 -->

## Platform

macOS and Windows desktop. The Python/Tk tracker runs on both platforms;
macOS also has an optional native AppKit `NSPanel` host for the always-on-top
game rail. This is not a website, iOS app, or Android app. The Windows overlay
uses normal topmost Tk behavior and works best with Hearthstone in
borderless/windowed mode; exclusive full-screen behavior is not guaranteed.

## Users and purpose

A Hearthstone Battlegrounds player who needs a readable floating tracker,
a narrow game-side overlay, observed board history and honest local statistics
while playing on macOS, with decision support that remains free, local and
explainable rather than account- or subscription-gated.
The user approved applying the separate macOS-inspired design preview to the
actual native application and its normal launcher.

## Constraints

Use standard-library/open-source components and the free HearthstoneJSON cache.
Preserve the existing log parser, history journal, localization and conservative
combat model. No uploads, account APIs, game actions, paid dependencies or
changes to macOS privacy permissions. Demo fixtures must be explicit and use
temporary storage. Native Tk is retained; no claim of native AppKit materials.
The AppKit overlay may use a high native window level and full-screen auxiliary
space behavior to remain visible after the game is focused, but it does not
inspect, resize, capture, automate or click through the Hearthstone window. Its
private file bridge is local-only and has no network listener.

## Brand commitments

Apple/macOS utility: readable installed typography, neutral dark/light layers,
restrained blue interactions, keyboard controls and explicit contrast colors.
Do not redistribute Apple's font or design-kit assets.

## Evidence and truth

Real state comes from readable Power.log events. Cached card metadata is not a
prediction of lobby availability. Old observations may be stale; a readable log
does not prove the game process is currently playing. Missing values and hidden
boards remain unknown. Journal corrections are manual and retain provenance.
When two observed boards are available, board-only combat simulation publishes a
quick result before its refined adaptive result, and remains explicitly hypothetical
and incomplete; missing boards,
invalid stats and missing card metadata block estimates, while unimplemented
observed effects produce a visibly labelled incomplete baseline that lists every
excluded effect. Each published result discloses its adaptive trial
count, 95% sampling interval, observation-age confidence, first-attacker rule,
modelled effects and conditional damage range. Stale-board sensitivity is a
labelled comparison against an observed-board-median minion, never a prediction
of a hidden opponent purchase. Last-observed opponent threats are summaries
rather than predictions of hidden changes. Calibration stores only logged,
unambiguous combat results and never invents an outcome. Recruit
guidance and the Decision lab's Buy/Level/Roll/Hold comparisons are transparent
logged-cost/shop heuristics, never optimal-play claims. Positioning analysis tests
only bounded local board orders and never moves a game minion. Card-reference
filters use only cached metadata and do not assert lobby availability. Post-match
reviews summarize only recorded snapshots; they do not claim
missed-gold decisions, unseen actions or causal explanations. Users can disable
the combat estimate and choose Auto, Recruit, Combat or Minimal rail presets in
Settings. History offers a manual aggregate-only anonymous-summary export, but
the app has no sharing endpoint and never uploads it. See README.md for
capabilities and limits.

## Verification limits

Native widget tests exercise the running Tk window with isolated fixture data.
Screenshot review is currently unavailable because Computer Use permissions
are not granted. The approved browser captures are reference material only,
not evidence that the native implementation was visually reviewed.
