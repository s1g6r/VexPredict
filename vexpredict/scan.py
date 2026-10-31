"""Data for VEX Scan (app.2360arachnid.com): one compact file with every High
School team's card and every event's team list, so the scanner can match a
plate against the event's teams and show a card with no further requests
(and keep working on bad venue wifi once cached).

    scan.json
      season, slug, updated
      k      win chance from ratings: P(red wins) = 1 / (1 + exp(-k * (sum of
             red ratings - sum of blue ratings))), fitted to the site's model
      med    median rating of rated High School teams (a stand-in "average team")
      t      teams, column arrays:
               id, num, name, loc ("City, Region"), r (rating, null if no matches),
               rk (world rank among rated HS teams, 0 if unrated), rec ("W-L-T"),
               sk ([combined, auto, driver] best single-event skills, or 0),
               q bits: 1 = qualified for States, 2 = Worlds; 4 = States pending,
                 8 = Worlds pending (the award qualifies only if the event gets
                 enough spots, and its VEX page hasn't posted them)
      e      events: id, name (shortened), date, end, place, t (team indices)
"""
from __future__ import annotations

import datetime as dt
import math
import random
import re
from typing import Callable

from .dataset import Season
from .hub import REGION, WORLDS, best_skills, qualifications, team_status


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


_NOISE = [r"Middle\s+(and|&)\s+High\s+School(\s+Teams)?", r"VEX\s*V5\s*Robotics\s*Competition", r"\bV5RC\b", r"\bVRC\b", r"Override", r"Push\s*Back",
          r"High\s*School\s*(Teams|Only|Division)?", r"\(HS\)", r"\bHS\b", r"™", r"®", r"\bTournament\b",
          r"\bpresented\s+by\b.*$", r"\b20\d\d(-\d\d)?\b", r"\bVEX\b", r"\bV5\b"]


def short_name(name: str) -> str:
    """'Lake Park High School VEX V5 Robotics Competition: Override High School
    Teams' -> 'Lake Park High School'. Falls back to the full name."""
    s = name
    for pat in _NOISE:
        s = re.sub(pat, " ", s, flags=re.I)
    s = re.sub(r"\s*[:|@\-–]\s*(?=[:|@\-–]|$)", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" :|@-–,")
    # "Lake Park High School : " leftovers, doubled separators
    s = re.sub(r"\s*([:|])\s*", r" \1 ", s)
    s = re.sub(r"(\s[:|]\s)+", " · ", s)
    s = re.sub(r"\s*·\s*,\s*", " · ", s)
    s = re.sub(r"\(\s*([A-Za-z]*)\s*[&/,]?\s*\)", lambda m: f"({m.group(1)})" if m.group(1) else "", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+,", ",", s).strip(" ·,")
    return s if len(s) >= 4 else name


def fit_k(predict: Callable[[tuple, tuple], float], ratings: dict[int, float], n: int = 3000, seed: int = 1) -> float:
    """Least-squares slope (through the origin) of logit(model probability)
    against the rating difference, over random 2-vs-2 alliances."""
    teams = sorted(ratings)
    if len(teams) < 4:
        return 0.05
    rng = random.Random(seed)
    sxy = sxx = 0.0
    for _ in range(n):
        a, b, c, d = rng.sample(teams, 4)
        p = min(max(predict((a, b), (c, d)), 1e-4), 1 - 1e-4)
        x = ratings[a] + ratings[b] - ratings[c] - ratings[d]
        y = math.log(p / (1 - p))
        sxy += x * y
        sxx += x * x
    return sxy / sxx if sxx else 0.05


def scan_data(season: Season, slug: str, ratings: dict[int, float], ranks: dict[int, int],
              records: dict[int, tuple[int, int, int]], k: float, now_ts: float) -> dict:
    hs = sorted((t for t in season.teams.values() if t.is_hs), key=lambda t: t.id)
    ix = {t.id: i for i, t in enumerate(hs)}
    quals = qualifications(season)
    skills = best_skills(season)
    cols: dict[str, list] = {c: [] for c in ("id", "num", "name", "loc", "r", "rk", "rec", "sk", "q")}
    for t in hs:
        r = ratings.get(t.id)
        rec = records.get(t.id)
        sk = skills.get(t.id)
        recs = quals.get(t.id, [])
        st = {g: team_status(recs, g) for g in (REGION, WORLDS)}
        cols["id"].append(t.id)
        cols["num"].append(t.number)
        cols["name"].append(t.name or "")
        cols["loc"].append(", ".join(x for x in (t.city, t.region or t.country) if x))
        cols["r"].append(None if r is None else round(r, 1))
        cols["rk"].append(ranks.get(t.id, 0))
        cols["rec"].append("-".join(map(str, rec)) if rec and sum(rec) else "")
        cols["sk"].append(list(sk[:3]) if sk else 0)
        cols["q"].append((1 if st[REGION] in ("listed", "expected") else 4 if st[REGION] == "possible" else 0)
                         | (2 if st[WORLDS] in ("listed", "expected") else 8 if st[WORLDS] == "possible" else 0))

    teams_at: dict[int, set[int]] = {eid: set(ts) for eid, ts in season.event_teams.items()}
    for m in season.matches:
        teams_at.setdefault(m.event_id, set()).update(m.teams)
    evs = {**season.calendar, **season.events}
    events = []
    for eid, ts in teams_at.items():
        ev = evs.get(eid)
        if ev is None or ev.name.strip().upper().startswith(("CANCELED", "CANCELLED")):
            continue
        members = sorted(ix[t] for t in ts if t in ix)
        if len(members) < 2:
            continue
        events.append({"id": eid, "name": short_name(ev.name), "date": _iso(ev.start), "end": _iso(ev.end),
                       "place": ", ".join(x for x in (ev.city, ev.region or ev.country) if x), "t": members})
    events.sort(key=lambda e: (e["date"], e["name"]))
    rated = sorted(v for t, v in ratings.items() if t in ix)
    return {"season": season.name, "slug": slug, "updated": _iso(now_ts), "k": round(k, 5),
            "med": round(rated[len(rated) // 2], 1) if rated else 0.0, "t": cols, "e": events}
