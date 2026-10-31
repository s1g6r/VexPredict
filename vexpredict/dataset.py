"""Turn raw per-event API files into one clean, time-ordered season dataset."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import HIGH_SCHOOL, season_dir

PRACTICE, QUAL, QF, SF, FINAL, R16 = 1, 2, 3, 4, 5, 6
ROUND_ORDER = {QUAL: 0, R16: 1, QF: 2, SF: 3, FINAL: 4}  # practice is dropped
DAY = 86400.0


@dataclass(frozen=True)
class Match:
    idx: int                 # position in the global time-ordered stream
    event_id: int
    division_id: int
    round: int
    instance: int
    matchnum: int
    ts: float                # seconds since epoch, used only for ordering
    red: tuple[int, ...]
    blue: tuple[int, ...]
    red_score: int
    blue_score: int
    dated: bool = True       # False: no match times and a multi-day event (e.g. a league), so the
                             # true order is unknown; such matches update ratings but aren't scored

    @property
    def is_qual(self) -> bool:
        return self.round == QUAL

    @property
    def is_elim(self) -> bool:
        return self.round != QUAL

    @property
    def teams(self) -> tuple[int, ...]:
        return self.red + self.blue

    @property
    def outcome(self) -> float:
        """1 if red won, 0 if blue won, 0.5 for a tie."""
        if self.red_score > self.blue_score:
            return 1.0
        if self.red_score < self.blue_score:
            return 0.0
        return 0.5


@dataclass(frozen=True)
class Event:
    id: int
    sku: str
    name: str
    start: float
    end: float
    level: str

    @property
    def is_worlds(self) -> bool:
        if self.level:  # the API's own label; names also match Worlds scrimmages
            return self.level.lower() == "world"
        return "world championship" in self.name.lower() and "scrimmage" not in self.name.lower()


@dataclass(frozen=True)
class SkillsResult:
    team_id: int
    event_id: int
    available_ts: float      # results usable for predictions after this time
    driver: int
    programming: int

    @property
    def combined(self) -> int:
        return self.driver + self.programming


@dataclass(frozen=True)
class Ranking:
    team_id: int
    division_id: int
    rank: int
    wins: int
    losses: int
    ties: int
    wp: int
    ap: int
    sp: int

    @property
    def played(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def awp(self) -> int:
        """Autonomous win points = WP beyond what wins and ties explain."""
        return max(0, self.wp - 2 * self.wins - self.ties)


@dataclass(frozen=True)
class Pending:
    """A scheduled qualification match with no result yet."""
    event_id: int
    division_id: int
    matchnum: int
    red: tuple[int, ...]
    blue: tuple[int, ...]

    @property
    def teams(self) -> tuple[int, ...]:
        return self.red + self.blue


@dataclass
class Team:
    id: int
    number: str
    grade: str = ""
    country: str = ""
    name: str = ""
    region: str = ""

    @property
    def is_hs(self) -> bool:
        return self.grade == HIGH_SCHOOL


@dataclass
class Season:
    name: str
    events: dict[int, Event] = field(default_factory=dict)
    teams: dict[int, Team] = field(default_factory=dict)
    matches: list[Match] = field(default_factory=list)
    skills: list[SkillsResult] = field(default_factory=list)
    rankings: dict[int, dict[int, Ranking]] = field(default_factory=dict)   # event -> team -> final/current
    pending: dict[int, list[Pending]] = field(default_factory=dict)         # event -> unplayed quals
    event_teams: dict[int, list[int]] = field(default_factory=dict)        # event -> registered teams
    synthetic: bool = False

    def event_matches(self, event_id: int) -> list[Match]:
        return [m for m in self.matches if m.event_id == event_id]

    def is_hs_match(self, m: Match) -> bool:
        return all(self.teams.get(t, Team(t, "?")).is_hs for t in m.teams)

    def team_label(self, tid: int) -> str:
        t = self.teams.get(tid)
        return t.number if t else str(tid)


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.timestamp()


def _alliance(m: dict, color: str) -> tuple[tuple[int, ...], int] | None:
    for a in m.get("alliances") or []:
        if a.get("color") == color:
            ids = tuple(t["team"]["id"] for t in a.get("teams") or []
                        if t.get("team") and not t.get("sitting"))
            return ids, int(a.get("score") or 0)
    return None


def _played(m: dict, red, blue) -> bool:
    """The API's `scored` flag is false on every match, played or not, so it
    can't be used. A match has been played if either alliance scored or it
    has a start time; an unplayed match is 0-0 with no start time."""
    return bool(red[1] or blue[1] or m.get("started"))


def _pending(raw: list[dict], event_id: int) -> list[Pending]:
    out = []
    for m in raw:
        if m.get("round") != QUAL:
            continue
        red, blue = _alliance(m, "red"), _alliance(m, "blue")
        if red and blue and red[0] and blue[0] and not _played(m, red, blue):
            out.append(Pending(event_id, (m.get("division") or {}).get("id", 0), m.get("matchnum") or 0,
                               red[0], blue[0]))
    out.sort(key=lambda p: (p.division_id, p.matchnum))
    return out


LONG_EVENT = 2 * DAY


def _event_matches(raw: list[dict], event_start: float, event_end: float | None = None) -> list[dict]:
    rows = []
    for m in raw:
        rnd = m.get("round")
        if rnd not in ROUND_ORDER:
            continue
        red, blue = _alliance(m, "red"), _alliance(m, "blue")
        if not red or not blue or not red[0] or not blue[0]:
            continue
        if not _played(m, red, blue):
            continue
        rows.append({
            "division_id": (m.get("division") or {}).get("id", 0),
            "round": rnd, "instance": m.get("instance") or 0, "matchnum": m.get("matchnum") or 0,
            "time": _ts(m.get("started")) or _ts(m.get("scheduled")),
            "red": red[0], "blue": blue[0], "red_score": red[1], "blue_score": blue[1],
        })
    # Use real start times when every match has one; otherwise the canonical
    # order (all quals, then R16 -> QF -> SF -> F). Timestamps are then forced
    # to be monotone along that order so ordering is never ambiguous.
    canon = lambda r: (ROUND_ORDER[r["round"]], r["division_id"], r["instance"], r["matchnum"])  # noqa: E731
    dated = True
    if rows and all(r["time"] is not None for r in rows):
        rows.sort(key=lambda r: (r["time"],) + canon(r))
    else:
        rows.sort(key=canon)
        # A league or other multi-week event without match times: we can't tell
        # when each match happened, so put them all at the end of the event
        # (never earlier than reality, so nothing leaks backwards in time) and
        # leave them out of the accuracy numbers.
        if event_end is not None and event_end - event_start > LONG_EVENT:
            event_start, dated = event_end, False
    prev = event_start
    for r in rows:
        t = r["time"] if r["time"] is not None and r["time"] >= prev else prev + 1.0
        r["time"] = prev = t
        r["dated"] = dated
    return rows


def load_season(slug: str, root: Path | None = None) -> Season:
    base = root or season_dir(slug)
    meta_path = base / "season.json"
    name = slug
    synthetic = False
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        name = meta["season"].get("name", slug)
        synthetic = bool(meta.get("synthetic"))
    season = Season(name=name, synthetic=synthetic)
    staged: list[tuple[float, int, dict]] = []
    files = sorted((base / "events").glob("*.json"))
    if not files:
        raise SystemExit(f"No event files in {base / 'events'}. Run `python3 -m vexpredict.fetch` first.")
    for f in files:
        rec = json.loads(f.read_text())
        e = rec["event"]
        start = _ts(e.get("start")) or 0.0
        end = _ts(e.get("end")) or start
        ev = Event(e["id"], e.get("sku", ""), e.get("name", ""), start, end, e.get("level") or "")
        season.events[ev.id] = ev
        for t in rec.get("teams") or []:
            loc = t.get("location") or {}
            team = season.teams.setdefault(t["id"], Team(t["id"], t.get("number", str(t["id"]))))
            team.grade = t.get("grade") or team.grade
            team.country = loc.get("country") or team.country
            team.region = loc.get("region") or team.region
            team.name = t.get("team_name") or team.name
            season.event_teams.setdefault(ev.id, []).append(t["id"])
        by_team: dict[int, dict[str, int]] = {}
        for s in rec.get("skills") or []:
            tid = (s.get("team") or {}).get("id")
            typ = s.get("type")
            if tid is None or typ not in ("driver", "programming"):
                continue
            d = by_team.setdefault(tid, {"driver": 0, "programming": 0})
            d[typ] = max(d[typ], int(s.get("score") or 0))
            season.teams.setdefault(tid, Team(tid, (s.get("team") or {}).get("name", str(tid))))
        avail = end + DAY
        for tid, d in by_team.items():
            season.skills.append(SkillsResult(tid, ev.id, avail, d["driver"], d["programming"]))
        ranks = {}
        for r in rec.get("rankings") or []:
            tid = (r.get("team") or {}).get("id")
            if tid is None:
                continue
            ranks[tid] = Ranking(tid, (r.get("division") or {}).get("id", 0), int(r.get("rank") or 0),
                                 int(r.get("wins") or 0), int(r.get("losses") or 0), int(r.get("ties") or 0),
                                 int(r.get("wp") or 0), int(r.get("ap") or 0), int(r.get("sp") or 0))
        if ranks:
            season.rankings[ev.id] = ranks
        pend = _pending(rec.get("matches") or [], ev.id)
        if pend:
            season.pending[ev.id] = pend
        for r in _event_matches(rec.get("matches") or [], start, end):
            for tid in r["red"] + r["blue"]:
                season.teams.setdefault(tid, Team(tid, str(tid)))
            staged.append((r["time"], ev.id, r))
    staged.sort(key=lambda x: (x[0], x[1]))
    for i, (t, eid, r) in enumerate(staged):
        season.matches.append(Match(i, eid, r["division_id"], r["round"], r["instance"], r["matchnum"],
                                    t, r["red"], r["blue"], r["red_score"], r["blue_score"], r["dated"]))
    season.skills.sort(key=lambda s: s.available_ts)
    return season
