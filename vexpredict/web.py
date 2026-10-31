"""The alliance web: every pair of teams that played on the same alliance,
for The Web (app.2360arachnid.com).

    web.json
      season, slug, updated
      t     teams, column arrays: num, name, reg (region or country), lat, lon,
            hs (1 = High School), r (current rating, 0 if none)
      e     events, column arrays: name, date, lat, lon
      p     partner pairs, flattened: [a, b, matches together, wins together,
            event of their first match together, ...], in the order the pairs
            first played together (so the app can spin the season in order)
      champ team indices of the World Champions alliance (empty until Worlds)

Indices are positions in the column arrays. Built only from published match
results.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable

from .dataset import FINAL, Season


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def world_champions(season: Season) -> list[int]:
    """The alliance that won the High School World Championship finals."""
    worlds = [e for e in season.events.values() if e.is_worlds and "middle" not in e.name.lower()]
    if not worlds:
        return []
    ev = max(worlds, key=lambda e: e.start)
    finals = [m for m in season.matches if m.event_id == ev.id and m.round == FINAL]
    if not finals:
        return []
    last_div = max(finals, key=lambda m: m.ts).division_id
    wins: dict[tuple[int, ...], int] = {}
    for m in finals:
        if m.division_id != last_div or m.red_score == m.blue_score:
            continue
        side = m.red if m.red_score > m.blue_score else m.blue
        wins[side] = wins.get(side, 0) + 1
    return list(max(wins, key=wins.get)) if wins else []


def web_data(season: Season, slug: str, rating: Callable[[int], float | None], now_ts: float) -> dict:
    pairs: dict[tuple[int, int], list] = {}
    for m in season.matches:              # time order, so dict order = first time together
        o = m.outcome
        for side, won in ((m.red, o == 1), (m.blue, o == 0)):
            if len(side) != 2:
                continue
            a, b = sorted(side)
            rec = pairs.get((a, b))
            if rec is None:
                pairs[(a, b)] = [1, int(won), m.event_id]
            else:
                rec[0] += 1
                rec[1] += int(won)
    team_ids = sorted({t for ab in pairs for t in ab})
    tix = {t: i for i, t in enumerate(team_ids)}
    event_ids = sorted({rec[2] for rec in pairs.values()}, key=lambda e: season.events[e].start)
    eix = {e: i for i, e in enumerate(event_ids)}

    cols: dict[str, list] = {k: [] for k in ("num", "name", "reg", "lat", "lon", "hs", "r")}
    for t in team_ids:
        tm = season.teams.get(t)
        r = rating(t)
        cols["num"].append(tm.number if tm else str(t))
        cols["name"].append(tm.name if tm else "")
        cols["reg"].append((tm.region or tm.country) if tm else "")
        cols["lat"].append(_r(tm.lat) if tm else None)
        cols["lon"].append(_r(tm.lon) if tm else None)
        cols["hs"].append(int(bool(tm and tm.is_hs)))
        cols["r"].append(round(r) if r is not None else 0)
    ev_cols: dict[str, list] = {k: [] for k in ("name", "date", "lat", "lon")}
    for e in event_ids:
        ev = season.events[e]
        ev_cols["name"].append(ev.name)
        ev_cols["date"].append(dt.datetime.fromtimestamp(ev.start, dt.timezone.utc).strftime("%Y-%m-%d"))
        ev_cols["lat"].append(_r(ev.lat))
        ev_cols["lon"].append(_r(ev.lon))
    flat: list[int] = []
    for (a, b), (n, w, e) in pairs.items():
        flat += [tix[a], tix[b], n, w, eix[e]]
    return {"season": season.name, "slug": slug,
            "updated": dt.datetime.fromtimestamp(now_ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "t": cols, "e": ev_cols, "p": flat,
            "champ": [tix[t] for t in world_champions(season) if t in tix]}
