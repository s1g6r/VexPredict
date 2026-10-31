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
const f2 = x => (Math.abs(x) < 0.005 ? 0 : x).toFixed(2);
const rnd = x => (x == null ? "–" : Math.round(x));
const num = id => NUMBERS[id] || id;
const teamLink = (id, extra = "") => `<a href="#/team/${id}" class="${myTeam() === id ? "me" : ""}" ${extra}>${esc(num(id))}</a>`;
function statusPill(s, league = false) {
  if (league && s === "live") return `<span class="pill">League, in progress</span>`;
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
  const parts = location.hash.split("?")[0].replace(/^#\/?/, "").split("/").filter(Boolean);
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
    else if (page === "qualify") await qualifyPage();
    else if (page === "skills") await skillsPage();
    else if (page === "plan") await planPage();
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
  const liveAll = META.events.filter(e => e.status === "live");
  const live = liveAll.filter(e => !e.league), leagues = liveAll.length - live.length;
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = META.events.filter(e => e.status === "upcoming" && e.date >= today).reverse().slice(0, 5);
  const [boardAll, q, sk, plan] = await Promise.all([get(`${SEASON}/leaderboard.json`),
    get(`${SEASON}/qualify.json`).catch(() => null), get(`${SEASON}/skills.json`).catch(() => null),
    get(`${SEASON}/plan.json`).catch(() => null)]);
  const board = boardAll.slice(0, 10);
  const soon = plan ? plan.events.filter(e => { const d = Date.parse(e.date) - Date.now(); return !e.league && d > -864e5 && d < 30 * 864e5; }).length : 0;
  const qTeams = q ? Object.keys(q.teams).length : 0;
  const tools = [
    ["#/events", "Predict", "Win odds for every match, ranking forecasts, match briefs and a live pick list.", `${META.events.filter(e => e.status === "live").length} events live now`],
    ["#/qualify", "Qualify", "Who has earned a spot at States or Worlds, and who's next in line on skills.", q ? (qTeams ? `${qTeams} teams qualified so far` : "Fills in as events post awards") : ""],
    ["#/skills", "Skills", "Season skills standings by region, with a filter for teams still without a spot.", sk && sk.length ? `Top score: ${sk[0].score} (${esc(sk[0].number)})` : ""],
    ["#/plan", "Plan", "Upcoming events near you, how strong each field is, and where you'd rank.", plan ? `${soon} events in the next 30 days` : ""],
  ].filter(t => t[3] !== "" || t[0] === "#/events");
  let next = "";
  const me = myTeam();
  if (me) {
    for (const e of liveAll) {
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
    <h1>Everything for your VEX season</h1>
    <p class="lede">Free tools for VEX V5RC High School: match predictions with published accuracy, qualification tracking, skills standings and an event planner. No accounts, no logins.</p>
    <div class="tools">${tools.map(([href, name, blurb, stat]) => `<a class="tool" href="${href}"><h2>${name}</h2><p>${blurb}</p>${stat ? `<span class="stat-line">${stat}</span>` : ""}</a>`).join("")}</div>
    ${next}
    ${live.length ? `<h2>Live now</h2><ul class="list panel">${live.map(evItem).join("")}</ul>` : ""}
    ${leagues ? `<p><a href="#/events?s=league">${leagues} league${leagues === 1 ? "" : "s"} in progress</a> (leagues play over several weeks)</p>` : ""}
    ${upcoming.length ? `<h2>Coming up</h2><ul class="list panel">${upcoming.map(evItem).join("")}</ul>` : ""}
    <h2>Top rated teams</h2>
    <div class="panel tablewrap">${boardTable(board)}<p><a href="#/leaderboard">See all ${META.teams_rated} rated teams</a></p></div>
    ${me ? "" : `<p class="callout">Open your team's page and choose "This is my team" to see your next match here.</p>`}`;
}
function evItem(e) {
  return `<li><a href="#/event/${e.id}">${esc(e.name)}</a><span class="row"><span class="muted">${e.date}</span>${statusPill(e.status, e.league)}</span></li>`;
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
      <select id="evs" aria-label="Status"><option value="">All events</option><option value="live">Live now</option><option value="league">Leagues in progress</option><option value="upcoming">Upcoming</option><option value="done">Finished</option></select>
    </div><ul class="list panel" id="evlist"></ul>`;
  const draw = () => {
    const q = $("#evq").value.toLowerCase(), s = $("#evs").value;
    const rows = META.events.filter(e => e.status !== "skills-only" && e.status !== "no-results")
      .filter(e => (!s || (s === "league" ? e.status === "live" && e.league : s === "live" ? e.status === "live" && !e.league : e.status === s)) && (!q || e.name.toLowerCase().includes(q) || e.sku.toLowerCase().includes(q)));
    $("#evlist").innerHTML = rows.slice(0, 300).map(evItem).join("") || `<li class="empty">No events match. Clear the filter to see all.</li>`;
  };
  const want = new URLSearchParams(location.hash.split("?")[1] || "").get("s");
  if (want) $("#evs").value = want;
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
    <p class="lede">${live && ev.matches.length ? "The rest of qualifications, simulated" : "Qualifications simulated before the first match"} 1,500 times with each team's rating, the schedule${!ev.matches.length && !ev.pending.length ? " (random schedules until the real one is out)" : ""}, and V5RC ranking rules: win points, autonomous points, then strength of schedule. Top ${sim.captains} become alliance captains.</p>
    ${hits}
    <div class="panel tablewrap"><table><thead><tr><th>Team</th>${ev.matches.length ? `<th class="n">${done ? "Final" : "Now"}</th><th class="n hide-m">Record</th>` : ""}
      <th class="n hide-m">Rating</th><th class="n">Expected</th><th>Captain odds</th><th class="n hide-m">Rank 1</th></tr></thead><tbody>
      ${rows.map(r => `<tr class="${myTeam() === r.id ? "mine" : ""}"><td class="t">${teamLink(r.id)}</td>
        ${ev.matches.length ? `<td class="n">${r.t.rank ?? "–"}</td><td class="n hide-m">${r.t.record ?? "–"}</td>` : ""}
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
  const [t, q, sk] = await Promise.all([get(`${SEASON}/teams/${id}.json`),
    get(`${SEASON}/qualify.json`).catch(() => null), get(`${SEASON}/skills.json`).catch(() => null)]);
  setTitle(t.number);
  const quals = q?.teams[id]?.quals || [];
  const skRow = sk?.find(x => x.id === id);
  const skRegion = skRow ? sk.filter(x => regionOf(x) === regionOf(skRow)).findIndex(x => x.id === id) + 1 : 0;
  const season = `${quals.length ? `<p class="callout good"><b>Qualified:</b> ${quals.map(z => `${esc(z.target)} (${esc(z.award)} at <a href="#/event/${z.event_id}">${esc(z.event)}</a>)`).join("; ")}</p>` : ""}
    ${skRow ? `<p class="muted">Skills: <b>${skRow.score}</b> (auto ${skRow.auto}, driver ${skRow.driver}) at <a href="#/event/${skRow.event_id}">${esc(skRow.event)}</a>. #${skRow.rank} in the world, #${skRegion} in ${esc(regionOf(skRow))}. <a href="#/skills">Skills standings</a></p>` : ""}`;
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
    ${season}
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
      ${c?.divisions ? `<tr><td>Before the first match</td><td class="n">${f2(c.spearman_sim)}</td><td class="n">${f2(c.spearman_standings)}</td></tr>` : ""}
      ${h?.divisions ? `<tr><td>Halfway through quals</td><td class="n">${f2(h.spearman_sim)}</td><td class="n">${f2(h.spearman_standings)}</td></tr>` : ""}
      </tbody></table><p class="muted">Rank correlation between predicted and actual final rankings: 1 is a perfect order, 0 is no better than random.</p></div>`;
  }
  html += `<h2>How the rating works</h2><div class="panel"><p>Each team has one number: the points it adds to its alliance in an average match. Before a match, the two partners' numbers are added up to predict each alliance's score. Afterwards, each team's number moves toward what actually happened. It moves a lot for new teams and less as a team plays more, and one freak result can only move it so far.</p>
    <p>Skills runs are solo, so they show what a robot can do on its own. A team's published skills scores set its starting rating and pull its rating toward them at the start of each new event. That matters most early in the season, when teams have played few matches.</p>
    <p>How much a match moves a rating depends on the time of season. Early on, alliances mostly score on their own, so a team is judged by its alliance's score. Once fields get strong, scoring is contested and defense matters, so the winning margin says more. Several versions of the rating run side by side, from "own score" to "margin", and each prediction leans on whichever has been predicting recent matches best. That uses only matches already played.${META.model.weights_now ? (() => {
      const lean = Object.entries(META.model.weights_now).reduce((a, [k, w]) => a + (+k) * w, 0);
      return ` Right now it leans ${pct(lean)} of the way from own score to margin.`;
    })() : ""}</p>
    <p>Model settings: ${esc(META.model.source)}.</p></div>`;
  app.innerHTML = html;
}

// ---------- hub: shared helpers ----------
const regionOf = t => t.region || t.country || "";
function regionOptions(rows, selected) {
  const rs = [...new Set(rows.map(regionOf).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  return `<option value="">All regions</option>${rs.map(r => `<option ${r === selected ? "selected" : ""}>${esc(r)}</option>`).join("")}`;
}
async function myRegion() {
  const me = myTeam();
  if (!me) return "";
  const sk = await get(`${SEASON}/skills.json`).catch(() => []);
  const row = sk.find(r => r.id === me);
  if (row) return regionOf(row);
  const board = await get(`${SEASON}/leaderboard.json`).catch(() => []);
  const b = board.find(r => r.id === me);
  return b ? regionOf(b) : "";
}

// ---------- qualification tracker ----------
async function qualifyPage() {
  setTitle("Qualification");
  const [q, sk] = await Promise.all([get(`${SEASON}/qualify.json`), get(`${SEASON}/skills.json`)]);
  const me = myTeam();
  const state = { target: store.get("q:target", q.targets[0]?.name || ""), region: store.get("q:region", null) ?? await myRegion() };
  const rowsAll = Object.entries(q.teams).map(([id, t]) => ({ id: +id, ...t }));
  for (const r of rowsAll) NUMBERS[r.id] = r.number;
  for (const r of sk) NUMBERS[r.id] = r.number;
  const intro = `<h1>Who has qualified?</h1>
    <p class="lede">Teams that have won an award that qualifies for a championship, straight from the official award results, plus the best teams in each region still without a spot.</p>`;
  if (!q.targets.length) {
    app.innerHTML = `${intro}<p class="callout">No qualifying awards have been recorded yet this season${q.events_with_awards ? ` (${q.events_with_awards} events have posted awards so far)` : ""}. This page fills in as events post their awards.</p>`;
    return;
  }
  const draw = () => {
    const t = state.target, r = state.region;
    const inR = x => !r || regionOf(x) === r;
    const qualified = rowsAll.filter(x => inR(x) && x.quals.some(z => z.target === t))
      .map(x => ({ ...x, mine: x.quals.filter(z => z.target === t) }))
      .sort((a, b) => a.mine[0].date.localeCompare(b.mine[0].date) || a.number.localeCompare(b.number));
    const doubles = qualified.filter(x => new Set(x.mine.map(z => `${z.event_id}:${z.award}`)).size > 1);
    const qset = new Set(rowsAll.filter(x => x.quals.some(z => z.target === t)).map(x => x.id));
    const next = sk.filter(x => inR(x) && !qset.has(x.id));
    const mine = me ? (() => {
      const meQ = rowsAll.find(x => x.id === me);
      const hit = meQ?.quals.filter(z => z.target === t) || [];
      if (hit.length) return `<p class="callout good"><b>${esc(num(me))} has qualified</b> for ${esc(t)}: ${hit.map(z => `${esc(z.award)} at <a href="#/event/${z.event_id}">${esc(z.event)}</a>`).join("; ")}.</p>`;
      const meSk = sk.find(x => x.id === me);
      if (!meSk) return `<p class="callout">${esc(num(me))} hasn't qualified for ${esc(t)} and has no skills score posted yet.</p>`;
      const pos = sk.filter(x => regionOf(x) === regionOf(meSk) && !qset.has(x.id)).findIndex(x => x.id === me) + 1;
      return `<p class="callout">${esc(num(me))} hasn't qualified for ${esc(t)} yet. On skills (${meSk.score}) it is <b>#${pos}</b> among ${esc(regionOf(meSk))} teams without a spot.</p>`;
    })() : `<p class="muted">Open your team's page and choose "This is my team" to see your own status here.</p>`;
    $("#qbody").innerHTML = `${mine}
      <div class="stats">
        <div class="stat"><b>${qualified.length}</b><span>${r ? esc(r) + " teams" : "teams"} qualified for ${esc(t)}</span></div>
        <div class="stat"><b>${doubles.length}</b><span>with more than one qualifying award (their extra spots pass down)</span></div>
      </div>
      <h2>Qualified</h2>
      ${qualified.length ? `<div class="panel tablewrap"><table><thead><tr><th>Team</th><th class="hide-m">Region</th><th>How</th><th class="n">Date</th></tr></thead><tbody>
        ${qualified.map(x => `<tr class="${me === x.id ? "mine" : ""}"><td class="t">${teamLink(x.id)}<span class="subnote">${esc(x.name || "")}</span></td><td class="hide-m">${esc(regionOf(x))}</td>
          <td>${x.mine.map(z => `${esc(z.award)} · <a href="#/event/${z.event_id}">${esc(z.event)}</a>`).join("<br>")}</td><td class="n">${x.mine[0].date.slice(5)}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="empty">Nobody${r ? " in " + esc(r) : ""} has qualified for ${esc(t)} yet.</p>`}
      <h2>Best skills without a spot</h2>
      <p class="muted">${r ? esc(r) + " teams" : "Teams"} that haven't qualified for ${esc(t)}, by their best skills score. When a qualified team wins another qualifying award, or spots are left over, they have usually gone to the next teams on this list.</p>
      ${next.length ? `<div class="panel tablewrap"><table><thead><tr><th class="n">#</th><th>Team</th><th class="n">Skills</th><th class="n">Auto</th><th class="n">Driver</th><th class="n hide-m">World</th></tr></thead><tbody>
        ${next.slice(0, 25).map((x, i) => `<tr class="${me === x.id ? "mine" : ""}"><td class="n">${i + 1}</td><td class="t">${teamLink(x.id)}<span class="subnote">${esc(regionOf(x))}</span></td>
          <td class="n"><b>${x.score}</b></td><td class="n">${x.auto}</td><td class="n">${x.driver}</td><td class="n hide-m">#${x.rank}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="empty">No skills scores posted${r ? " in " + esc(r) : ""} yet.</p>`}
      <p class="muted">Spots come from the qualifications VEX lists on each award. VEX hasn't published how many spots each region gets this season, so this page doesn't guess at cut-offs. Updated ${esc(q.updated)} from ${q.events_with_awards} events with posted awards.</p>`;
  };
  app.innerHTML = `${intro}
    <div class="row" style="margin:14px 0">
      <label class="sr" for="qt">Championship</label><select id="qt">${q.targets.map(x => `<option value="${esc(x.name)}" ${x.name === state.target ? "selected" : ""}>${esc(x.name)} (${x.teams})</option>`).join("")}</select>
      <label class="sr" for="qr">Region</label><select id="qr">${regionOptions([...rowsAll, ...sk], state.region)}</select>
    </div><div id="qbody"></div>`;
  if (!q.targets.some(x => x.name === state.target)) state.target = q.targets[0].name;
  $("#qt").onchange = e => { state.target = e.target.value; store.set("q:target", state.target); draw(); };
  $("#qr").onchange = e => { state.region = e.target.value; store.set("q:region", state.region); draw(); };
  draw();
}

// ---------- skills standings ----------
async function skillsPage() {
  setTitle("Skills");
  const sk = await get(`${SEASON}/skills.json`);
  for (const r of sk) NUMBERS[r.id] = r.number;
  const me = myTeam();
  const state = { region: store.get("s:region", ""), open: store.get("s:open", false), q: "", shown: 100 };
  app.innerHTML = `<h1>Skills standings</h1>
    <p class="lede">Each High School team's best skills score this season: driving plus autonomous coding from the same event, ranked the way the official standings are (ties go to the higher autonomous score).</p>
    <div class="row" style="margin:14px 0">
      <input type="text" id="sq" placeholder="Filter by number or name" style="max-width:260px" aria-label="Filter teams">
      <label class="sr" for="sr">Region</label><select id="sr">${regionOptions(sk, state.region)}</select>
      <label class="row" style="gap:6px;font-weight:700"><input type="checkbox" id="so" ${state.open ? "checked" : ""}> Only teams without a qualifying spot</label>
    </div><div id="sbody"></div>`;
  const draw = () => {
    const rows = sk.filter(x => (!state.region || regionOf(x) === state.region) && (!state.open || !x.qualified.length));
    const ranked = rows.map((x, i) => ({ ...x, pos: i + 1 }));
    const q = state.q.toLowerCase();
    const shown = ranked.filter(x => !q || x.number.toLowerCase().includes(q) || (x.name || "").toLowerCase().includes(q));
    const meRow = me && ranked.find(x => x.id === me);
    $("#sbody").innerHTML = `${meRow ? `<p class="callout">${esc(num(me))}: <b>${meRow.score}</b> (auto ${meRow.auto}, driver ${meRow.driver}), <b>#${meRow.pos}</b> on this list and #${meRow.rank} in the world.</p>` : ""}
      ${shown.length ? `<div class="panel tablewrap"><table><thead><tr><th class="n">#</th><th>Team</th><th class="n">Score</th><th class="n">Auto</th><th class="n">Driver</th><th class="hide-m">Where</th><th class="n hide-m">World</th></tr></thead><tbody>
        ${shown.slice(0, state.shown).map(x => `<tr class="${me === x.id ? "mine" : ""}"><td class="n">${x.pos}</td>
          <td class="t">${teamLink(x.id)}${x.qualified.length ? ` <span class="pill good" title="${esc(x.qualified.join(", "))}">Qualified</span>` : ""}<span class="subnote">${esc(regionOf(x))}</span></td>
          <td class="n"><b>${x.score}</b></td><td class="n">${x.auto}</td><td class="n">${x.driver}</td>
          <td class="hide-m"><a href="#/event/${x.event_id}">${esc(x.event)}</a></td><td class="n hide-m">#${x.rank}</td></tr>`).join("")}
      </tbody></table></div>${shown.length > state.shown ? `<p><button id="smore">Show 100 more</button></p>` : ""}`
      : `<p class="empty">No teams match. Clear the filters to see everyone.</p>`}`;
    const more = $("#smore"); if (more) more.onclick = () => { state.shown += 100; draw(); };
  };
  $("#sq").oninput = e => { state.q = e.target.value; state.shown = 100; draw(); };
  $("#sr").onchange = e => { state.region = e.target.value; store.set("s:region", state.region); state.shown = 100; draw(); };
  $("#so").onchange = e => { state.open = e.target.checked; store.set("s:open", state.open); state.shown = 100; draw(); };
  draw();
}

// ---------- event planner ----------
function distance(a, b) {
  const r = x => x * Math.PI / 180;
  const h = Math.sin(r(b[0] - a[0]) / 2) ** 2 + Math.cos(r(a[0])) * Math.cos(r(b[0])) * Math.sin(r(b[1] - a[1]) / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(h));
}
async function planPage() {
  setTitle("Plan your season");
  const [plan, board] = await Promise.all([get(`${SEASON}/plan.json`), get(`${SEASON}/leaderboard.json`).catch(() => [])]);
  const ratingOf = Object.fromEntries(board.map(b => [b.id, b.rating]));
  const hasPage = new Set(META.events.map(e => e.id));
  const official = sku => `https://events.vex.com/robot-competitions/vex-robotics-competition/${encodeURIComponent(sku)}.html`;
  const byNumber = Object.fromEntries(Object.entries(NUMBERS).map(([id, n]) => [String(n).toUpperCase(), +id]));
  const state = { team: myTeam(), radius: store.get("p:radius", 500), days: store.get("p:days", 90), level: "", leagues: false };
  app.innerHTML = `<h1>Where should we compete?</h1>
    <p class="lede">Upcoming events near your team, how strong each field is so far, and where your team would sit in it. Fields fill in as teams register, so check back.</p>
    <div class="panel"><div class="row">
      <label for="pt">Team</label><input id="pt" type="text" style="max-width:110px" value="${esc(state.team ? num(state.team) : "")}" placeholder="2360A" autocomplete="off">
      <label class="sr" for="pd">Distance</label><select id="pd">${[[100, "Within 100"], [250, "Within 250"], [500, "Within 500"], [1000, "Within 1,000"], [0, "Any distance"]].map(([v, l]) => `<option value="${v}" ${v === state.radius ? "selected" : ""}>${l}</option>`).join("")}</select>
      <label class="sr" for="pw">When</label><select id="pw">${[[30, "Next 30 days"], [90, "Next 90 days"], [0, "Rest of the season"]].map(([v, l]) => `<option value="${v}" ${v === state.days ? "selected" : ""}>${l}</option>`).join("")}</select>
      <label class="sr" for="pl">Level</label><select id="pl"><option value="">All levels</option>${[...new Set(plan.events.map(e => e.level))].sort().map(l => `<option>${esc(l)}</option>`).join("")}</select>
      <label class="row" style="gap:6px;font-weight:700"><input type="checkbox" id="pg"> Include leagues</label>
    </div><p class="muted" id="pnote" style="margin-bottom:0"></p></div>
    <div id="pbody"></div>`;
  const draw = () => {
    const loc = state.team ? plan.team_loc[state.team] : null;
    const miles = loc ? loc[2] === 1 : true;
    const unit = miles ? "mi" : "km";
    const conv = d => (miles ? d * 0.621371 : d);
    const myR = state.team ? ratingOf[state.team] : null;
    for (const o of $("#pd").options) if (+o.value) o.textContent = `Within ${(+o.value).toLocaleString()} ${unit}`;
    $("#pnote").textContent = !state.team ? "Enter a team number to see distances and where that team would rank in each field."
      : !loc ? `No location on file for ${num(state.team)}, so events aren't filtered by distance.`
      : myR == null ? `${num(state.team)} has no rating yet (no matches this season), so its place in each field isn't shown.`
      : `${num(state.team)} is rated ${Math.round(myR)}. Field strength is the median and top-8 average rating of registered High School teams.`;
    const now = Date.now(), horizon = state.days ? now + state.days * 864e5 : Infinity;
    const rows = plan.events.map(e => ({ ...e, km: loc && e.lat != null ? distance(loc, [e.lat, e.lon]) : null }))
      .filter(e => (state.leagues || !e.league) && (!state.level || e.level === state.level))
      .filter(e => Date.parse(e.date) <= horizon)
      .filter(e => !loc || !state.radius || (e.km != null && conv(e.km) <= state.radius));
    const place = e => {
      if (myR == null || !e.ratings?.length) return "–";
      const better = e.ratings.filter(r => r > myR + 0.05).length;
      const registered = e.teams?.includes(state.team);
      return `#${better + 1} of ${e.ratings.length + (registered ? 0 : 1)}`;
    };
    $("#pbody").innerHTML = rows.length ? `<p class="muted">${rows.length} event${rows.length === 1 ? "" : "s"}.</p><div class="panel tablewrap"><table><thead><tr>
        <th class="n hide-m">Date</th><th>Event</th>${loc ? `<th class="n">Away</th>` : ""}<th class="n">Teams</th><th class="n hide-m">Median</th><th class="n hide-m">Top 8</th><th class="n">${state.team ? "You" : "Place"}</th></tr></thead><tbody>
      ${rows.map(e => `<tr class="${e.teams?.includes(state.team) ? "mine" : ""}"><td class="n hide-m">${e.date.slice(5)}</td>
        <td>${hasPage.has(e.id) ? `<a href="#/event/${e.id}">${esc(e.name)}</a>` : `<a href="${official(e.sku)}" target="_blank" rel="noopener">${esc(e.name)}</a>`}${e.level !== "Other" ? ` <span class="pill">${esc(e.level)}</span>` : ""}${e.teams?.includes(state.team) ? ` <span class="pill good">Registered</span>` : ""}
          <span class="subnote">${esc([new Date(e.date + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" }), e.city, e.region, e.country !== "United States" ? e.country : ""].filter(Boolean).join(" · "))}</span></td>
        ${loc ? `<td class="n" style="white-space:nowrap">${e.km == null ? "–" : `${Math.round(conv(e.km)).toLocaleString()} ${unit}`}</td>` : ""}
        <td class="n">${e.hs ?? "–"}</td><td class="n hide-m">${rnd(e.median)}</td><td class="n hide-m">${rnd(e.top8)}</td><td class="n" style="white-space:nowrap">${place(e)}</td></tr>`).join("")}
      </tbody></table></div>
      <p class="muted">"You" ranks your team by rating among the High School teams registered so far, counting your team in. Only teams with matches this season have ratings. Events with registered High School teams open their forecast page here; the rest link to the official event page.</p>`
      : `<p class="empty">No events match. Try a larger distance, a longer time window, or include leagues.</p>`;
  };
  $("#pt").onchange = e => {
    const id = byNumber[e.target.value.trim().toUpperCase()];
    state.team = id || null;
    if (!id && e.target.value.trim()) $("#pnote").textContent = `No team ${e.target.value.trim()} found this season.`;
    draw();
  };
  $("#pd").onchange = e => { state.radius = +e.target.value; store.set("p:radius", state.radius); draw(); };
  $("#pw").onchange = e => { state.days = +e.target.value; store.set("p:days", state.days); draw(); };
  $("#pl").onchange = e => { state.level = e.target.value; draw(); };
  $("#pg").onchange = e => { state.leagues = e.target.checked; draw(); };
  draw();
}

boot();
