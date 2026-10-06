"use strict";

// This prototype never opens game logs or the real tracker database.
// Card metadata was checked against the existing public HearthstoneJSON cache;
// entity statistics, opponents, dates and placements are synthetic fixtures.
const STORAGE_KEY = "open-battlegrounds.design-preview.v1";
const DEFAULTS = Object.freeze({theme: "dark", opacity: 96, compact: false, reduceTransparency: false, reduceMotion: false, model: false});
const ownBoard = [
  {name:"Wolf Pup", tribe:"Beast", tier:3, attack:29, health:32},
  {name:"Tasty Lobster", tribe:"Beast", tier:3, attack:2, health:1},
  {name:"Hoarding Hyena", tribe:"Beast", tier:4, attack:4, health:6},
  {name:"Lurking Lionfish", tribe:"Beast", tier:2, attack:22, health:12},
  {name:"Brain Rotter", tribe:"Aberration", tier:2, attack:16, health:11}
];
const referenceCards = [
  {id:"BG36_207", name:"Wolf Pup", tribe:"Beast", tier:3, attack:3, health:6},
  {id:"BG36_202", name:"Tasty Lobster", tribe:"Beast", tier:3, attack:2, health:1},
  {id:"BG36_210", name:"Hoarding Hyena", tribe:"Beast", tier:4, attack:4, health:6},
  {id:"BG36_201", name:"Lurking Lionfish", tribe:"Beast", tier:2, attack:3, health:4},
  {id:"BG36_099", name:"Brain Rotter", tribe:"Aberration", tier:2, attack:3, health:4}
];
const opponents = [
  {id:"ragnaros", name:"Ragnaros the Firelord", tier:4, seen:5, next:true, board:[
    {name:"Wolf Pup",tribe:"Beast",tier:3,attack:14,health:18},
    {name:"Hoarding Hyena",tribe:"Beast",tier:4,attack:6,health:8},
    {name:"Lurking Lionfish",tribe:"Beast",tier:2,attack:8,health:12}
  ]},
  {id:"sylvanas", name:"Sylvanas Windrunner", tier:3, seen:6, board:[
    {name:"Brain Rotter",tribe:"Aberration",tier:2,attack:12,health:16},
    {name:"Lurking Lionfish",tribe:"Beast",tier:2,attack:9,health:10},
    {name:"Tasty Lobster",tribe:"Beast",tier:3,attack:2,health:1}
  ]},
  {id:"millhouse", name:"Millhouse Manastorm", tier:3, seen:3, board:[
    {name:"Wolf Pup",tribe:"Beast",tier:3,attack:6,health:9},
    {name:"Brain Rotter",tribe:"Aberration",tier:2,attack:5,health:6}
  ]},
  {id:"nzoth", name:"N’Zoth", tier:null, seen:null, board:[]}
];
const matches = [
  {id:1, date:"1 Oct · 02:18", hero:"Zephrys, the Great", placement:2, rounds:14, source:"Observed", board:ownBoard},
  {id:2, date:"30 Sep · 23:42", hero:"Ragnaros the Firelord", placement:4, rounds:12, source:"Observed", board:opponents[0].board},
  {id:3, date:"30 Sep · 22:10", hero:"Sylvanas Windrunner", placement:1, rounds:16, source:"Manual", board:opponents[1].board},
  {id:4, date:"30 Sep · 21:06", hero:"Millhouse Manastorm", placement:6, rounds:10, source:"Observed", board:opponents[2].board},
  {id:5, date:"29 Sep · 23:14", hero:"N’Zoth", placement:8, rounds:8, source:"Observed", board:ownBoard.slice(0,2)},
  {id:6, date:"29 Sep · 22:02", hero:"Galakrond", placement:null, rounds:6, source:"Incomplete", board:ownBoard.slice(1,3)}
];
let preferences = readPreferences();
let currentView = "live", phase = "recruit", selectedOpponent = "ragnaros", selectedMatch = 1;
let historyQuery = "", historySort = "date", referenceQuery = "", referenceTier = "all";
const $ = selector => document.querySelector(selector);
const escapeHTML = value => String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#icon-${name}"/></svg>`;
const badge = (text, modifier="") => `<span class="badge ${modifier}">${escapeHTML(text)}</span>`;
const metric = (value, label, modifier="") => `<div class="metric ${modifier}"><span class="value">${escapeHTML(value)}</span><span class="label">${escapeHTML(label)}</span></div>`;
const notice = (title, detail, neutral=false) => `<div class="notice ${neutral?"neutral":""}">${icon(neutral?"info":"alert")}<div><strong>${escapeHTML(title)}</strong><p>${escapeHTML(detail)}</p></div></div>`;
const ordinal = value => value === null ? "Unranked" : `${value}${value===1?"st":value===2?"nd":value===3?"rd":"th"}`;

function readPreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (!saved || typeof saved !== "object") return {...DEFAULTS};
    const result = {...DEFAULTS};
    if (["dark","light","system"].includes(saved.theme)) result.theme = saved.theme;
    if (Number.isFinite(saved.opacity)) result.opacity = Math.max(85,Math.min(100,Math.round(saved.opacity)));
    for (const key of ["compact","reduceTransparency","reduceMotion","model"]) if (typeof saved[key] === "boolean") result[key] = saved[key];
    return result;
  } catch { return {...DEFAULTS}; }
}
function savePreferences() {
  try {localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));}
  catch {announce("Browser storage is unavailable. Preferences will last for this visit only.");}
}
function announce(message) {$("#announcement").textContent = message;}
function applyPreferences() {
  const theme = preferences.theme === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light") : preferences.theme;
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.reduceMotion = String(preferences.reduceMotion);
  const opacity = preferences.reduceTransparency || matchMedia("(prefers-reduced-transparency: reduce)").matches ? 100 : preferences.opacity;
  document.documentElement.style.setProperty("--overlay-opacity", opacity / 100);
  $("#opacity-caption").textContent = `${opacity}%`;
  const button = $("#theme-toggle");
  button.setAttribute("aria-label", `Switch to ${theme==="dark"?"light":"dark"} appearance`);
  button.innerHTML = icon(theme==="dark"?"sun":"moon");
}
function minionRows(board) {
  return `<div class="data-head"><span>Minion · tier</span><span>ATK</span><span>HP</span></div>` + board.map(m => `<div class="minion-row"><div><strong>${escapeHTML(m.name)}</strong><small>${escapeHTML(m.tribe)} · Tier ${m.tier}</small></div><span class="number" aria-label="${m.attack} attack">${m.attack}</span><span class="number" aria-label="${m.health} health">${m.health}</span></div>`).join("");
}
function renderOpponents() {
  $("#opponent-list").innerHTML = opponents.map(o => `<button class="opponent-option ${o.id===selectedOpponent?"selected":""}" data-opponent="${o.id}" aria-pressed="${o.id===selectedOpponent}"><span><strong>${escapeHTML(o.name)}</strong><small>${o.seen===null?"Not observed yet":`Tier ${o.tier} · Seen in round ${o.seen}`}</small></span>${o.next?badge("Next","success"):icon("chevron")}</button>`).join("");
  const o = opponents.find(o => o.id===selectedOpponent);
  $("#opponent-detail").innerHTML = `<section class="opponent-detail"><div class="section-heading"><h3>${escapeHTML(o.name)}</h3>${badge(o.seen===null?"Unknown":`${7-o.seen} round${7-o.seen===1?"":"s"} ago`,"warning")}</div>${o.board.length?minionRows(o.board)+notice("An observation, not their current board",`These ${o.board.length} minions were visible in round ${o.seen}. Later changes and unobserved slots are unknown.`):notice("No board recorded","Meet this opponent in combat before a board can be observed.",true)}</section>`;
}
function renderOverlay() {
  const root = $("#overlay-root");
  const oldFocus = document.activeElement?.closest?.("#overlay-root [data-action]")?.dataset.action;
  const header = `<header class="overlay-header"><span class="overlay-title">Battlegrounds</span><button class="icon-button" data-action="compact" aria-label="${preferences.compact?"Expand":"Compact"} overlay" aria-pressed="${preferences.compact}" title="${preferences.compact?"Expand":"Compact"} overlay">${icon(preferences.compact?"expand":"compact")}</button><button class="icon-button" data-action="settings" aria-label="Open overlay settings" title="Overlay settings">${icon("settings")}</button></header>`;
  let body;
  if (phase === "waiting" || phase === "access") {
    const waiting = phase === "waiting";
    body = `<div class="overlay-body"><div class="phase-line"><strong>Sample connection state</strong>${badge(waiting?"Waiting":"Access error",waiting?"":"warning")}</div><div class="empty-state">${icon(waiting?"live":"alert")}<h2>${waiting?"Waiting for a match":"Can’t read the game log"}</h2><p>${waiting?"The tracker will appear here when a Battlegrounds match produces a readable Power.log.":"The selected log folder is not readable. In the live app, check the folder and its permissions."}</p><button class="button primary" data-action="recruit">Return to sample match</button>${waiting?"":'<button class="button" data-action="settings">View data settings</button>'}</div>${notice("This is a simulated state","The preview does not access your files or request macOS permissions.",true)}</div>`;
  } else if (preferences.compact) {
    body = `<div class="compact-content"><div><strong>Round 7 · Tier 4</strong><small>${phase==="combat"?"Combat":"Recruit"} · Next: Ragnaros · 29 health</small></div><span class="compact-gold">8 gold</span></div>`;
  } else {
    const combat = phase === "combat";
    body = `<div class="overlay-body"><div class="phase-line"><strong>Round 7 <span class="secondary">· ${combat?"Combat":"Recruit"}</span></strong>${badge("Demo connection","success")}</div><div class="metrics">${metric("4","Tavern tier")}${metric("8","Gold","gold")}${metric("29","Health")}${metric("7","Armor")}</div><section class="overlay-section next-section"><div class="next-summary"><strong>${combat?"Facing":"Next"}: Ragnaros the Firelord</strong><small class="secondary">Tier 4</small></div><p class="stale-inline">${icon("alert")}<span><strong>Last seen 2 rounds ago.</strong> Board may have changed.</span></p></section>`;
    // Keep the complete observed friendly board in the default scan; secondary
    // costs and comparison reasoning are progressively disclosed below it.
    body += `<section class="overlay-section"><div class="section-heading"><h2>${combat?"Your board · pre-combat":"Your board"}</h2><span class="secondary">5 of 7 · 2 slots free</span></div>${minionRows(ownBoard)}</section>`;
    if (combat) {
      body += `<section class="overlay-section"><div class="section-heading"><h2>Combat estimate</h2>${badge(preferences.model?"Model blocked":"Off")}</div>${notice("No reliable odds available","This board includes unsupported effects. The board-only model cannot simulate the complete combat.")}<button class="button link" data-action="model" aria-pressed="${preferences.model}">${preferences.model?"Turn off board-only model":"Enable board-only model"}</button><p class="secondary model-caption">Hypothetical model only. Never live combat odds.</p></section>`;
    } else {
      body += `<section class="overlay-section"><details class="utility-disclosure"><summary><strong>Economy</strong><span class="secondary">Upgrade 5 gold · 3 left</span>${icon("chevron")}</summary><div class="disclosed-content"><p class="secondary">Logged costs · sample</p><div class="economy-row"><span>Buy / refresh</span><span>3 / 1 gold</span></div><div class="economy-row"><span>Board space</span><span>2 slots available</span></div></div></details></section>`;
    }
    if (!combat) {
      body += `<section class="overlay-section"><details class="utility-disclosure"><summary><strong>Shop comparison</strong><span class="secondary">2 minions · reasoning</span>${icon("chevron")}</summary><div class="disclosed-content"><details class="shop-option"><summary><span><strong>Hoarding Hyena</strong><small>4 / 6 · Beast · Tier 4</small></span>${badge("Tribe match","success")}${icon("chevron")}</summary><p>Raw stats: 10. Shared Beast tribe with 4 friendly minions: +8. Heuristic score: 18. This is a comparison aid, not an optimal-buy recommendation.</p></details><details class="shop-option"><summary><span><strong>Brain Rotter</strong><small>3 / 4 · Aberration · Tier 2</small></span>${badge("Tribe match")}${icon("chevron")}</summary><p>Raw stats: 7. Shared Aberration tribe with 1 friendly minion: +2. Heuristic score: 9. Scaling and effects are not evaluated.</p></details></div></details></section>`;
    } else {
      body += `<section class="overlay-section"><div class="section-heading"><h2>Opponent snapshot</h2><span class="secondary">3 observed minions</span></div>${minionRows(opponents[0].board)}</section>`;
    }
    body += `</div>`;
  }
  // The bounded content region remains scrollable by keyboard as well as mouse.
  body = body.replace('<div class="overlay-body">', '<div class="overlay-body" tabindex="0" role="region" aria-label="Overlay details">');
  root.innerHTML = `<section class="overlay ${preferences.compact?"compact":""}" aria-label="Floating overlay preview">${header}${body}<footer class="overlay-footer"><span>Synthetic match · Read-only</span><button class="button" data-action="history">History</button></footer></section>`;
  if (oldFocus) root.querySelector(`[data-action="${oldFocus}"]`)?.focus();
}
function viewHeading(title, detail) {return `<div class="view-heading"><div><h1>${title}</h1><p>${detail}</p></div>${badge("Sample data")}</div>`;}
function renderHistory() {
  const ranked = matches.filter(m => m.placement!==null);
  const average = (ranked.reduce((total,m)=>total+m.placement,0)/ranked.length).toLocaleString(undefined,{maximumFractionDigits:1,minimumFractionDigits:1});
  const topFour = Math.round(100*ranked.filter(m=>m.placement<=4).length/ranked.length);
  $("#view-history").innerHTML = viewHeading("Match history","Review your games. Understand where the numbers come from.")+`<div class="stats-strip">${metric(matches.length,"Tracked")}${metric(ranked.length,"Ranked")}${metric(average,"Average placement")}${metric(topFour+"%","Top 4")}</div><div class="history-tools"><label><span class="field-label">Search by hero</span><input type="search" id="history-search" placeholder="Find a match…" value="${escapeHTML(historyQuery)}"></label><button class="button" data-action="export">Export sample JSON</button></div><div class="table-wrap"><table aria-label="Synthetic match history"><thead><tr><th scope="col" id="date-sort" aria-sort="descending"><button class="sort-button" data-sort="date">Date ↓</button></th><th scope="col">Hero</th><th scope="col" id="placement-sort" aria-sort="none"><button class="sort-button" data-sort="placement">Placement</button></th><th scope="col">Rounds</th><th scope="col">Source</th></tr></thead><tbody id="history-rows"></tbody></table></div><p class="settings-note">Ranked aggregates include manual placements and exclude incomplete games. These 6 records are synthetic; your real journal is untouched.</p><section id="match-detail" class="match-detail"></section>`;
  renderHistoryRows(); renderMatchDetail();
}
function renderHistoryRows() {
  const filtered = matches.filter(m=>m.hero.toLowerCase().includes(historyQuery.toLowerCase()));
  if (historySort==="placement") filtered.sort((a,b)=>(a.placement??99)-(b.placement??99));
  $("#history-rows").innerHTML = filtered.map(m=>`<tr class="${m.id===selectedMatch?"selected":""}"><td>${m.date}</td><td><button class="button link" data-match="${m.id}" aria-label="View ${escapeHTML(m.hero)} match, ${escapeHTML(m.date)}">${escapeHTML(m.hero)}</button></td><td>${m.placement===null?badge("Unranked"):ordinal(m.placement)}</td><td>${m.rounds}</td><td><span class="secondary">${m.source}</span></td></tr>`).join("") || '<tr><td colspan="5">No sample matches found. Try another hero name.</td></tr>';
  $("#date-sort").setAttribute("aria-sort",historySort==="date"?"descending":"none");
  $("#placement-sort").setAttribute("aria-sort",historySort==="placement"?"ascending":"none");
  announce(`${filtered.length} sample match${filtered.length===1?"":"es"} found.`);
}
function renderMatchDetail() {
  const m = matches.find(m=>m.id===selectedMatch);
  $("#match-detail").innerHTML = `<div class="detail-header"><div><h2>${escapeHTML(m.hero)}</h2><p>${m.date} · ${ordinal(m.placement)} · ${m.rounds} rounds</p></div>${badge(m.source+" placement")}</div><div class="detail-columns"><div><div class="section-heading"><h3>Last recorded board</h3><span class="secondary">Round ${m.rounds}</span></div>${minionRows(m.board)}</div>${notice(m.placement===null?"Placement unknown":m.source==="Manual"?"Manually recorded placement":"Placement observed in the log",m.placement===null?"The sample log ended before the final rank. This game is not included in ranked aggregates.":m.source==="Manual"?"A manually corrected placement stays labeled so you can distinguish it from a logged result.":"Game-log placement is different from MMR. Rating changes are not inferred from Power.log.",true)}</div>`;
}
function renderReference() {
  $("#view-reference").innerHTML = viewHeading("Card reference","Base card metadata, separate from live minion statistics.")+`<div class="reference-tools"><label><span class="field-label">Search cards</span><input id="reference-search" type="search" placeholder="Name or minion type…" value="${escapeHTML(referenceQuery)}"></label><label><span class="field-label">Tavern tier</span><select id="reference-tier"><option value="all">All preview tiers</option>${[1,2,3,4,5,6].map(t=>`<option value="${t}">Tier ${t}</option>`).join("")}</select></label></div>${notice("A 5-card reference sample","Names, tiers and base stats come from the cached HearthstoneJSON export. This is not the full or live lobby pool.",true)}<div class="card-reference-list" id="reference-list"></div><p id="reference-count" class="settings-note"></p>`;
  $("#reference-tier").value=referenceTier; renderReferenceList();
}
function renderReferenceList() {
  const cards = referenceCards.filter(c=>(referenceTier==="all"||String(c.tier)===referenceTier)&&`${c.name} ${c.tribe}`.toLowerCase().includes(referenceQuery.toLowerCase()));
  $("#reference-list").innerHTML = cards.map(c=>`<div class="reference-entry"><div><strong>${escapeHTML(c.name)}</strong><small>${c.tribe} · Tier ${c.tier} · ${c.id}</small></div><span class="number">${c.attack} ATK / ${c.health} HP</span></div>`).join("") || '<p class="settings-note">No cards match this preview sample. Clear the search or choose another tier.</p>';
  $("#reference-count").textContent = `${cards.length} of ${referenceCards.length} sample cards shown. No lobby tribe availability is inferred.`;
  announce(`${cards.length} sample cards shown.`);
}
function renderSettings() {
  $("#view-settings").innerHTML = viewHeading("Settings","Make the overlay comfortable without making the data disappear.")+`<div class="settings-container"><section class="settings-group"><h2>Appearance</h2><div class="settings-rows"><div class="setting-row"><div><label for="setting-theme">Appearance</label><p>System follows your Mac’s light or dark preference.</p></div><div class="setting-control"><select id="setting-theme"><option value="system">System</option><option value="dark">Dark</option><option value="light">Light</option></select></div></div><div class="setting-row"><div><label for="setting-opacity">Background opacity</label><p>Only the panel background fades. Text stays fully opaque.</p></div><div class="range-label"><input id="setting-opacity" type="range" min="85" max="100" step="1" value="${preferences.opacity}" ${preferences.reduceTransparency?'disabled':''}><output id="opacity-value" for="setting-opacity">${preferences.opacity}%</output></div></div><div class="setting-row"><div><label for="setting-transparency">Reduce transparency</label><p>Use an opaque background for consistent contrast.</p></div><input id="setting-transparency" class="switch" type="checkbox" role="switch" ${preferences.reduceTransparency?'checked':''}></div><div class="setting-row"><div><label for="setting-motion">Reduce motion</label><p>System reduced-motion preferences are always respected.</p></div><input id="setting-motion" class="switch" type="checkbox" role="switch" ${preferences.reduceMotion?'checked':''}></div></div></section><section class="settings-group"><h2>Overlay</h2><div class="settings-rows"><div class="setting-row"><div><label for="setting-compact">Compact mode</label><p>Keep round, tier, next opponent and gold in one small panel.</p></div><input id="setting-compact" class="switch" type="checkbox" role="switch" ${preferences.compact?'checked':''}></div><div class="setting-row"><div><strong>Compact shortcut</strong><p>While this preview is focused. The live tracker’s ⌘⇧H is unchanged.</p></div><kbd class="shortcut">C</kbd></div><div class="setting-row"><div><label for="setting-model">Board-only combat model</label><p>Opt-in, hypothetical simulation. Unsupported boards still block odds.</p></div><input id="setting-model" class="switch" type="checkbox" role="switch" ${preferences.model?'checked':''}></div></div></section><section class="settings-group"><h2>Data & privacy</h2><div class="settings-rows"><div class="setting-row"><div><strong>Preview data</strong><p>Synthetic matches. No log access, real history or network downloads.</p></div>${badge("Local only","success")}</div><div class="setting-row"><div><strong>Log diagnostics</strong><p>Preview the waiting and access-error messages. No permission changes.</p></div><button class="button" data-action="diagnostics">Preview states</button></div></div></section><button class="button" data-action="reset">Reset preview preferences</button><p class="settings-note">These settings affect only this browser prototype and are saved under its own local-storage key. This preview does not change tracker settings, Blizzard files, or macOS permissions.</p></div>`;
  $("#setting-theme").value=preferences.theme;
}
function showView(view, focus=true) {
  if (!["live","history","reference","settings"].includes(view)) return;
  currentView=view;
  if (view==="history") renderHistory();
  if (view==="reference") renderReference();
  if (view==="settings") renderSettings();
  for (const element of document.querySelectorAll(".view")) element.hidden=element.id!==`view-${view}`;
  for (const button of document.querySelectorAll(".nav-item")) {
    const active=button.dataset.view===view; button.classList.toggle("active",active);
    if(active) button.setAttribute("aria-current","page"); else button.removeAttribute("aria-current");
  }
  $("#footer-context").textContent = view==="history"?"6 synthetic matches · 5 ranked":view==="reference"?"HearthstoneJSON · 5-card sample":view==="settings"?"Preview preferences only":"Sample session · Round 7";
  if(focus) $("#content").focus({preventScroll:true});
  announce(`${view==="live"?"Live overlay":view==="history"?"Match history":view==="reference"?"Card reference":"Settings"} view.`);
}
function setPhase(value) {
  if (!["recruit","combat","waiting","access"].includes(value)) return;
  phase=value; $("#phase-select").value=value; $("#mobile-phase-select").value=value;
  renderOverlay(); announce(`Sample state: ${value}. Not connected to Hearthstone.`);
}
function toggleCompact() {
  preferences.compact=!preferences.compact; savePreferences(); renderOverlay();
  announce(`${preferences.compact?"Compact":"Expanded"} overlay.`);
}
function exportSample() {
  const blob = new Blob([JSON.stringify({synthetic:true,source:"Open Battlegrounds design preview",matches},null,2)],{type:"application/json"});
  const url=URL.createObjectURL(blob), link=document.createElement("a");
  link.href=url; link.download="battlegrounds-preview-history.json"; document.body.append(link); link.click(); link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000); announce("Synthetic match history exported. Your actual journal is unchanged.");
}
document.addEventListener("click", event => {
  if (!(event.target instanceof Element)) return;
  const element=event.target.closest("button"); if(!element || element.disabled) return;
  if(element.dataset.view) return showView(element.dataset.view);
  if(element.dataset.opponent) {selectedOpponent=element.dataset.opponent; renderOpponents(); document.querySelector(`[data-opponent="${selectedOpponent}"]`).focus(); return announce(`Showing ${opponents.find(o=>o.id===selectedOpponent).name}’s last observed board.`);}
  if(element.dataset.match) {selectedMatch=Number(element.dataset.match); renderHistoryRows(); renderMatchDetail(); document.querySelector(`[data-match="${selectedMatch}"]`)?.focus(); return;}
  if(element.dataset.sort) {historySort=element.dataset.sort; renderHistoryRows(); return;}
  switch(element.dataset.action) {
    case "compact": return toggleCompact();
    case "settings": return showView("settings");
    case "history": return showView("history");
    case "recruit": return setPhase("recruit");
    case "model": preferences.model=!preferences.model; savePreferences(); renderOverlay(); return announce("Model preference changed. Unsupported board: odds remain unavailable.");
    case "export": return exportSample();
    case "diagnostics": showView("live"); return setPhase("access");
    case "reset": preferences={...DEFAULTS}; savePreferences(); applyPreferences(); renderOverlay(); renderSettings(); $("[data-action='reset']").focus(); return announce("Preview preferences reset. Live tracker unchanged.");
  }
});
document.addEventListener("input", event => {
  if(event.target.id==="history-search") {historyQuery=event.target.value; renderHistoryRows();}
  if(event.target.id==="reference-search") {referenceQuery=event.target.value; renderReferenceList();}
  if(event.target.id==="setting-opacity") {preferences.opacity=Number(event.target.value); $("#opacity-value").value=`${preferences.opacity}%`; applyPreferences(); savePreferences();}
});
document.addEventListener("change", event => {
  const target=event.target;
  if(["phase-select","mobile-phase-select"].includes(target.id)) return setPhase(target.value);
  if(target.id==="reference-tier") {referenceTier=target.value; return renderReferenceList();}
  const map={"setting-theme":"theme","setting-transparency":"reduceTransparency","setting-motion":"reduceMotion","setting-compact":"compact","setting-model":"model"};
  const key=map[target.id]; if(!key) return;
  preferences[key]=key==="theme"?target.value:target.checked;
  applyPreferences(); savePreferences(); renderOverlay();
  if(target.id==="setting-transparency") $("#setting-opacity").disabled=preferences.reduceTransparency;
  announce("Preview preference saved.");
});
$("#theme-toggle").addEventListener("click",()=>{preferences.theme=document.documentElement.dataset.theme==="dark"?"light":"dark";applyPreferences();savePreferences();if(currentView==="settings")$("#setting-theme").value=preferences.theme;announce(`${preferences.theme} appearance.`);});
$("#hide-window").addEventListener("click",()=>{$(".app-window").hidden=true;$(".reopen-panel").hidden=false;$("#reopen-window").focus();});
$("#reopen-window").addEventListener("click",()=>{$(".app-window").hidden=false;$(".reopen-panel").hidden=true;$(".nav-item.active").focus();});
$("#minimize-window").addEventListener("click",()=>{showView("live",false);toggleCompact();});
$("#expand-window").addEventListener("click",()=>{const expanded=$(".app-window").classList.toggle("expanded");$("#expand-window").setAttribute("aria-label",expanded?"Restore preview window size":"Expand preview window");});
document.addEventListener("keydown",event=>{
  if(event.key.toLowerCase()==="c"&&!event.metaKey&&!event.ctrlKey&&!event.altKey&&!event.target.closest("input,select,textarea,[contenteditable]")&&!$(".app-window").hidden) {event.preventDefault();showView("live",false);toggleCompact();}
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change",()=>{if(preferences.theme==="system")applyPreferences();});
matchMedia("(prefers-reduced-transparency: reduce)").addEventListener("change",applyPreferences);

const mobilePhase=document.createElement("div"); mobilePhase.className="mobile-phase";
mobilePhase.innerHTML='<label class="field-label" for="mobile-phase-select">Preview state</label><select id="mobile-phase-select"><option value="recruit">Recruit phase</option><option value="combat">Combat phase</option><option value="waiting">Waiting for a match</option><option value="access">Log access unavailable</option></select>';
$("#view-live .view-heading").after(mobilePhase);
applyPreferences(); renderOpponents(); renderOverlay(); showView("live",false);
