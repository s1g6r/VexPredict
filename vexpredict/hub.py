"""Data for the hub tools beyond match prediction:

  qualify.json  which High School teams have earned a spot at Worlds or their
                region championship (States), from the official award records:
                the qualifications an award lists, or, at events whose records
                list none, the RECF qualifying rules (see qualifications())
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

# When an event's award records don't list qualifications (most don't), the
# RECF rules decide. Local events and Region Championships give spots in this
# order (V5RC spot allocation chart): Excellence 1, Tournament Champions 2,
# Design 1, Robot Skills Champion 1, then Finalists and the judged awards. The
# first three spots are the minimum allocation, so Excellence and Tournament
# Champions are "expected"; Design and Skills Champion need an allocation of 4+
# spots, which RECF sets by event size (for 2026-27, in January 2027), so they
# are "possible". Signature Events: exactly three Worlds spots, Excellence and
# Tournament Champions (2026-27 Signature Event guide), so those are expected.
EXPECTED_AWARDS = ("excellence award", "tournament champions")
POSSIBLE_AWARDS = ("design award", "robot skills champion")
RANK = {"listed": 0, "expected": 1, "possible": 2}
PASSED = "Skills spot (passed down)"


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


def _rules(ev) -> tuple[str, tuple[str, ...]] | None:
    """(championship, awards that can qualify) for an event whose records list nothing."""
    if ev is None or "scrimmage" in ev.name.lower():
        return None
    lvl = (ev.level or "").lower()
    if lvl in ("other", "spotlight", ""):
        return REGION, EXPECTED_AWARDS + POSSIBLE_AWARDS
    if lvl == "signature":
        return WORLDS, EXPECTED_AWARDS
    if lvl in ("regional", "national"):
        return WORLDS, EXPECTED_AWARDS + POSSIBLE_AWARDS
    return None


def _event_skills(season: Season) -> dict[int, list[int]]:
    """event -> High School teams by their skills score there (ties: autonomous, then driver)."""
    best: dict[tuple[int, int], tuple[int, int, int]] = {}
    for x in season.skills:
        k = (x.event_id, x.team_id)
        v = (x.combined, x.programming, x.driver)
        if v > best.get(k, (-1, -1, -1)):
            best[k] = v
    out: dict[int, list[tuple]] = defaultdict(list)
    for (eid, tid), v in best.items():
        t = season.teams.get(tid)
        if t and t.is_hs:
            out[eid].append((v, tid))
    return {eid: [tid for _, tid in sorted(rows, key=lambda r: (tuple(-x for x in r[0]), r[1]))] for eid, rows in out.items()}


def qualifications(season: Season) -> dict[int, list[dict]]:
    """team id -> the championships it has earned (or is in line for) a spot at,
    High School teams only, in event order. Each record has a status:

      listed    the award record lists the qualification
      expected  the RECF rules give this award a spot at every event of its
                kind (the event's records just don't say so)
      possible  the award qualifies only if the event is allocated enough spots

    Double qualifications follow the RECF rules: when a team wins a second
    qualifying award, or already holds a spot, its spot passes to the next
    High School team on that event's skills list that didn't win a qualifying
    award there and doesn't already hold a spot ("Skills spot (passed down)")."""
    out: dict[int, list[dict]] = defaultdict(list)
    _target = target_namer(season)
    skills_at = _event_skills(season)
    by_event: dict[int, list] = defaultdict(list)
    for a in season.awards:
        if not _middle_school(a.name):
            by_event[a.event_id].append(a)
    held: dict[str, set[int]] = {REGION: set(), WORLDS: set()}   # teams with a listed or expected spot
    order = sorted(by_event, key=lambda e: (season.events[e].start if e in season.events else 0, e))
    for eid in order:
        ev = season.events.get(eid)
        awards = by_event[eid]
        listed_here = any(a.qualifications for a in awards)
        rules = None if listed_here else _rules(ev)
        slots: dict[str, list[tuple[str, int, str]]] = defaultdict(list)   # target -> (award, team, status)
        for a in awards:
            low = a.name.lower()
            if a.qualifications:
                targets, status = {_target(q) for q in a.qualifications} - {None}, "listed"
            elif rules and low.startswith(rules[1]):
                targets, status = {rules[0]}, ("expected" if low.startswith(EXPECTED_AWARDS) else "possible")
            else:
                continue
            for tid in a.team_ids:
                t = season.teams.get(tid)
                if t and t.is_hs:
                    for tg in targets:
                        slots[tg].append((a.name, tid, status))
        for tg, sl in slots.items():
            sl.sort(key=lambda x: RANK[x[2]])
            winners = {tid for _, tid, _ in sl}
            given: set[int] = set()
            freed: list[str] = []
            for award, tid, status in sl:
                if tid in held[tg] or tid in given:
                    freed.append(status)      # a double qualification: this spot passes down
                else:
                    given.add(tid)
                    if status != "possible":
                        held[tg].add(tid)
                _add(out, tid, tg, award, status, ev, eid)
            queue = [t for t in skills_at.get(eid, []) if t not in winners and t not in held[tg]]
            for status, tid in zip(freed, queue):
                _add(out, tid, tg, PASSED, status, ev, eid)
                if status != "possible":
                    held[tg].add(tid)
    return out


def _add(out, tid, target, award, status, ev, eid) -> None:
    if any(r["target"] == target and r["event_id"] == eid and r["award"] == award for r in out[tid]):
        return
    out[tid].append({"target": target, "award": award, "event_id": eid, "status": status,
                     "listed": status == "listed", "event": ev.name if ev else "",
                     "date": _iso(ev.start) if ev else ""})


def team_status(recs: list[dict], target: str) -> str | None:
    """A team's best status for one championship, or None."""
    st = [r["status"] for r in recs if r["target"] == target]
    return min(st, key=RANK.get) if st else None


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
    pending: dict[str, int] = defaultdict(int)
    for recs in quals.values():
        for t in (REGION, WORLDS):
            st = team_status(recs, t)
            if st in ("listed", "expected"):
                counts[t] += 1
            elif st == "possible":
                pending[t] += 1
    targets = [REGION, WORLDS]
    teams = {}
    for tid, recs in quals.items():
        tm = season.teams[tid]
        teams[str(tid)] = {"number": tm.number, "name": tm.name, "region": tm.region, "country": tm.country,
                           "quals": recs}
    awards_in = len({a.event_id for a in season.awards})
    return {"targets": [{"name": t, "teams": counts.get(t, 0), "pending": pending.get(t, 0)} for t in targets],
            "teams": teams,
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
                     "qualified": [t for t in (REGION, WORLDS) if team_status(quals.get(tid, []), t) in ("listed", "expected")],
                     "pending": [t for t in (REGION, WORLDS) if team_status(quals.get(tid, []), t) == "possible"]})
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
