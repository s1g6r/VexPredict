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
            "id": 1000 + i, "number": f"D{100 + i}{'ABCDE'[i % 5]}",
            "grade": "High School" if rng.random() < 0.7 else "Middle School",
            "region": i % regions,
            "base": rng.lognormvariate(3.1, 0.45),     # ~22 points median contribution
            "growth": rng.uniform(0.2, 1.4),            # improvement over the season
            "auton": rng.random(),                      # autonomous quality (AWP / AP)
            "name": f"Demo Robotics {i + 1}",
            "state": ["Illinois", "Indiana", "Wisconsin", "Ohio", "Michigan", "Iowa", "Missouri", "Kentucky"][i % regions],
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
            name = "Demo World Championship (synthetic)"
        else:
            start = t0 + rng.uniform(0, season_days) * DAY
            r = rng.randrange(regions)
            k = rng.randint(20, 44)
            local = rng.sample(by_region[r], min(len(by_region[r]), int(k * 0.85)))
            others = rng.sample(teams, k - len(local))
            pool = list({t["id"]: t for t in local + others}.values())
            name = f"Demo Tournament {e}"
        end = start + DAY
        eid = 50000 + e
        matches, mid = [], 0
        record = {t["id"]: 0 for t in pool}
        stats = {t["id"]: {"wins": 0, "losses": 0, "ties": 0, "wp": 0, "ap": 0, "sp": 0} for t in pool}

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
            # autonomous bonus (AP) to the alliance with better autons; AWP per team
            ra = sum(t["auton"] for t in red) + rng.gauss(0, 0.4)
            ba = sum(t["auton"] for t in blue) + rng.gauss(0, 0.4)
            ap_red, ap_blue = (10, 0) if ra > ba else (0, 10)
            for al, mine, theirs, ap in ((red, s[0], s[1], ap_red), (blue, s[1], s[0], ap_blue)):
                for t in al:
                    st = stats[t["id"]]
                    w = 2 if mine > theirs else (1 if mine == theirs else 0)
                    st["wins" if w == 2 else ("ties" if w == 1 else "losses")] += 1
                    awp = 1 if rng.random() < 0.7 * t["auton"] ** 2 else 0
                    st["wp"] += w + awp
                    st["ap"] += ap
                    st["sp"] += min(mine, theirs)
                    record[t["id"]] = st["wp"]
        # VEX ranking: WP, then AP, then SP
        ranked = sorted(pool, key=lambda t: (-stats[t["id"]]["wp"], -stats[t["id"]]["ap"],
                                             -stats[t["id"]]["sp"], rng.random()))
        rankings = [dict({"rank": i + 1, "team": {"id": t["id"], "name": t["number"]},
                          "division": {"id": 1}}, **stats[t["id"]]) for i, t in enumerate(ranked)]
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
            "event": {"id": eid, "sku": f"DEMO-{eid}", "name": name, "start": _iso(start),
                      "end": _iso(end), "level": "World" if worlds else "Other",
                      "divisions": [{"id": 1, "name": "Division 1"}]},
            "teams": [{"id": t["id"], "number": t["number"], "grade": t["grade"], "team_name": t["name"],
                       "location": {"country": "United States", "region": t["state"]}} for t in pool],
            "skills": skills, "matches": matches, "rankings": rankings, "final": True,
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
        rec = {"event": {"id": eid, "sku": f"DEMO-{eid}", "name": f"Demo Skills Day {e}",
                         "start": _iso(start), "end": _iso(start), "level": "Other", "divisions": []},
               "teams": [{"id": t["id"], "number": t["number"], "grade": t["grade"]} for t in pool],
               "skills": skills, "matches": [], "final": True}
        (out / "events" / f"{eid}.json").write_text(json.dumps(rec))
    (out / "season.json").write_text(json.dumps({"season": {"id": 0, "name": "Synthetic season"}, "synthetic": True}))
    return {"teams": teams, "truth_start": truth, "truth_by_event": truth_by_event}


def make_live(out: Path, event_id: int, frac: float = 0.5, seed: int = 0) -> float:
    """Turn a finished synthetic event into one that is in progress: quals after
    `frac` lose their scores, elims disappear, and rankings reflect only the
    played matches. Returns a timestamp to use as 'now'."""
    rng = random.Random(seed)
    path = out / "events" / f"{event_id}.json"
    rec = json.loads(path.read_text())
    quals = [m for m in rec["matches"] if m["round"] == 2]
    quals.sort(key=lambda m: m["matchnum"])
    cut = int(len(quals) * frac)
    stats: dict[int, dict] = {}
    names: dict[int, str] = {}
    for i, m in enumerate(quals):
        if i >= cut:
            m["scored"] = False
            m["started"] = None
            for a in m["alliances"]:
                a["score"] = 0
            continue
        red, blue = m["alliances"][0], m["alliances"][1]
        for a, o in ((red, blue), (blue, red)):
            for t in a["teams"]:
                tid = t["team"]["id"]
                names[tid] = t["team"]["name"]
                st = stats.setdefault(tid, {"wins": 0, "losses": 0, "ties": 0, "wp": 0, "ap": 0, "sp": 0})
                w = 2 if a["score"] > o["score"] else (1 if a["score"] == o["score"] else 0)
                st["wins" if w == 2 else ("ties" if w == 1 else "losses")] += 1
                st["wp"] += w + (1 if rng.random() < 0.15 else 0)
                st["ap"] += 10 if rng.random() < 0.5 else 0
                st["sp"] += min(a["score"], o["score"])
    rec["matches"] = quals
    order = sorted(stats, key=lambda t: (-stats[t]["wp"], -stats[t]["ap"], -stats[t]["sp"]))
    rec["rankings"] = [dict({"rank": i + 1, "team": {"id": t, "name": names[t]}, "division": {"id": 1}}, **stats[t])
                       for i, t in enumerate(order)]
    rec["final"] = False
    path.write_text(json.dumps(rec))
    played = [m for m in quals[:cut] if m.get("started")]
    start = dt.datetime.fromisoformat(rec["event"]["start"].replace("Z", "+00:00")).timestamp()
    return max([start + 3600] + [dt.datetime.fromisoformat(m["started"].replace("Z", "+00:00")).timestamp()
                                 for m in played]) + 600


def add_upcoming(out: Path, after_ts: float, teams: list[dict], n: int = 36, seed: int = 0) -> int:
    rng = random.Random(seed)
    eid = 90000
    pool = rng.sample(teams, n)
    start = after_ts + 10 * DAY
    rec = {"event": {"id": eid, "sku": f"DEMO-{eid}", "name": "Demo Invitational (upcoming)",
                     "start": _iso(start), "end": _iso(start + DAY), "level": "Other",
                     "divisions": [{"id": 1, "name": "Division 1"}]},
           "teams": [{"id": t["id"], "number": t["number"], "grade": t["grade"], "team_name": t["name"],
                      "location": {"country": "United States", "region": t["state"]}} for t in pool],
           "skills": [], "matches": [], "rankings": [], "final": False}
    (out / "events" / f"{eid}.json").write_text(json.dumps(rec))
    return eid
