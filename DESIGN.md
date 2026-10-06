---
name: Open Battlegrounds — native macOS tracker
description: A readable floating Apple/macOS utility for local Battlegrounds observations.
colors:
  window: "#202124"
  sidebar: "#26272b"
  raised: "#2c2e33"
  panel: "#242529"
  text: "#f2f3f5"
  secondary: "#b4b6bd"
  line: "#41444b"
  accent: "#80bcff"
  selected: "#344a65"
  warning: "#ffd17c"
  button: "#3b3e45"
  light-window: "#fafafa"
  light-sidebar: "#eff0f2"
  light-raised: "#eceef1"
  light-panel: "#f4f5f7"
  light-text: "#202329"
  light-secondary: "#59616d"
  light-line: "#c5c9cf"
  light-accent: "#145ca5"
  light-selected: "#dbe9fa"
  light-warning: "#835106"
  light-button: "#e4e7ec"
  chrome-close: "#ff6058"
  chrome-minimize: "#ffbd2e"
  chrome-expand: "#28c840"
typography:
  headline: {fontFamily: "Helvetica Neue", fontSize: "23pt", fontWeight: 700}
  title: {fontFamily: "Helvetica Neue", fontSize: "13pt", fontWeight: 700}
  body: {fontFamily: "Helvetica Neue", fontSize: "12pt", fontWeight: 400}
  body-strong: {fontFamily: "Helvetica Neue", fontSize: "12pt", fontWeight: 700}
  label: {fontFamily: "Helvetica Neue", fontSize: "11pt", fontWeight: 400}
  metric: {fontFamily: "Helvetica Neue", fontSize: "23pt", fontWeight: 700}
  history-metric: {fontFamily: "Helvetica Neue", fontSize: "22pt", fontWeight: 700}
rounded:
  square: "0px"
spacing:
  compact: "6px"
  inset: "8px"
  control: "10px"
  text: "12px"
  panel: "14px"
  separator: "16px"
  section-inset: "18px"
  main-inset: "22px"
  section-gap: "24px"
components:
  button-secondary: {backgroundColor: "{colors.button}", textColor: "{colors.text}", typography: "{typography.body}", rounded: "{rounded.square}", padding: "6px 10px"}
  button-secondary-hover: {backgroundColor: "{colors.raised}", textColor: "{colors.text}"}
  navigation: {backgroundColor: "{colors.sidebar}", textColor: "{colors.secondary}", typography: "{typography.body}", rounded: "{rounded.square}", padding: "6px 10px"}
  navigation-active: {backgroundColor: "{colors.selected}", textColor: "{colors.text}"}
  search: {backgroundColor: "{colors.raised}", textColor: "{colors.text}", typography: "{typography.body}", rounded: "{rounded.square}"}
  board-panel: {backgroundColor: "{colors.panel}", textColor: "{colors.text}", rounded: "{rounded.square}", padding: "10px 14px"}
  board-portrait: {backgroundColor: "{colors.raised}", textColor: "{colors.text}", ovalArt: "58px × 77px within a 76px × 100px focusable Canvas", badge: "logged ATK / HP"}
  history-row: {backgroundColor: "{colors.panel}", textColor: "{colors.text}", typography: "{typography.body}", height: "32px"}
  history-row-selected: {backgroundColor: "{colors.selected}", textColor: "{colors.text}"}
---

# Design System: Open Battlegrounds — native macOS tracker

## Overview

**Creative North Star: "Apple/macOS utility"**

Installed typography, neutral dark/light layers and restrained blue interactions define this floating Python/Tk desktop utility. Information is compact and readable: hierarchy comes from type, alignment and surface tone. The approved browser preview supplies the direction; the actual native source supplies the implementation rules.

Tk frames and widgets adapt that direction with square surfaces and explicit colors. This is not AppKit glass: no blur, bundled font assets or decorative animation is implemented. Source and widget tests establish behavior, but native screenshot review remains unavailable because Computer Use permissions are not granted. The fresh review verdict is recapture; browser reference captures and HTML examples do not establish native visual approval.

**Key Characteristics:**

- Installed Helvetica Neue with compact functional hierarchy.
- Neutral dark/light layers and restrained blue interactive emphasis.
- Square Tk surfaces, explicit focus and aligned numeric columns.
- Immediate updates with visible uncertainty and provenance.

## Colors

The frontmatter records colors actually assigned to native widgets. Unprefixed roles are the dark appearance; light-prefixed roles are their light counterparts. Appearance is chosen explicitly, rather than following the operating system automatically.

