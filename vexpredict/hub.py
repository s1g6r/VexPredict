"""Data for the hub tools beyond match prediction:

  qualify.json  which High School teams have earned a spot at a championship,
                from the "qualifications" the official award records list
  skills.json   season skills standings (best single-event combined score)
                with each team's qualification status, so "the best teams that
                haven't qualified yet" is one filter away
  plan.json     every upcoming event of the season with its location, level,
                registered High School teams and their ratings, for the
                "where should we compete?" planner

All three are built only from published results; nothing here guesses spot
counts or qualification rules.
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


GENERIC = {"Event Region Championship": "Region championship (States)"}


def target_namer(season: Season) -> Callable[[str], str]:
    """An award's qualification is either a generic championship ("Event
    Region Championship", "World Championship") or a specific event's code
    (e.g. VE-V5-26-66512); show the event's name for the latter."""
    by_sku = {ev.sku: ev.name for ev in season.calendar.values() if ev.sku}

    def name(q: str) -> str:
        q = " ".join(q.split())
        return by_sku.get(q) or GENERIC.get(q, q)
    return name


def _middle_school(label: str) -> bool:
    low = label.lower()
    return "(ms)" in low or "middle school" in low


def qualifications(season: Season) -> dict[int, list[dict]]:
    """team id -> the qualifying awards it has won (High School teams only)."""
    out: dict[int, list[dict]] = defaultdict(list)
    _target_label = target_namer(season)
    for a in sorted(season.awards, key=lambda a: season.events[a.event_id].start if a.event_id in season.events else 0):
        if not a.qualifications:
            continue
        ev = season.events.get(a.event_id)
        for tid in a.team_ids:
            t = season.teams.get(tid)
            if not t or not t.is_hs:
                continue
            for q in a.qualifications:
                label = _target_label(q)
                if _middle_school(label):
                    continue   # blended events list the MS championship too; not a High School team's spot
                out[tid].append({"target": label, "award": a.name, "event_id": a.event_id,
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
    targets = sorted(counts, key=lambda t: (-counts[t], t))
    teams = {}
    for tid, recs in quals.items():
        tm = season.teams[tid]
        teams[str(tid)] = {"number": tm.number, "name": tm.name, "region": tm.region, "country": tm.country,
                           "quals": recs}
    awards_in = len({a.event_id for a in season.awards})
    return {"targets": [{"name": t, "teams": counts[t]} for t in targets], "teams": teams,
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
