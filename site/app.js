/* VexPredict site: plain JS, reads the static JSON written by vexpredict.publish. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const app = $("#app");
const cache = new Map();
const ROUND = { 2: "Q", 6: "R16 ", 3: "QF ", 4: "SF ", 5: "F " };
const TAGS = ["Strong auton", "Good driver", "Consistent", "Fast cycles", "Plays defense", "Breaks down", "Great partner"];

let SEASON = null;   // slug
let META = null;
let NUMBERS = {};    // team id -> number

// ---------- helpers ----------
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
let bundleLoad = null;
async function loadBundle() {
  // Packaged builds ship the data as a few chunk files instead of thousands of small ones.
  const parts = await Promise.all(window.__VP_CHUNKS.map(u => fetch(u).then(r => {
    if (!r.ok) throw new Error(`${r.status} ${u}`); return r.json(); })));
  window.__VP_DATA = Object.assign({}, ...parts);
}
async function get(path) {
  if (window.__VP_CHUNKS && !window.__VP_DATA) await (bundleLoad = bundleLoad || loadBundle());
  if (window.__VP_DATA) { if (path in window.__VP_DATA) return window.__VP_DATA[path]; throw new Error(`Not published: ${path}`); }
  if (cache.has(path)) return cache.get(path);
  const p = fetch(`data/${path}`).then(r => { if (!r.ok) throw new Error(`${r.status} ${path}`); return r.json(); });
  cache.set(path, p);
  try { return await p; } catch (e) { cache.delete(path); throw e; }
}
const store = {
  get(k, d) { try { const v = localStorage.getItem(`vp:${k}`); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(`vp:${k}`, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};
const myTeam = () => store.get(`${SEASON}:me`, window.__VP_DEMO_ME ?? null);
const notes = () => store.get(`${SEASON}:notes`, {});
function saveNote(id, note) { const n = notes(); if (!note.text && !note.tags.length) delete n[id]; else n[id] = note; store.set(`${SEASON}:notes`, n); }
const pct = p => `${Math.round(p * 100)}%`;
const rnd = x => (x == null ? "–" : Math.round(x));
const num = id => NUMBERS[id] || id;
const teamLink = (id, extra = "") => `<a href="#/team/${id}" class="${myTeam() === id ? "me" : ""}" ${extra}>${esc(num(id))}</a>`;
function statusPill(s) {
  const label = { live: "Live", upcoming: "Upcoming", done: "Finished", "skills-only": "Skills only", "no-results": "No results" }[s] || s;
  return `<span class="pill ${s === "live" ? "live" : ""}">${label}</span>`;
}
function matchName(m) { return m.round === 2 ? `Q${m.num}` : `${ROUND[m.round] || ""}${m.inst}-${m.num}`; }
function tug(p, cls = "") {
  const r = Math.max(0.04, Math.min(0.96, p));
  return `<div class="tug ${cls}" role="img" aria-label="Red ${pct(p)} to win, blue ${pct(1 - p)}">
    <b class="r" style="flex-basis:${r * 100}%">${p >= 0.5 ? pct(p) : ""}</b><b class="b" style="flex-basis:${(1 - r) * 100}%">${p < 0.5 ? pct(1 - p) : ""}</b></div>`;
}
function matchRow(m, played) {
  let mid;
  if (played) {
    const rw = m.rs > m.bs, bw = m.bs > m.rs;
    mid = `<div class="vs"><span class="${rw ? "w" : ""}">${m.rs}</span>–<span class="${bw ? "w" : ""}">${m.bs}</span></div>`;
  } else {
    mid = `<div class="vs"><span class="pred">${rnd(m.pr)}–${rnd(m.pb)}</span></div>`;
  }
  let verdict = "";
  if (played && m.p != null && m.rs !== m.bs) {
    const hit = (m.p >= 0.5) === (m.rs > m.bs);
    verdict = `<div class="verdict ${hit ? "hit" : "miss"}">${hit ? "Called it" : "Upset"} · predicted ${rnd(m.pr)}–${rnd(m.pb)}</div>`;
  }
  return `<div class="m"><div class="id">${matchName(played ? m : { ...m, round: 2 })}</div>
    <div class="teams"><div class="side red">${m.red.map(t => teamLink(t)).join("")}</div>${mid}<div class="side blue">${m.blue.map(t => teamLink(t)).join("")}</div></div>
    <div class="bar">${m.p != null ? tug(m.p, "small") : ""}${verdict}</div></div>`;
}
function setTitle(t) { document.title = t ? `${t} | VexPredict` : "VexPredict"; }
function navCurrent(page) {
  document.querySelectorAll(".nav a").forEach(a => a.toggleAttribute("aria-current", a.getAttribute("href") === `#/${page}`));
  document.querySelectorAll(".nav a[aria-current]").forEach(a => a.setAttribute("aria-current", "page"));
}

// ---------- boot ----------
async function boot() {
  let seasons = [];
  try { seasons = await get("seasons.json"); } catch {
    app.innerHTML = `<div class="panel"><h1>No data yet</h1><p class="lede">Run <code>python3 -m vexpredict.publish --season "Push Back"</code> to build the data this site reads.</p></div>`;
    return;
  }
  const want = new URLSearchParams(location.search).get("season");
  const pick = seasons.find(s => s.slug === want) || [...seasons].reverse().find(s => !s.synthetic) || seasons[seasons.length - 1];
  SEASON = pick.slug;
  [META, NUMBERS] = await Promise.all([get(`${SEASON}/meta.json`), get(`${SEASON}/team_numbers.json`)]);
  $("#demo").hidden = !META.synthetic;
  $("#generated").textContent = `${META.season}. Data updated ${META.generated.replace("T", " ").replace("+00:00", " UTC")}.`;
  setupSearch();
  window.addEventListener("hashchange", route);
  route();
}

async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [page, id, sub] = parts;
  navCurrent(page || "");
  window.scrollTo(0, 0);
  try {
    if (!page) await home();
    else if (page === "event") await eventPage(+id, sub || "matches");
    else if (page === "team") await teamPage(+id);
    else if (page === "leaderboard") await leaderboard();
    else if (page === "events") await eventsPage();
    else if (page === "accuracy") await accuracy();
    else app.innerHTML = `<p>That page doesn't exist. <a href="#/">Go to the home page</a>.</p>`;
  } catch (e) {
    console.error(e);
    app.innerHTML = `<div class="panel"><h1>Couldn't load this page</h1><p class="lede">${esc(e.message)}. The data for it may not be published yet.</p></div>`;
  }
  app.focus({ preventScroll: true });
}

// ---------- search ----------
function setupSearch() {
  const input = $("#q"), list = $("#suggest");
  const byNumber = Object.entries(NUMBERS).map(([id, n]) => ({ id: +id, n: String(n) }));
  const show = () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { list.hidden = true; return; }
    const teams = byNumber.filter(t => t.n.toLowerCase().startsWith(q)).slice(0, 6)
      .map(t => `<li><a href="#/team/${t.id}">${esc(t.n)} <small>team</small></a></li>`);
    const evs = META.events.filter(e => e.name.toLowerCase().includes(q) || e.sku.toLowerCase().includes(q)).slice(0, 6)
      .map(e => `<li><a href="#/event/${e.id}">${esc(e.name)} <small>${e.date}</small></a></li>`);
    const all = teams.concat(evs);
    list.innerHTML = all.length ? all.join("") : `<li class="muted" style="padding:8px 10px">No team or event matches "${esc(input.value)}"</li>`;
    list.hidden = false;
  };
  input.addEventListener("input", show);
  input.addEventListener("focus", show);
  document.addEventListener("click", e => { if (!$("#search").contains(e.target)) list.hidden = true; });
  list.addEventListener("click", () => { list.hidden = true; input.value = ""; });
  $("#search").addEventListener("submit", e => {
    e.preventDefault();
    const first = list.querySelector("a");
    if (first) { location.hash = first.getAttribute("href"); list.hidden = true; input.value = ""; }
  });
}

// ---------- home ----------
async function home() {
  setTitle("");
  const live = META.events.filter(e => e.status === "live");
  const upcoming = META.events.filter(e => e.status === "upcoming").reverse().slice(0, 5);
  const board = (await get(`${SEASON}/leaderboard.json`)).slice(0, 10);
  let next = "";
  const me = myTeam();
  if (me) {
    for (const e of live) {
      const ev = await get(`${SEASON}/events/${e.id}.json`);
      const m = ev.pending.find(p => p.red.includes(me) || p.blue.includes(me));
      if (m) {
        const red = m.red.includes(me);
        const p = red ? m.p : 1 - m.p;
        next = `<section class="panel hero-match"><h2>Your next match: ${esc(num(me))} in Q${m.num}</h2>
          <p class="lede">${pct(p)} chance to win at ${esc(ev.name)}. Predicted score ${rnd(red ? m.pr : m.pb)} to ${rnd(red ? m.pb : m.pr)}.</p>
          <div style="margin:12px 0">${tug(m.p)}</div>
          <p><a href="#/event/${e.id}/brief">Open the match brief</a></p></section>`;
        break;
      }
    }
  }
  app.innerHTML = `
    <h1>Who wins, by how much, and who to pick</h1>
    <p class="lede">Predictions for VEX V5RC High School. Every match gets a win probability before it's played, every event gets a ranking forecast, and the accuracy is published.</p>
    ${next}
    ${live.length ? `<h2>Live now</h2><ul class="list panel">${live.map(evItem).join("")}</ul>` : ""}
    ${upcoming.length ? `<h2>Coming up</h2><ul class="list panel">${upcoming.map(evItem).join("")}</ul>` : ""}
    <h2>Top rated teams</h2>
    <div class="panel tablewrap">${boardTable(board)}<p><a href="#/leaderboard">See all ${META.teams_rated} rated teams</a></p></div>
    ${me ? "" : `<p class="callout">Open your team's page and choose "This is my team" to see your next match here.</p>`}`;
}
function evItem(e) {
  return `<li><a href="#/event/${e.id}">${esc(e.name)}</a><span class="row"><span class="muted">${e.date}</span>${statusPill(e.status)}</span></li>`;
}
function boardTable(rows) {
  return `<table><thead><tr><th class="n">#</th><th>Team</th><th class="n">Rating</th><th class="n">Record</th><th class="n">Best skills</th><th>Region</th></tr></thead><tbody>
    ${rows.map(b => `<tr class="${myTeam() === b.id ? "mine" : ""}"><td class="n">${b.rank}</td><td class="t"><a href="#/team/${b.id}">${esc(b.number)}</a> <span class="muted">${esc(b.name)}</span></td>
      <td class="n">${rnd(b.rating)}</td><td class="n">${b.record}</td><td class="n">${b.skills ?? "–"}</td><td>${esc(b.region || b.country || "")}</td></tr>`).join("")}
  </tbody></table>`;
}

// ---------- events ----------
async function eventsPage() {
  setTitle("Events");
  app.innerHTML = `<h1>Events</h1><div class="row" style="margin:14px 0">
      <input type="text" id="evq" placeholder="Filter by name or event code" style="max-width:340px" aria-label="Filter events">
      <select id="evs" aria-label="Status"><option value="">All events</option><option value="live">Live</option><option value="upcoming">Upcoming</option><option value="done">Finished</option></select>
    </div><ul class="list panel" id="evlist"></ul>`;
  const draw = () => {
    const q = $("#evq").value.toLowerCase(), s = $("#evs").value;
    const rows = META.events.filter(e => e.status !== "skills-only" && e.status !== "no-results")
      .filter(e => (!s || e.status === s) && (!q || e.name.toLowerCase().includes(q) || e.sku.toLowerCase().includes(q)));
    $("#evlist").innerHTML = rows.slice(0, 300).map(evItem).join("") || `<li class="empty">No events match. Clear the filter to see all.</li>`;
  };
  $("#evq").addEventListener("input", draw); $("#evs").addEventListener("change", draw); draw();
}

// Big events (Worlds, some Signature events and States) split into divisions
// that rank and pick alliances separately; show one division at a time.
function subSim(sim, d) {
  if (!sim) return sim;
  const t = Object.fromEntries(Object.entries(sim.teams).filter(([, v]) => v.div == null || v.div === d));
  if (!Object.keys(t).length) return null;
  return { ...sim, teams: t, captains: sim.by_div?.[d] ?? sim.captains };
}
function divisionView(ev, d) {
  const inD = x => x.div == null || x.div === d;
  return { ...ev, teams: ev.teams.filter(inD), matches: ev.matches.filter(inD), pending: ev.pending.filter(inD),
           sim_pre: subSim(ev.sim_pre, d), sim_live: subSim(ev.sim_live, d), pickKey: `${SEASON}:picks:${ev.id}:${d}` };
}
async function eventPage(id, tab) {
  const ev = await get(`${SEASON}/events/${id}.json`);
  setTitle(ev.name);
  const teams = new Map(ev.teams.map(t => [t.id, t]));
  for (const t of ev.teams) NUMBERS[t.id] = t.number;
  const me = myTeam();
  const iAmHere = me && teams.has(me);
  const divs = ev.divisions || [];
  const divKey = `${SEASON}:div:${ev.id}`;
  let d = null, view = ev;
  if (divs.length > 1) {
    d = store.get(divKey, null) ?? (iAmHere ? teams.get(me).div : null) ?? divs[0].id;
    if (!divs.some(x => x.id === d)) d = divs[0].id;
    view = divisionView(ev, d);
  }
  const tabs = [["matches", "Matches"], ["forecast", "Ranking forecast"], ["picks", "Pick list"], ["teams", "Teams"]];
  if (iAmHere) tabs.splice(1, 0, ["brief", `Brief for ${num(me)}`]);
  const played = view.matches.length, left = view.pending.length;
  app.innerHTML = `
    <div class="row"><a href="#/events">Events</a>${statusPill(ev.status)}</div>
    <h1 style="margin-top:8px">${esc(ev.name)}</h1>
    ${d != null ? `<div class="row divpick"><label for="div">Division</label><select id="div">${divs.map(x =>
      `<option value="${x.id}" ${x.id === d ? "selected" : ""}>${esc(x.name)}${x.finals ? " (finals between divisions)" : ""}${iAmHere && teams.get(me).div === x.id ? ` (${esc(num(me))})` : ""}</option>`).join("")}</select>
      <span class="muted">${divs.filter(x => !x.finals).length} divisions rank and pick alliances separately</span></div>` : ""}
    <div class="stats">
      <div class="stat"><b>${view.teams.length}</b><span>teams${d != null ? " in this division" : ""}</span></div>
      <div class="stat"><b>${played}</b><span>matches played</span></div>
      ${left ? `<div class="stat"><b>${left}</b><span>qualification matches left</span></div>` : ""}
      ${played ? `<div class="stat"><b>${hitRate(view.matches)}</b><span>of results called correctly</span></div>` : ""}
    </div>
    <p class="muted">${ev.date} · ${esc(ev.sku)}</p>
    <nav class="tabs" aria-label="Event sections">${tabs.map(([k, l]) => `<a href="#/event/${id}/${k}" ${k === tab ? 'aria-current="page"' : ""}>${esc(l)}</a>`).join("")}</nav>
    <div id="tab"></div>`;
  const sel = $("#div");
  if (sel) sel.onchange = () => { store.set(divKey, +sel.value); eventPage(id, tab); };
  const el = $("#tab");
  if (tab === "forecast") return forecastTab(el, view, teams);
  if (tab === "picks") return picksTab(el, view, teams);
  if (tab === "teams") return teamsTab(el, view);
  if (tab === "brief") return briefTab(el, ev, teams);   // your matches, whatever division is on screen
  return matchesTab(el, view);
}
function hitRate(ms) {
  const d = ms.filter(m => m.rs !== m.bs && m.p != null);
  if (!d.length) return "–";
  return pct(d.filter(m => (m.p >= 0.5) === (m.rs > m.bs)).length / d.length);
}
function matchesTab(el, ev) {
  const me = myTeam();
  const mine = m => m.red.includes(me) || m.blue.includes(me);
  let only = store.get("onlyMine", false) && ev.teams.some(t => t.id === me);
  const draw = () => {
    const f = ms => (only ? ms.filter(mine) : ms);
    const quals = f(ev.matches.filter(m => m.round === 2)), elims = f(ev.matches.filter(m => m.round !== 2));
    const pend = f(ev.pending);
    el.innerHTML = `
      ${ev.teams.some(t => t.id === me) ? `<p><button id="only" aria-pressed="${only}">Only ${esc(num(me))}'s matches</button></p>` : ""}
      ${pend.length ? `<h2>Still to play</h2><p class="muted">Grey numbers are predicted scores, from each team's current rating.</p><div class="matches">${pend.map(m => matchRow(m, false)).join("")}</div>` : ""}
      ${elims.length ? `<h2>Eliminations</h2><div class="matches">${elims.map(m => matchRow(m, true)).join("")}</div>` : ""}
      ${quals.length ? `<h2>Qualifications</h2><p class="muted">Each bar is the prediction made before the match was played.</p><div class="matches">${quals.slice().reverse().map(m => matchRow(m, true)).join("")}</div>` : ""}
      ${!pend.length && !quals.length && !elims.length ? `<p class="empty">No matches yet. Check the ranking forecast for a pre-event prediction.</p>` : ""}`;
    const b = $("#only");
    if (b) b.onclick = () => { only = !only; store.set("onlyMine", only); draw(); };
  };
  draw();
}
function forecastTab(el, ev, teams) {
  const sim = ev.sim_live || ev.sim_pre;
  if (!sim) {
    el.innerHTML = `<p class="empty">${ev.divisions_pending ? "No forecast yet: this event splits into divisions, and teams aren't assigned to one until the schedule is out."
      : ev.divisions?.length > 1 && !ev.teams.length ? "These are the finals between division winners, so there are no rankings to forecast."
      : "No forecast for this event: it needs at least 8 teams with a schedule or a registered team list."}</p>`;
    return;
  }
  const live = !!ev.sim_live;
  const done = ev.status === "done";
  const rows = Object.entries(sim.teams).map(([id, s]) => ({ id: +id, ...s, t: teams.get(+id) || {} }))
    .sort((a, b) => a.mean_rank - b.mean_rank);
  let hits = "";
  if (done && !live) {
    const k = sim.captains;
    const predTop = new Set(rows.slice(0, k).map(r => r.id));
    const actualTop = rows.filter(r => r.t.rank && r.t.rank <= k).length ? rows.filter(r => r.t.rank <= k) : [];
    const overlap = actualTop.filter(r => predTop.has(r.id)).length;
    if (actualTop.length) hits = `<p class="callout">${overlap} of the ${k} teams we picked to finish top ${k} before the event actually did.</p>`;
  }
  el.innerHTML = `
    <p class="lede">${live ? "The rest of qualifications, simulated" : "Qualifications simulated before the first match"} 1,500 times with each team's rating, the schedule${ev.status === "upcoming" ? " (random schedules until the real one is out)" : ""}, and V5RC ranking rules: win points, autonomous points, then strength of schedule. Top ${sim.captains} become alliance captains.</p>
    ${hits}
    <div class="panel tablewrap"><table><thead><tr><th>Team</th>${ev.status !== "upcoming" ? `<th class="n">${done ? "Final" : "Now"}</th><th class="n hide-m">Record</th>` : ""}
      <th class="n hide-m">Rating</th><th class="n">Expected</th><th>Captain odds</th><th class="n hide-m">Rank 1</th></tr></thead><tbody>
      ${rows.map(r => `<tr class="${myTeam() === r.id ? "mine" : ""}"><td class="t">${teamLink(r.id)}</td>
        ${ev.status !== "upcoming" ? `<td class="n">${r.t.rank ?? "–"}</td><td class="n hide-m">${r.t.record ?? "–"}</td>` : ""}
        <td class="n hide-m">${rnd(live || !done ? r.t.rating_now : r.t.rating_pre)}</td><td class="n">${r.mean_rank.toFixed(1)}</td>
        <td style="white-space:nowrap"><span class="meter"><i style="width:${r.p_captain * 100}%"></i></span>${pct(r.p_captain)}</td><td class="n hide-m">${pct(r.p_first)}</td></tr>`).join("")}
    </tbody></table></div>`;
}
function teamsTab(el, ev) {
  const n = notes();
  const rows = ev.teams.slice().sort((a, b) => (b.rating_now ?? -1) - (a.rating_now ?? -1));
  el.innerHTML = `<div class="panel tablewrap"><table><thead><tr><th>Team</th><th class="n">Rating</th><th class="n">Skills here</th><th class="n">Rank</th><th>Your notes</th></tr></thead><tbody>
    ${rows.map(t => `<tr class="${myTeam() === t.id ? "mine" : ""}"><td class="t">${teamLink(t.id)} <span class="muted">${esc(t.name)}</span></td><td class="n">${rnd(t.rating_now)}</td>
      <td class="n">${t.skills ?? "–"}</td><td class="n">${t.rank ?? "–"}</td><td>${esc((n[t.id]?.tags || []).join(", "))}</td></tr>`).join("")}
  </tbody></table></div>`;
}

// ---------- match brief ----------
function briefTab(el, ev, teams) {
  const me = myTeam();
  const sim = ev.sim_live || ev.sim_pre || { rates: {} };
  const n = notes();
  const card = (id, color) => {
    const t = teams.get(id) || {}; const r = sim.rates?.[id] || {}; const note = n[id];
    return `<div class="card ${color}">${teamLink(id)} <p>${esc(t.name || "")}</p>
      <p>Rating ${rnd(t.rating_now)}${t.rank ? ` · rank ${t.rank}` : ""}${t.skills ? ` · skills ${t.skills}` : ""}</p>
      ${r.awp != null ? `<p>Auton win point ${pct(r.awp)} · auton bonus ${pct(r.auton)}</p>` : ""}
      ${note ? `<p class="note">${esc([...(note.tags || []), note.text].filter(Boolean).join(" · "))}</p>` : ""}</div>`;
  };
  const block = (m, played) => {
    const red = m.red.includes(me);
    const p = red ? m.p : 1 - m.p;
    const partner = (red ? m.red : m.blue).filter(t => t !== me);
    const opp = red ? m.blue : m.red;
    const head = played ? `${matchName(m)}: ${red ? m.rs : m.bs}–${red ? m.bs : m.rs} ${((red ? m.rs > m.bs : m.bs > m.rs) ? "win" : m.rs === m.bs ? "tie" : "loss")}`
      : `Q${m.num}: ${pct(p)} to win`;
    return `<section class="panel brief"><h3 style="margin:0">${head}</h3>
      <p class="muted" style="margin:0">Predicted ${rnd(red ? m.pr : m.pb)} to ${rnd(red ? m.pb : m.pr)}. You're on ${red ? "red" : "blue"}.</p>
      ${tug(m.p, "small")}
      <div class="who"><div><h3>With</h3>${partner.map(t => card(t, red ? "red" : "blue")).join("")}</div>
      <div><h3>Against</h3>${opp.map(t => card(t, red ? "blue" : "red")).join("")}</div></div></section>`;
  };
  const pend = ev.pending.filter(m => m.red.includes(me) || m.blue.includes(me));
  const done = ev.matches.filter(m => m.red.includes(me) || m.blue.includes(me)).reverse();
  el.innerHTML = `${pend.length ? `<h2>Coming up for ${esc(num(me))}</h2>${pend.map(m => block(m, false)).join("")}` : `<p class="muted">No unplayed matches for ${esc(num(me))} here.</p>`}
    ${done.length ? `<h2>Played</h2>${done.map(m => block(m, true)).join("")}` : ""}
    <p class="muted">Auton win point: how often the team earns it. Auton bonus: how often its alliance wins the autonomous bonus. Both come from earlier events. Notes are your own scouting tags from each team's page, saved in this browser.</p>`;
}

// ---------- pick list ----------
function picksTab(el, ev, teams) {
  const key = ev.pickKey || `${SEASON}:picks:${ev.id}`;
  const state = store.get(key, { picked: [], dnp: [], w: 0.25 });
  const sim = ev.sim_live || ev.sim_pre || { rates: {} };
  const me = myTeam();
  const pool = ev.teams.filter(t => t.id !== me && t.rating_now != null);
  const prank = vals => { const s = [...vals].sort((a, b) => a - b); return v => (s.length > 1 ? s.indexOf(v) / (s.length - 1) : 0.5); };
  const rp = prank(pool.map(t => t.rating_now));
  const autoVal = t => { const r = sim.rates?.[t.id]; return r ? (r.awp ?? 0) + (r.auton ?? 0.5) : 0.5; };
  const ap = prank(pool.map(autoVal));
  const draw = () => {
    const n = notes();
    const score = t => (1 - state.w) * rp(t.rating_now) + state.w * ap(autoVal(t));
    const order = pool.slice().sort((a, b) => {
      const rank = t => (state.picked.includes(t.id) ? 2 : state.dnp.includes(t.id) ? 1 : 0);
      return rank(a) - rank(b) || score(b) - score(a);
    });
    let pos = 0;
    el.innerHTML = `
      <p class="lede">Ranked by rating, plus how much weight you put on autonomous. Mark teams as they get picked during alliance selection and the list reorders.</p>
      <div class="panel"><div class="row">
        <label for="w">Weight on autonomous</label>
        <input id="w" type="range" min="0" max="1" step="0.05" value="${state.w}" style="flex:1;min-width:140px">
        <span class="num" id="wv">${pct(state.w)}</span>
        <button id="reset">Clear picks</button>
      </div>${me ? "" : `<p class="muted" style="margin-bottom:0">Set your team on its team page to leave it out of this list.</p>`}</div>
      <div class="panel tablewrap"><table><thead><tr><th class="n">#</th><th>Team</th><th class="n">Rating</th><th class="n">Auton</th><th><span class="sr">Actions</span></th></tr></thead><tbody>
      ${order.map(t => {
        const picked = state.picked.includes(t.id), dnp = state.dnp.includes(t.id);
        const r = sim.rates?.[t.id];
        return `<tr class="${picked ? "picked" : dnp ? "dnp" : ""}"><td class="n">${picked || dnp ? "" : ++pos}</td>
          <td class="t">${teamLink(t.id)}${n[t.id]?.tags?.length ? `<span class="subnote">${esc(n[t.id].tags.join(", "))}</span>` : ""}</td><td class="n">${rnd(t.rating_now)}</td>
          <td class="n">${r ? pct(r.auton) : "–"}</td>
          <td><div class="acts"><button class="iconbtn" data-a="picked" data-id="${t.id}" aria-pressed="${picked}" aria-label="${esc(t.number)} was picked">Picked</button>
          <button class="iconbtn" data-a="dnp" data-id="${t.id}" aria-pressed="${dnp}" aria-label="Skip ${esc(t.number)}">Skip</button></div></td></tr>`;
      }).join("")}</tbody></table></div>`;
    $("#w").oninput = e => { state.w = +e.target.value; $("#wv").textContent = pct(state.w); };
    $("#w").onchange = () => { store.set(key, state); draw(); };
    $("#reset").onclick = () => { state.picked = []; state.dnp = []; store.set(key, state); draw(); };
    el.querySelectorAll("button[data-a]").forEach(b => b.onclick = () => {
      const id = +b.dataset.id, list = state[b.dataset.a], other = state[b.dataset.a === "picked" ? "dnp" : "picked"];
      const i = list.indexOf(id);
      if (i >= 0) list.splice(i, 1); else { list.push(id); const j = other.indexOf(id); if (j >= 0) other.splice(j, 1); }
      store.set(key, state); draw();
    });
  };
  draw();
}

// ---------- team ----------
async function teamPage(id) {
  const t = await get(`${SEASON}/teams/${id}.json`);
  setTitle(t.number);
  NUMBERS[id] = t.number;
  const me = myTeam() === id;
  const decided = t.matches.filter(m => m.score !== m.opp_score && m.p_win != null);
  const right = decided.filter(m => (m.p_win >= 0.5) === (m.score > m.opp_score)).length;
  const evNames = Object.fromEntries(META.events.map(e => [e.id, e.name]));
  const note = notes()[id] || { text: "", tags: [] };
  app.innerHTML = `
    <div class="row"><a href="#/leaderboard">Ratings</a></div>
    <h1 style="margin-top:8px">${esc(t.number)} <span class="muted" style="font-weight:500">${esc(t.name)}</span></h1>
    <p class="muted">${esc([t.region, t.country].filter(Boolean).join(", "))}</p>
    <div class="stats">
      <div class="stat"><b>${rnd(t.rating)}</b><span>rating (points added per match)</span></div>
      <div class="stat"><b>${t.rank ? "#" + t.rank : "–"}</b><span>of ${META.teams_rated} HS teams</span></div>
      <div class="stat"><b>${t.skills ?? "–"}</b><span>best skills</span></div>
      <div class="stat"><b>${decided.length ? pct(right / decided.length) : "–"}</b><span>of its results predicted right</span></div>
    </div>
    <p><button id="me" class="${me ? "" : "primary"}" aria-pressed="${me}">${me ? `${esc(t.number)} is your team` : "This is my team"}</button></p>
    ${t.history.length > 1 ? `<section class="panel"><h2>Rating through the season</h2>${spark(t.history)}</section>` : ""}
    <section class="panel"><h2>Scouting notes</h2>
      <div class="tags" id="tags">${TAGS.map(g => `<button class="tag" aria-pressed="${note.tags.includes(g)}">${esc(g)}</button>`).join("")}</div>
      <label class="sr" for="nt">Notes</label>
      <textarea id="nt" rows="3" style="margin-top:10px" placeholder="What did you see? Drivetrain, autons, reliability…">${esc(note.text)}</textarea>
      <div class="row" style="margin-top:8px"><span class="muted" id="saved">Saved in this browser.</span>
        <button id="exp" class="iconbtn">Export all notes</button><label class="btn iconbtn" style="font-weight:700">Import notes<input id="imp" type="file" accept="application/json" hidden></label></div>
    </section>
    <h2>Matches</h2>
    ${t.events.slice().reverse().map(eid => {
      const ms = t.matches.filter(m => m.event === eid);
      return `<section class="panel"><h3 style="margin-top:0"><a href="#/event/${eid}">${esc(evNames[eid] || "Event " + eid)}</a></h3><ul class="list">
        ${ms.slice().reverse().map(m => {
          const res = m.score > m.opp_score ? "W" : m.score < m.opp_score ? "L" : "T";
          const hit = m.score !== m.opp_score ? ((m.p_win >= 0.5) === (res === "W") ? "hit" : "miss") : "";
          return `<li><span><b class="num">${matchName(m)}</b> with ${m.partner.map(x => teamLink(x)).join(" ")} vs ${m.opp.map(x => teamLink(x)).join(" ")}</span>
            <span class="num">${res} ${m.score}–${m.opp_score} <span class="verdict ${hit}" style="display:inline">${pct(m.p_win)} to win</span></span></li>`;
        }).join("")}</ul></section>`;
    }).join("") || `<p class="empty">No matches this season yet.</p>`}`;
  $("#me").onclick = () => { store.set(`${SEASON}:me`, me ? null : id); teamPage(id); };
  const save = () => {
    const tags = [...document.querySelectorAll("#tags .tag[aria-pressed=true]")].map(b => b.textContent);
    saveNote(id, { text: $("#nt").value.trim(), tags });
    $("#saved").textContent = "Saved in this browser.";
  };
  document.querySelectorAll("#tags .tag").forEach(b => b.onclick = () => { b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") !== "true"); save(); });
  $("#nt").addEventListener("input", () => { $("#saved").textContent = "Saving…"; clearTimeout(window._nt); window._nt = setTimeout(save, 400); });
  if (window.__VP_DATA) $("#exp").textContent = "Copy all notes";
  $("#exp").onclick = () => {
    const text = JSON.stringify({ season: SEASON, notes: notes() }, null, 2);
    if (window.__VP_DATA) {
      navigator.clipboard.writeText(text).then(() => { $("#saved").textContent = "Copied. Paste it to a teammate."; },
        () => { $("#saved").textContent = "Copy isn't allowed here."; });
      return;
    }
    const blob = new Blob([text], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `scouting-notes-${SEASON}.json` });
    a.click(); URL.revokeObjectURL(a.href);
  };
  $("#imp").onchange = async e => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      const merged = { ...notes() };
      for (const [k, v] of Object.entries(data.notes || {})) {
        const cur = merged[k] || { text: "", tags: [] };
        merged[k] = { text: [cur.text, v.text].filter(Boolean).filter((x, i, a) => a.indexOf(x) === i).join("\n"),
                      tags: [...new Set([...(cur.tags || []), ...(v.tags || [])])] };
      }
      store.set(`${SEASON}:notes`, merged);
      $("#saved").textContent = `Imported notes for ${Object.keys(data.notes || {}).length} teams.`;
      setTimeout(() => teamPage(id), 900);
    } catch { $("#saved").textContent = "That file isn't a notes export from this site."; }
  };
}
function spark(h) {
  const pts = h.filter(x => x.rating != null);
  const W = 600, H = 70, pad = 6;
  const ys = pts.map(p => p.rating), lo = Math.min(...ys), hi = Math.max(...ys);
  const x = i => pad + (i * (W - 2 * pad)) / Math.max(pts.length - 1, 1);
  const y = v => H - pad - ((v - lo) / Math.max(hi - lo, 1)) * (H - 2 * pad);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.rating).toFixed(1)}`).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Rating went from ${rnd(ys[0])} to ${rnd(ys[ys.length - 1])} over ${pts.length} events">
    <path d="${d}" vector-effect="non-scaling-stroke"/></svg>
    <div class="row muted" style="justify-content:space-between;font-size:14px"><span>${pts[0].date}: ${rnd(ys[0])}</span><span>${pts[pts.length - 1].date}: ${rnd(ys[ys.length - 1])}</span></div>`;
}

// ---------- leaderboard ----------
async function leaderboard() {
  setTitle("Ratings");
  const board = await get(`${SEASON}/leaderboard.json`);
  const regions = [...new Set(board.map(b => b.region || b.country).filter(Boolean))].sort();
  let shown = 100;
  app.innerHTML = `<h1>Team ratings</h1>
    <p class="lede">A rating is the points a team adds to its alliance's score in an average match. Two partners' ratings added together give their predicted score.</p>
    <div class="row" style="margin:14px 0"><input type="text" id="lq" placeholder="Filter by number or name" style="max-width:300px" aria-label="Filter teams">
    <select id="lr" aria-label="Region"><option value="">All regions</option>${regions.map(r => `<option>${esc(r)}</option>`).join("")}</select></div>
    <div class="panel tablewrap" id="lb"></div>`;
  const draw = () => {
    const q = $("#lq").value.toLowerCase(), r = $("#lr").value;
    const rows = board.filter(b => (!r || (b.region || b.country) === r) && (!q || b.number.toLowerCase().includes(q) || (b.name || "").toLowerCase().includes(q)));
    $("#lb").innerHTML = (rows.length ? boardTable(rows.slice(0, shown)) : `<p class="empty">No teams match. Clear the filter to see everyone.</p>`)
      + (rows.length > shown ? `<p><button id="more">Show 100 more</button></p>` : "");
    const more = $("#more"); if (more) more.onclick = () => { shown += 100; draw(); };
  };
  $("#lq").addEventListener("input", () => { shown = 100; draw(); });
  $("#lr").addEventListener("change", () => { shown = 100; draw(); });
  draw();
}

// ---------- accuracy ----------
async function accuracy() {
  setTitle("Accuracy");
  const acc = await get(`${SEASON}/accuracy.json`).catch(() => ({}));
  let html = `<h1>How accurate is it?</h1>
    <p class="lede">Every model here is tested on a full past season. It predicts each match before seeing the result, settings are tuned only on the first part of the season, and the numbers below come from the rest, State championships and Worlds included.</p>`;
  if (acc.metrics) {
    const r = acc.metrics.results;
    if (acc.metrics.season && acc.metrics.season !== META.season) html += `<p class="callout">These results are from testing on ${esc(acc.metrics.season)}, the last full season. This season's predictions use the settings tuned there.</p>`;
    const slices = ["HS, all matches", "HS eliminations", "HS Worlds"];
    for (const s of slices) {
      const n = Object.values(r)[0].slices[s]?.n;
      if (!n) continue;
      const rows = Object.entries(r).filter(([, v]) => v.slices[s]?.n).sort((a, b) => a[1].slices[s].brier - b[1].slices[s].brier);
      html += `<h2>${esc(s)} <span class="muted" style="font-weight:500">(${n.toLocaleString()} matches)</span></h2><div class="panel tablewrap"><table>
        <thead><tr><th>Model</th><th class="n">Winner right</th><th class="n">Brier</th><th class="n">Score error</th></tr></thead><tbody>
        ${rows.map(([name, v], i) => { const m = v.slices[s]; return `<tr${i === 0 ? ' class="mine"' : ""}><td>${esc(name)}</td><td class="n">${(m.accuracy * 100).toFixed(1)}%</td>
          <td class="n">${m.brier.toFixed(3)}</td><td class="n">${m.score_mae != null ? m.score_mae.toFixed(1) : "–"}</td></tr>`; }).join("")}
        </tbody></table></div>`;
    }
    html += `<p class="muted">Brier score measures how good the probabilities are, not just the winner: 0 is perfect and 0.25 is a coin flip. Score error is the average miss on each alliance's score, in points.</p>`;
  } else {
    html += `<p class="callout">The backtest hasn't been published for this season yet. Run <code>python3 -m vexpredict.backtest</code> and then publish again.</p>`;
  }
  if (acc.simcheck) {
    const c = acc.simcheck.cut_0, h = acc.simcheck.cut_50;
    html += `<h2>Ranking forecasts</h2><div class="panel tablewrap"><table><thead><tr><th>When</th><th class="n">Simulator</th><th class="n">Current standings</th></tr></thead><tbody>
      ${c?.divisions ? `<tr><td>Before the first match</td><td class="n">${c.spearman_sim.toFixed(2)}</td><td class="n">${c.spearman_standings.toFixed(2)}</td></tr>` : ""}
      ${h?.divisions ? `<tr><td>Halfway through quals</td><td class="n">${h.spearman_sim.toFixed(2)}</td><td class="n">${h.spearman_standings.toFixed(2)}</td></tr>` : ""}
      </tbody></table><p class="muted">Rank correlation between predicted and actual final rankings: 1 is a perfect order, 0 is no better than random.</p></div>`;
  }
  html += `<h2>How the rating works</h2><div class="panel"><p>Each team has one number: the points it adds to its alliance in an average match. Before a match, the two partners' numbers are added up to predict each alliance's score. Afterwards, each team's number moves toward what actually happened. It moves a lot for new teams and less as a team plays more, and one freak result can only move it so far.</p>
    <p>Skills runs are solo, so they show what a robot can do on its own. A team's published skills scores set its starting rating and pull its rating toward them at the start of each new event. That matters most early in the season, when teams have played few matches.</p>
    <p>Model settings: ${esc(META.model.source)}.</p></div>`;
  app.innerHTML = html;
}

boot();
