"""Data for the hub tools beyond match prediction:

  qualify.json  which High School teams have earned a spot at Worlds or their
                region championship (States), from the official award records:
                the qualifications an award lists, or, at events whose records
                list none, the Excellence, Tournament Champions and Robot
                Skills Champion awards that qualify at almost every event
  skills.json   season skills standings (best single-event combined score)
                with each team's qualification status, so "the best teams that
                haven't qualified yet" is one filter away
  plan.json     every upcoming event of the season with its location, level,
                registered High School teams and their ratings, for the
                "where should we compete?" planner

All three are built only from published results; nothing here guesses spot
counts.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from typing import Callable

from .dataset import Season


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


WORLDS = "World Championship"
REGION = "Region championship (States)"

# Awards that qualify a team at almost every event when the organizer hasn't
# typed the qualification into the award record (most don't).
QUALIFYING_AWARDS = ("excellence award", "tournament champions", "robot skills champion")


def target_namer(season: Season) -> Callable[[str], str | None]:
    """Map an award's qualification to one of the two championships a High
    School team is chasing: Worlds or its region championship (States, or the
    equivalent: an Australian state championship, a national championship).
    A qualification is either a generic string ("Event Region Championship")
    or an event's code; anything else (JROTC, Middle School events) is None."""
    by_sku = {ev.sku: ev for ev in season.calendar.values() if ev.sku}
    by_sku.update({ev.sku: ev for ev in season.events.values() if ev.sku})

    def name(q: str) -> str | None:
        q = " ".join(q.split())
        low = q.lower()
        if low == "world championship":
            return WORLDS
        if low in ("event region championship", "national championship"):
            return REGION
        ev = by_sku.get(q)
        if ev is None or _middle_school(ev.name):
            return None
        lvl = (ev.level or "").lower()
        if lvl == "world":
            return WORLDS
        n = ev.name.lower()
        if lvl in ("regional", "national") or "state championship" in n or "national championship" in n:
            return REGION
        return None
    return name


def _middle_school(label: str) -> bool:
    low = label.lower()
    return "(ms)" in low or "middle school" in low


def _inferred_target(ev) -> str | None:
    """Where an event's top awards usually send a team when the record says nothing."""
    if ev is None or "scrimmage" in ev.name.lower():
        return None
    lvl = (ev.level or "").lower()
    if lvl in ("other", "spotlight", ""):
        return REGION
    if lvl in ("signature", "regional", "national"):
        return WORLDS
    return None


def qualifications(season: Season) -> dict[int, list[dict]]:
    """team id -> the championships it has earned a spot at (High School teams
    only). Each record says whether the award record lists the qualification
    ("listed") or it is the event's usual qualifying award ("listed": False)."""
    out: dict[int, list[dict]] = defaultdict(list)
    _target = target_namer(season)
    listed_events = {a.event_id for a in season.awards if a.qualifications}
    for a in sorted(season.awards, key=lambda a: season.events[a.event_id].start if a.event_id in season.events else 0):
        ev = season.events.get(a.event_id)
        if _middle_school(a.name):
            continue
        if a.qualifications:
            targets = {_target(q) for q in a.qualifications} - {None}
            listed = True
        elif a.event_id not in listed_events and a.name.lower().startswith(QUALIFYING_AWARDS):
            targets = {_inferred_target(ev)} - {None}
            listed = False
        else:
            continue
        for tid in a.team_ids:
            t = season.teams.get(tid)
            if not t or not t.is_hs:
                continue
            for label in sorted(targets):
                if any(r["target"] == label and r["event_id"] == a.event_id and r["award"] == a.name for r in out[tid]):
                    continue
                out[tid].append({"target": label, "award": a.name, "event_id": a.event_id, "listed": listed,
                                 "event": ev.name if ev else "", "date": _iso(ev.start) if ev else ""})
    return out


def best_skills(season: Season) -> dict[int, tuple[int, int, int, int]]:
    """team id -> (combined, programming, driver, event id) for its best single
    event, ties broken by the autonomous score as the official standings do."""
    best: dict[int, tuple[int, int, int, int]] = {}
    for s in season.skills:
        key = (s.combined, s.programming, s.driver, s.event_id)
        if s.team_id not in best or key[:3] > best[s.team_id][:3]:
            best[s.team_id] = key
    return best


def qualify_data(season: Season, now_ts: float) -> dict:
    quals = qualifications(season)
    counts: dict[str, int] = defaultdict(int)
    for recs in quals.values():
        for t in {r["target"] for r in recs}:
            counts[t] += 1
    targets = [t for t in (REGION, WORLDS) if t in counts] or [REGION, WORLDS]
    teams = {}
    for tid, recs in quals.items():
        tm = season.teams[tid]
        teams[str(tid)] = {"number": tm.number, "name": tm.name, "region": tm.region, "country": tm.country,
                           "quals": recs}
    awards_in = len({a.event_id for a in season.awards})
    return {"targets": [{"name": t, "teams": counts.get(t, 0)} for t in targets], "teams": teams,
            "events_with_awards": awards_in, "updated": _iso(now_ts)}


