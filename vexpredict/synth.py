"""Synthetic V5RC season with known team strengths, written in the same raw
format the API pull produces. Used to test the whole pipeline end to end and to
check that the models recover strengths they should be able to recover."""
from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

DAY = 86400


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def generate(out: Path, n_teams: int = 360, n_events: int = 90, seed: int = 0,
             season_days: int = 160, missing_times: float = 0.2, n_skills_events: int = 60) -> dict:
    rng = random.Random(seed)
    t0 = dt.datetime(2025, 9, 1, tzinfo=dt.timezone.utc).timestamp()
    regions = 8
    teams = []
    for i in range(n_teams):
        teams.append({
            "id": 1000 + i, "number": f"{100 + i}{'ABCDE'[i % 5]}",
            "grade": "High School" if rng.random() < 0.7 else "Middle School",
            "region": i % regions,
            "base": rng.lognormvariate(3.1, 0.45),     # ~22 points median contribution
            "growth": rng.uniform(0.2, 1.4),            # improvement over the season
        })
    by_region = [[t for t in teams if t["region"] == r] for r in range(regions)]

    def strength(t: dict, ts: float) -> float:
        frac = (ts - t0) / (season_days * DAY)
        return t["base"] * (1 + t["growth"] * frac)

    truth: dict[int, float] = {}
    truth_by_event: dict[int, dict[int, float]] = {}
    (out / "events").mkdir(parents=True, exist_ok=True)
    for e in range(n_events + 1):
        worlds = e == n_events
        if worlds:
            start = t0 + (season_days + 20) * DAY
            pool = sorted(teams, key=lambda t: -strength(t, start))
            pool = [t for t in pool if t["grade"] == "High School"][:80]
            name = "VEX Robotics World Championship - High School"
        else:
            start = t0 + rng.uniform(0, season_days) * DAY
            r = rng.randrange(regions)
            k = rng.randint(20, 44)
            local = rng.sample(by_region[r], min(len(by_region[r]), int(k * 0.85)))
            others = rng.sample(teams, k - len(local))
            pool = list({t["id"]: t for t in local + others}.values())
            name = f"Synthetic Tournament {e}"
        end = start + DAY
        eid = 50000 + e
        matches, mid = [], 0
        record = {t["id"]: 0 for t in pool}

        def play(red, blue, rnd, inst, num, ts):
            nonlocal mid
            sc = []
            for al in (red, blue):
                mu = sum(strength(t, ts) for t in al)
                sc.append(max(0, int(round(rng.gauss(mu, 0.22 * mu + 4)))))
            mid += 1
            started = None if rng.random() < missing_times else _iso(ts)
            matches.append({
                "id": eid * 1000 + mid, "division": {"id": 1}, "round": rnd, "instance": inst,
                "matchnum": num, "scheduled": None, "started": started, "scored": True,
                "alliances": [
                    {"color": "red", "score": sc[0], "teams": [{"team": {"id": t["id"], "name": t["number"]}, "sitting": False} for t in red]},
                    {"color": "blue", "score": sc[1], "teams": [{"team": {"id": t["id"], "name": t["number"]}, "sitting": False} for t in blue]},
                ]})
            return sc

        ts = start + 3600
        per_team = 8
        slots = []
        for _ in range(per_team):
            order = pool[:]
            rng.shuffle(order)
            slots.extend(order)
        num = 0
        for i in range(0, len(slots) - 3, 4):
            four = slots[i:i + 4]
            if len({t["id"] for t in four}) < 4:
                continue
            num += 1
            red, blue = four[:2], four[2:]
            s = play(red, blue, 2, 1, num, ts)
            ts += 420
            for t in red:
                record[t["id"]] += 2 if s[0] > s[1] else (1 if s[0] == s[1] else 0)
            for t in blue:
                record[t["id"]] += 2 if s[1] > s[0] else (1 if s[0] == s[1] else 0)
        # alliance selection: top 8 by record pick the strongest available (by true strength, noisy)
        ranked = sorted(pool, key=lambda t: -record[t["id"]] - rng.random())
        avail = ranked[:]
        alliances = []
        for cap in ranked[:8]:
            if cap not in avail:
                continue
            avail.remove(cap)
            if not avail:
                break
            pick = max(avail[:12], key=lambda t: strength(t, ts) * rng.uniform(0.8, 1.2))
            avail.remove(pick)
            alliances.append([cap, pick])
        rounds = [(3, alliances), ]
        current = alliances
        rnd_codes = {8: 3, 4: 4, 2: 5}
        while len(current) >= 2:
            code = rnd_codes.get(len(current), 3)
            nxt = []
            for j in range(len(current) // 2):
                a, b = current[j], current[-1 - j]
                s = play(a, b, code, j + 1, 1, ts)
                ts += 420
                nxt.append(a if s[0] >= s[1] else b)
            current = nxt
        skills = []
        for t in pool:
            st = strength(t, start)
            truth.setdefault(t["id"], st)
            truth_by_event.setdefault(eid, {})[t["id"]] = st
            if rng.random() < 0.85:
                skills.append({"team": {"id": t["id"], "name": t["number"]}, "type": "driver",
                               "score": max(0, int(rng.gauss(2.2 * st, 0.25 * st)))})
            if rng.random() < 0.6:
                skills.append({"team": {"id": t["id"], "name": t["number"]}, "type": "programming",
                               "score": max(0, int(rng.gauss(1.0 * st, 0.5 * st)))})
        rec = {
            "event": {"id": eid, "sku": f"RE-V5RC-25-{eid}", "name": name, "start": _iso(start),
                      "end": _iso(end), "level": "World" if worlds else "Other",
                      "divisions": [{"id": 1, "name": "Division 1"}]},
            "teams": [{"id": t["id"], "number": t["number"], "grade": t["grade"],
                       "location": {"country": "United States"}} for t in pool],
            "skills": skills, "matches": matches, "final": True,
        }
        (out / "events" / f"{eid}.json").write_text(json.dumps(rec))
    # Skills-only events (no matches): how many real teams first post a score.
    for e in range(n_skills_events):
        start = t0 + rng.uniform(0, season_days) * DAY
        eid = 70000 + e
        r = rng.randrange(regions)
        pool = rng.sample(by_region[r], min(len(by_region[r]), rng.randint(10, 25)))
        skills = []
        for t in pool:
            st = strength(t, start)
            skills.append({"team": {"id": t["id"], "name": t["number"]}, "type": "driver",
                           "score": max(0, int(rng.gauss(2.2 * st, 0.25 * st)))})
            if rng.random() < 0.6:
                skills.append({"team": {"id": t["id"], "name": t["number"]}, "type": "programming",
                               "score": max(0, int(rng.gauss(1.0 * st, 0.5 * st)))})
        rec = {"event": {"id": eid, "sku": f"RE-V5RC-25-{eid}", "name": f"Skills Only {e}",
                         "start": _iso(start), "end": _iso(start), "level": "Other", "divisions": []},
               "teams": [{"id": t["id"], "number": t["number"], "grade": t["grade"]} for t in pool],
               "skills": skills, "matches": [], "final": True}
        (out / "events" / f"{eid}.json").write_text(json.dumps(rec))
    (out / "season.json").write_text(json.dumps({"season": {"id": 0, "name": "Synthetic season"}}))
    return {"teams": teams, "truth_start": truth, "truth_by_event": truth_by_event}