### Primary

Accent is the cool blue used by focus highlights, insertion carets and the active opacity control. Selected is the subdued blue surface identifying chosen navigation, opponents, tiers and table rows. The native implementation uses neutral action buttons; it does not implement the preview's filled primary button.

### Secondary

Warning is amber text for stale observations, model limitations, demo identification and the gold metric. Its light counterpart is a darker brown for readable emphasis on light surfaces.

### Neutral

Window is the main canvas. Sidebar contains navigation and the title/footer strips. Panel groups boards, settings and text details; raised is the field surface and hover fill. Text carries primary information, secondary carries supporting context, line defines thin boundaries, and button supplies neutral action fill.

The fixed chrome-close, chrome-minimize and chrome-expand colors draw the three titlebar circles in both themes. These circles are decorative drag affordances, not three working window controls; Close and Compact are separate labeled controls.

**The Semantic Continuity Rule.** Change theme values while preserving each role and component assignment.

## Typography

The installed family is Helvetica Neue; no font file is shipped. Tk positive font sizes are points, so these are not browser pixel sizes. Tk controls font metrics and line height; no custom tracking, web font stack or tabular numeral feature is configured.

Headline and live metric share the large bold step. Title covers the window title and waiting-state heading. Body is the regular label, button, field, detail and table face; body-strong identifies sections and board names. Label is supporting context, table headings and settings scale text. History metrics use their observed smaller bold step.

**The Data Hierarchy Rule.** Reserve enlarged numbers for metrics; use compact sentence-case labels and supporting text elsewhere.

Numeric board cells are right-aligned with a four-character field width. Text wraps within the observed widget widths; do not substitute an invented CSS line-height or tracking rule for Tk metrics.

## Layout

The frameless normal window has a minimum size of (800 × 580), with migrated/default redesigned geometry of (1040 × 760), constrained against the screen at startup. The sidebar is fixed at (154px). Main content uses horizontal inset (22px) and vertical inset (18px); the compact panel uses the frontmatter's board-panel padding.

At window widths of (940px) and above, the opponent notebook and board panel sit side by side with a gap (24px); the panel column has minimum width (370px). Below that threshold, the board panel comes first and the notebook follows beneath it with the same gap. The sidebar remains vertical. A Canvas scroll area makes overflow reachable and hides its scrollbar only when the content fits.

The header and footer sit outside the scrolling content. The complete observed friendly board precedes optional economy, shop, combat, decision-explanation and hand disclosures. Their detail content starts collapsed in the redesigned defaults. A separate Decision lab presents turn-plan assumptions, observed combat factors, coverage groups, opponent timeline and a local positioning sandbox without crowding the live board. Compact mode hides body and footer, retaining the draggable titlebar and two-line observed summary at (480 × 96); expanding restores the saved normal geometry.

History uses stretchable columns and rows of (32px). Settings use vertically grouped panels; the opacity scale has source length (280px). Native pack/grid values are Tk coordinate units, not a browser layout guarantee.

### Game-side overlay

The game-side overlay is a separate `(330 × 700)` mode, entered from the full tracker or Settings. On a new display it anchors `(20px)` from the right edge and near the top (`90px` when the display permits), then retains its dragged position. It intentionally uses a screen edge rather than attempting to inspect, resize, attach to, or automate the Hearthstone window. **Full** restores the detailed tracker and its saved normal geometry.

The rail stores one of four selectable presets: **Auto**, **Recruit**, **Combat** or **Minimal**. Auto becomes Recruit while the local log is in Recruit and Combat while it is in Combat. Recruit orders the logged resource metrics, a concise affordability/shop heuristic, the friendly board and next-opponent threat summary. Combat orders the resource metrics, last-observed opponent/staleness/threat signals, hypothetical win chance and coverage copy, then both portrait boards. Minimal retains metrics, chance and opponent identity. Its oval board tiles use `(46 × 66)` canvases so seven minions wrap in the narrow width while retaining focus, hover/full-card preview and logged ATK/HP badges. The rail is topmost when the floating preference is on, but Tk does not implement background-only translucency, native blur, game-window detection or pointer click-through.

### Native AppKit host

