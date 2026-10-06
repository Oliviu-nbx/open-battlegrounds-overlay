---
name: Open Battlegrounds — design preview
description: An Apple/macOS utility look for a synthetic local browser prototype.
colors:
  desktop: "#15171b"
  window: "#202124"
  sidebar: "#26272b"
  raised: "#2c2e33"
  panel: "#242529"
  text: "#f2f3f5"
  secondary: "#b4b6bd"
  line: "#41444b"
  accent: "#80bcff"
  selected: "#344a65"
  success: "#82dfa2"
  warning: "#ffd17c"
  danger: "#ffa4aa"
  info: "#28313e"
  button: "#3b3e45"
  on-primary: "#14263b"
  light-desktop: "#e3e7eb"
  light-window: "#fafafa"
  light-sidebar: "#eff0f2"
  light-raised: "#eceef1"
  light-panel: "#f4f5f7"
  light-text: "#202329"
  light-secondary: "#59616d"
  light-line: "#c5c9cf"
  light-accent: "#145ca5"
  light-selected: "#dbe9fa"
  light-success: "#21683e"
  light-warning: "#835106"
  light-danger: "#a12836"
  light-info: "#e8eef6"
  light-button: "#e4e7ec"
  light-on-primary: "#fff"
typography:
  headline: {fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: "25px", fontWeight: 650, lineHeight: 1.25, letterSpacing: "-.025em"}
  title: {fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: "15px", fontWeight: 650, lineHeight: 1.3}
  body: {fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: "13px", lineHeight: 1.5}
  label: {fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: "12px", lineHeight: 1.5}
  metric: {fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', fontSize: "24px", fontWeight: 550, lineHeight: 1.2, letterSpacing: "-.02em"}
rounded:
  button: "6px"
  control: "7px"
  notice: "8px"
  settings: "10px"
  window: "12px"
  overlay: "14px"
  badge: "5px"
spacing:
  tight: "8px"
  compact: "12px"
  regular: "16px"
  section: "24px"
  roomy: "32px"
components:
  button-primary: {backgroundColor: "{colors.accent}", textColor: "{colors.on-primary}", rounded: "{rounded.button}", padding: "5px 12px"}
  button-secondary: {backgroundColor: "{colors.button}", textColor: "{colors.text}", rounded: "{rounded.button}", padding: "5px 12px"}
  search: {backgroundColor: "{colors.raised}", textColor: "{colors.text}", rounded: "{rounded.control}", padding: "7px 10px"}
  navigation-active: {backgroundColor: "{colors.selected}", textColor: "{colors.text}", rounded: "{rounded.control}", padding: "8px 10px"}
  badge: {backgroundColor: "{colors.raised}", textColor: "{colors.secondary}", rounded: "{rounded.badge}", padding: "3px 7px"}
  overlay: {textColor: "{colors.text}", rounded: "{rounded.overlay}"}
---

# Design System: Open Battlegrounds — design preview

## Overview

**Creative North Star: "Apple/macOS utility"**

System typography, restrained neutral light/dark surfaces and dense clear controls define this local HTML prototype. AppKit-inspired chrome provides familiar visual orientation. This is a browser design preview; its materials do not imply native blur, topmost behavior or a live game connection.

**Key Characteristics:**

- System typography and compact functional hierarchy.
- Neutral layers with restrained blue interactive emphasis.
- Semantic state colors, readable numbers and explicit provenance.

## Colors

Frontmatter captures the exact CSS semantic palette. Unprefixed colors map to dark `:root` custom properties; `light-` counterparts map to the same properties under `[data-theme="light"]`. Components resolve those properties so both themes use the same assignments.

### Primary

Blue accent marks actions, active navigation icons, links, caret and focus. Selected blue-gray surfaces identify the current item without filling every control with accent.

### Neutral

Desktop, window, sidebar, panel and raised surfaces establish the hierarchy. Text and secondary text separate content from supporting context; line supplies boundaries; button and on-primary keep actions legible. Info is the tinted notice surface. Success, warning and danger are semantic state colors, not ornamental accents.

**The Semantic Continuity Rule.** Change theme values while preserving each role and component assignment.

## Typography

The installed system stack is explicitly pinned by the chosen macOS utility direction. No font asset or display face is shipped. Headline, title, body, label and metric tokens describe observed roles; supporting annotations also use a smaller step (11px). Mobile headings reduce to (23px). Metrics and tabular data use tabular numerals.

**The Data Hierarchy Rule.** Reserve enlarged numbers for metrics; use compact sentence-case labels and supporting text elsewhere.

## Layout

The window centers within a maximum width (1320px). Desktop layout combines a sidebar (176px), notebook and overlay column (380px), with generous outer spacing and compact internal rows. At (1150px) margins, sidebar and overlay narrow; at (980px) navigation becomes horizontal. At (720px) the overlay precedes the notebook, with a maximum width (420px), and detail/reference columns stack.

The overlay caps height at (660px); its body scrolls while header and footer stay available. The default recruit state fits all five board rows and a visible Shop comparison disclosure. Keep dense row typography and aligned numeric columns; the default reviewed height was approximately (585px).

## Elevation & Depth

Neutral tonal layers and thin borders carry most structure. Ambient window and overlay shadows separate their shells from the surrounding desktop. Exact shadows live in the sidecar. Overlay transparency applies to its isolated background pseudo-element: opacity defaults to (96%) and settings can make it opaque; text stays fully opaque.

## Shapes

Use modest control corners, slightly broader container corners, one-pixel borders and compact inset spacing from the frontmatter. The window and overlay clip their interiors. Authored stroke SVGs use rounded caps and joins; disclosure chevrons rotate when open.

## Components

Buttons use compact padding, medium weight and brightness on hover. Primary actions pair accent with on-primary; secondary actions use the neutral button surface. Fields use raised surfaces and visible borders. Active navigation uses selected fill; inactive items gain raised fill on hover. Badges communicate provenance or state with restrained fills and semantic text.

The overlay is the signature container: header, metrics, aligned minion rows, native HTML disclosures and fixed footer. Expandable reasoning preserves source uncertainty. Settings group rows in bordered panel containers; switch, select and range controls stay compact and keyboard accessible.

**The Visible Focus Rule.** Interactive controls use the accent outline (3px) with offset (3px). State changes use the source duration (160ms) and easing; view changes use (180ms). Honor both system and preview reduced-motion preferences.

## Do's and Don'ts

### Do:

- Do preserve semantic color assignments in both appearances.
- Do use installed system typography and tabular numerals for data.
- Do keep dense clear controls, visible focus and authored SVG icons.
- Do apply transparency to panel backgrounds while keeping text opaque.

### Don't:

- Don't imply native blur, topmost behavior or a live game connection.
- Don't turn observations or incomplete models into confident predictions.
- Don't introduce marketing typography or ornamental color into this utility.

Source evidence: `styles.css`, `index.html`, `app.js`, `BRIEF.md`, `PRODUCT.md`; reviewed captures in `.impeccable/review/`. Synthesized sidecar tonal ramps are palette previews, not implemented CSS tokens.
