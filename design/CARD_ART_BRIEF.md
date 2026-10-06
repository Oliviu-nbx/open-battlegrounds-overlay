# Native card portrait extension

User-approved: oval battlefield portraits; mouse hover opens the full card.
Apply to friendly and last-observed opponent boards. Keep parser/history and
the existing macOS utility shell. This is an Operate-mode local extension.

THESIS: recognize minions visually without sacrificing honest live statistics.
OWN-WORLD: retain native DESIGN.md; actual Blizzard art inhabits oval crops.
STORY: inspect the board, hover a portrait, read the card and logged stats.
FIRST VIEWPORT: the complete friendly board wraps into compact portrait rows;
missing art uses a named fallback with the same footprint.
FORM: a non-modal top-level hover preview, also reachable with Tab/Return;
hover survives movement into the preview and Escape dismisses before app exit.
FINISH: bounded asynchronous fetch, on-disk cache with source provenance, tests,
native screenshot review when permissions permit, no false pixel-perfect claim.

Primary portrait art uses HearthstoneJSON's public `256x` image route; localized
full-card renders use its `render/latest/{locale}/512x` route. If and only if a
full render returns HTTP 404 and cached metadata supplies a normal DBF ID, the
preview may request the BG Card Database public image route
(`https://hsbg.cards/api/v1/cards/{normalDbfID}/image`). Golden cards request
`?golden=true` explicitly; never infer a golden variant from stats or a guessed
card ID. The secondary source is labelled **BG Card Database · English base
render**. If that API reports normal art for a golden request, the preview says
so; an English/normal fallback must not be represented as localized/golden art.

Sources and terms: https://hearthstonejson.com/docs/images.html ;
https://hsbg.cards/api-docs ; https://hsbg.cards/terms . Public artwork is not
MIT-licensed tracker code. Requests remain lazy, bounded and cached below
`data/images/` with adjacent provenance JSON; do not bulk-scrape or mirror card
art. A render may lag a patch or be unavailable; do not infer card variants,
current buffs, damage or live statistics from a static image. No account, journal
or Power.log uploads occur.