`Start Native Overlay.command` builds a local normal AppKit application when a game-side rail must remain above the focused game. It appears in the Dock and exposes a persistent **BG** menu-bar item, so background game focus never removes the user’s route to Show/Hide, Keep Above Games, Settings, reset-position or Quit. The Settings window mirrors the on-top, hide, position and quit controls. Its borderless `NSPanel` uses the screen-saver window level and the `canJoinAllSpaces`, `fullScreenAuxiliary`, `stationary` and non-deactivation collection/window behaviors when Keep Above Games is enabled. The high level is strictly for the user's read-only local panel; it is not click-through, does not capture screen pixels, attach to the game process or automate input. The panel reads an atomically replaced local JSON feed from the existing Python parser/model process and closes that child process when the panel exits.

The native panel uses an original game-adjacent HUD treatment: a near-black charcoal surface, restrained violet outline, gold resource ribbon, monospaced compact status copy, and a dedicated segmented **Combat Odds** card with green win, lavender tie and red loss values. The design takes visual cues from the supplied Battlegrounds overlay references—compact game-side hierarchy and a prominent odds block—without embedding or reproducing their artwork, card frames, logos or proprietary interface assets. An amber **Baseline** tag continues to disclose reduced model fidelity rather than presenting partial simulation as full-rules odds.

## Elevation & Depth

Depth comes from neutral tonal layers and thin boundaries. The app defines no widget shadows or blur. Border lines are (1px) where present; controls and entry fields use accent focus highlights (2px), while the read-only detail widget uses a focus highlight (1px).

Tk window alpha fades the entire window, including text and controls. The setting ranges from (85–100%) and defaults to (96%); Use opaque window forces (100%). Contrast tests on palette values do not verify composited contrast over every possible desktop background.

**The Whole Window Rule.** Describe transparency as whole-window alpha; use the opaque setting when consistent contrast is needed.

## Shapes

Frames, controls, fields and table rows have square corners. Do not import the browser preview's rounded container tokens. Authored Canvas navigation icons use strokes (1.5px) and rounded caps/joins, within (18 × 18) canvases. Those stroke details do not imply rounded widget surfaces.

## Components

### Buttons

Neutral, labeled and keyboard reachable. Default buttons use the button surface and body text with the frontmatter's padding. Hover replaces the surface with raised; pointer exit restores the base surface. Accent marks the focus highlight. Return and Space invoke the same action as click. No separate pressed fill or animated transition is defined.

### Navigation

Four vertically stacked labeled controls pair visible text with decorative Canvas stroke icons. Selected navigation uses selected fill and primary text; other entries use sidebar fill and secondary text. Hover uses raised fill, and keyboard focus uses the same accent highlight as buttons.

### Inputs / Fields

Search and manual-placement entries use raised fill, primary text, an accent caret and selected text background. Their flat border width is (4px), with focus highlight (2px); width is specified in characters. Disabled entry configuration retains raised fill with secondary text. Fields are actual Tk entries, not HTML inputs.

### Cards / Containers

The board panel uses panel fill, a thin line boundary and compact inset padding. It shows phase, resource metrics, last-observed opponent context, an automatic hypothetical win-chance surface when both boards are covered, the complete observed portrait board, then inline disclosure controls. Missing values render as an em dash rather than guessed numbers.

### Board portraits and full-card preview

Friendly and selected last-observed opponent boards render each minion as a focusable `(76 × 100)` Tk Canvas tile. When public artwork is available, the `(58 × 77)` art crop is oval; the surrounding panel/container remains square under the native design system. A tier badge appears only when cached metadata knows the tier. The attack/health badges always show **logged live values**, with abbreviated large values only on the small tile; they do not use printed card values. When Pillow, artwork or metadata is unavailable, a named text fallback keeps the same tile footprint rather than fabricating art or state.

The portrait grid recalculates from its available width (`1–7` columns at roughly `84px` per column), so normal and narrow layouts preserve every observed minion before optional detail disclosures. Hover delays the non-modal full-card preview by `(250ms)`; a `(160ms)` leave grace permits movement into it. Tab focus plus Return/Space opens it immediately, and Escape dismisses it before tracker exit. The preview repeats exact logged ATK/HP and identifies the card image as printed/base information, which can lag a patch and cannot describe buffs, damage, auras or opponent changes after observation.

Full-card art first uses HearthstoneJSON. An HTTP 404 localized-render fallback may use BG Card Database only when an actual normal DBF ID is cached; the fallback is visibly labelled as an English base render, and an unavailable golden render is visibly labelled as normal artwork. Downloads are lazy, bounded and cached with local provenance. This component specification documents source behavior, not a native screenshot: physical pointer ergonomics, screen-edge placement and macOS rendering remain pending visual recapture.

### Hypothetical win chance