def skills_data(season: Season) -> list[dict]:
    quals = qualifications(season)
    rows = []
    for tid, (combined, prog, drv, eid) in best_skills(season).items():
        tm = season.teams.get(tid)
        if not tm or not tm.is_hs:
            continue
        ev = season.events.get(eid)
        rows.append({"id": tid, "number": tm.number, "name": tm.name, "region": tm.region, "country": tm.country,
                     "score": combined, "auto": prog, "driver": drv, "event_id": eid,
                     "event": ev.name if ev else "", "date": _iso(ev.start) if ev else "",
                     "qualified": sorted({q["target"] for q in quals.get(tid, [])})})
    rows.sort(key=lambda r: (-r["score"], -r["auto"], -r["driver"], r["number"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def plan_data(season: Season, rating: Callable[[int], float | None], now_ts: float) -> dict:
    """Upcoming events, each with what's known about its field. `rating(t)`
    is a team's current rating (None if it has no matches yet)."""
    today = now_ts - 86400   # keep events that started today
    events = []
    for eid, ev in season.calendar.items():
        if ev.end < today or ev.name.strip().upper().startswith(("CANCELED", "CANCELLED")):
            continue
        reg = season.event_teams.get(eid)
        rec = {"id": eid, "sku": ev.sku, "name": ev.name, "date": _iso(ev.start), "end": _iso(ev.end),
               "level": ev.level or "Other", "city": ev.city, "region": ev.region, "country": ev.country,
               "lat": _r(ev.lat, 3), "lon": _r(ev.lon, 3), "league": ev.end - ev.start > 2 * 86400}
        if reg is not None:
            hs = [t for t in reg if season.teams.get(t) and season.teams[t].is_hs]
            rated = sorted(((rating(t), t) for t in hs if rating(t) is not None), reverse=True)
            rec.update(hs=len(hs), teams=hs, ratings=[_r(r) for r, _ in rated],
                       median=_r(rated[len(rated) // 2][0]) if rated else None,
                       top8=_r(sum(r for r, _ in rated[:8]) / min(8, len(rated))) if rated else None)
        events.append(rec)
    events.sort(key=lambda e: (e["date"], e["name"]))
    # [lat, lon, 1 if the team is in the US (the planner shows miles there)]
    loc = {str(t.id): [_r(t.lat, 2), _r(t.lon, 2), int(t.country == "United States")] for t in season.teams.values()
           if t.is_hs and t.lat is not None and t.lon is not None}
    return {"events": events, "team_loc": loc, "updated": _iso(now_ts)}


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance (used by tests; the site does the same in JS)."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


__all__ = ["schedule_luck", "qualify_data", "skills_data", "plan_data", "qualifications", "best_skills", "km"]


def schedule_luck(groups: dict[int, list], rating: dict[int, float], scale: float) -> dict[int, dict]:
    """How much easier or harder each team's qualification schedule was, in wins.

    For every qualification match a team plays, take the chance that an
    *average* team (the division's mean pre-event rating) would win with this
    team's actual partner against its actual opponents. The sum is the wins an
    average team would expect from this schedule; subtracting the division's
    typical value per match leaves the schedule's effect alone, separate from
    how good the team itself is. Positive = an easier draw than average.

    `groups` maps division -> scheduled quals (anything with .red and .blue),
    `rating` holds pre-event ratings, `scale` converts a rating gap to a win
    chance (logistic), as the model does."""
    out: dict[int, dict] = {}
    for _, group in groups.items():
        teams = {t for x in group for t in x.red + x.blue}
        if len(teams) < 4 or not group:
            continue
        r = {t: rating.get(t, 0.0) for t in teams}
        mean = sum(r.values()) / len(r)
        exp: dict[int, float] = defaultdict(float)
        n: dict[int, int] = defaultdict(int)
        for x in group:
            for side, other in ((x.red, x.blue), (x.blue, x.red)):
                opp = sum(r[t] for t in other)
                for t in side:
                    partners = sum(r[p] for p in side if p != t)
                    gap = (mean + partners) - opp
                    if len(side) != len(other):          # 1-team alliances in tiny events
                        gap = mean + partners - opp * len(side) / max(1, len(other))
                    exp[t] += 1 / (1 + math.exp(-gap / scale))
                    n[t] += 1
        per_match = sum(exp.values()) / max(1, sum(n.values()))
        for t in exp:
            out[t] = {"luck": exp[t] - per_match * n[t], "n": n[t]}
    return out