When the local board and the next opponent's last-observed board both have usable card metadata and current logged stats, a worker first publishes a 100-trial **Quick estimate** and then runs the adaptive `(800–6,000)`-trial board-only refinement. A superseded simulation checks for a newer board inside its attack loop, so an earlier complex fight cannot block the current quick result. The surface displays **Hypothetical win chance**, loss and tie percentages above the friendly portrait board. It recalculates when either relevant observation changes, stops early only after the 95% win interval narrows enough, announces calculation while a worker runs, and can be disabled in Settings. Completed coverage shows the interval, observation-age confidence, first-attacker rule, included effects and conditional damage range; unavailable coverage names all known blockers in the full combat disclosure. A stale observation can expose a sensitivity range based on a synthetic observed-board-median minion, which is explicitly a comparison scenario and never a hidden-board assertion. The surface states that it uses the last-observed board; it never represents hidden changes as current data.

If either board is absent, an opponent was not yet observed, current stats are invalid, or card metadata is missing, the surface shows an awaiting or unavailable message instead of an invented percentage. If valid observed boards contain unimplemented effects, the live surface instead shows an **Incomplete baseline win chance** based on logged stats and generic combat mechanics, names the excluded effects, and uses warning styling to state that the result can be biased. The model includes vanilla attack order, Taunt, Divine Shield, Poisonous/Venomous, Windfury/Reborn, Cleave, Mega Windfury, immunity/untargetability and board positions; audited fixed-token deathrattle summon chains and Titus repeats; plus Tarecgosa's logged retained state, Electric Synthesizer, Runic Arcanist, Roaring Recruiter, Mummifier, Hopebringer, Eternal Knight, Humming Bird, Thousandth Paper Drake, Fire-forged Evoker, Amber Guardian and Boom-in-a-Box. Hero powers, trinkets, quests, most spells, random/hand-dependent summon effects, other unknown card effects and unobserved changes remain outside the model. The history view calibrates estimates only against outcomes the Power.log made unambiguous. The percentage is therefore a constrained scenario estimate, not full-game odds or a guarantee.

### Tables / Read-only Details

The history table uses the explicit ttk clam theme, panel rows, raised headers and selected row fill. Header text is secondary; active headers use button fill. Its metrics include private prediction calibration once the Power.log has made combat outcomes unambiguous: sample count, predicted versus actual expected win rate and Brier score. Details add an evidence-only post-match review and board-change timeline before the recorded snapshots: observed round count, highest recorded tier, peak recorded board and per-round stat/card changes. Details use a word-wrapped Tk Text widget, panel fill and compact inset (12px horizontally, 10px vertically). Rendering restores disabled state so details remain read-only; heading, muted and warning tags preserve hierarchy.

**The Evidence Rule.** Keep observations, missing values, stale boards, manual corrections and hypothetical models visibly distinguished.

The sidecar's five self-contained HTML/CSS component examples are documentation approximations of native widgets. They are not native implementations or native screenshots. Browser hover/focus states illustrate corresponding source states; their rendering does not verify Tk geometry or macOS display output.

## Do's and Don'ts

### Do:

- Do preserve semantic color assignments in both explicit appearances.
- Do use installed Helvetica Neue with Tk point sizes and square surfaces.
- Do keep visible keyboard focus, labeled controls and authored stroke icons.
- Do keep the complete observed portrait board before optional details and identify its live badges as logged values.
- Do label automatic board-only percentages as hypothetical and last-observed.
- Do describe transparency as whole-window alpha and offer the opaque setting.
- Do keep unknown values, stale observations and model limitations visible.

### Don't:

- Don't claim AppKit materials, native blur, background-only opacity or decorative animation.
- Don't import preview-only radii, shadows, browser typography or primary-button variants.
- Don't treat printed card-image values as current buffs, damage or opponent state.
- Don't present a blocked, stale or board-only estimate as complete-game odds.
- Don't infer hidden boards, lobby exclusions or model accuracy from visual design.
- Don't treat HTML documentation examples or browser captures as native visual approval.

Source evidence: `ui.py`, `overlay.py`, `combat.py`, `card_images.py`, `settings.py`, `main.py`, `PRODUCT.md`, `design/NATIVE_BRIEF.md`, `design/CARD_ART_BRIEF.md`, `tests/test_native_design.py`, `tests/test_card_images.py` and `tests/test_features.py`. The parent verification pass reports 51 passing tests; behavior verification is separate from the outstanding native screenshot review. Unused palette entries success, info and on_primary are not canonized as implemented component roles. Sidecar tonal ramps are synthesized palette illustrations, not native runtime tokens.
