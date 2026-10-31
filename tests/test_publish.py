import json

import pytest

from vexpredict import backtest, publish
from vexpredict.dataset import load_season
from vexpredict.synth import add_upcoming, generate, make_live


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    info = generate(raw, n_teams=300, n_events=50, n_skills_events=20, seed=9)
    now = make_live(raw, 50000 + 50, 0.5)
    add_upcoming(raw, now, [t for t in info["teams"] if t["grade"] == "High School"], n=20)
    season = load_season("t", root=raw)
    out = publish.publish(season, "t", out=tmp_path_factory.mktemp("site"), now_ts=now)
    return season, out


def test_files_and_statuses(published):
    season, out = published
    meta = json.loads((out / "meta.json").read_text())
    assert meta["synthetic"] is True
    statuses = {e["status"] for e in meta["events"]}
    assert {"done", "live", "upcoming"} <= statuses
    board = json.loads((out / "leaderboard.json").read_text())
    assert board and [b["rank"] for b in board] == list(range(1, len(board) + 1))
    assert all(board[i]["rating"] >= board[i + 1]["rating"] for i in range(len(board) - 1))
    assert (out / "teams" / f"{board[0]['id']}.json").exists()
    assert json.loads((out.parent / "seasons.json").read_text())[0]["slug"] == "t"


def test_live_event_has_pending_predictions_and_sim(published):
    _, out = published
    ev = json.loads((out / "events" / "50050.json").read_text())
    assert ev["status"] == "live" and ev["pending"] and "sim_live" in ev
    total = sum(v["p_captain"] for v in ev["sim_live"]["teams"].values())
    assert total == pytest.approx(sum(ev["sim_live"]["by_div"].values()), abs=0.05)
    if len(ev.get("divisions", [])) > 1:   # synthetic Worlds: each division ranks separately
        assert {v["div"] for v in ev["sim_live"]["teams"].values()} == {d["id"] for d in ev["divisions"]}
    up = json.loads((out / "events" / "90000.json").read_text())
    assert up["status"] == "upcoming" and "sim_pre" in up and not up["matches"]


def test_site_predictions_are_pre_match_backtest_predictions(published):
    """What the site shows for a played match must be exactly what the model
    predicted before that match, not a hindsight number."""
    season, out = published
    model, _ = publish.build_model(season, "t")
    recs = backtest.run(model, season)
    by_event = {}
    for r in recs:
        by_event.setdefault(r.m.event_id, []).append(r)
    eid = next(iter(by_event))
    ev = json.loads((out / "events" / f"{eid}.json").read_text())
    for shown, r in zip(ev["matches"], by_event[eid]):
        assert shown["p"] == pytest.approx(r.pred.p_red, abs=6e-4)


def test_site_uses_tuned_adaptive_model_with_its_calibration(tmp_path, monkeypatch):
    """With backtest settings saved, the site must show the adaptive model's
    probabilities with the backtest's fitted temperature applied (the
    backtest's accuracy numbers are for calibrated probabilities)."""
    from vexpredict import tuned
    from vexpredict.models.epa import EPAMix
    raw = tmp_path / "raw"
    generate(raw, n_teams=120, n_events=20, n_skills_events=5, seed=4)
    season = load_season("t", root=raw)
    params = {"k_start": 0.3, "k_end": 0.15, "k_tau": 8.0, "elim_weight": 0.33, "huber_c": 100.0, "prob_k": 0.6,
              "init_frac": 0.8, "gap_tau": 0.0, "skills_a": 0.8, "skills_b": 0.25, "anchor_n": 15.0,
              "margin_ws": [0.0, 1.0], "sub_temps": [0.6, 0.7], "half_life": 300.0}
    reports = tmp_path / "reports"
    (reports / "t").mkdir(parents=True)
    (reports / "t" / "metrics.json").write_text(json.dumps({"results": {
        "EPA + skills, adaptive": {"params": params, "temperature": 0.8}}}))
    monkeypatch.setattr(tuned, "REPORTS_DIR", reports)
    out = publish.publish(season, "t", out=tmp_path / "site")
    meta = json.loads((out / "meta.json").read_text())
    assert meta["model"]["name"] == "EPA + skills, adaptive" and meta["model"]["temperature"] == 0.8
    p = dict(params, skills_map=(params.pop("skills_a"), params.pop("skills_b")))
    calibrated = backtest.run(EPAMix(temp=0.8, **p), season)
    raw_recs = backtest.run(EPAMix(**p), season)
    eid = calibrated[-1].m.event_id
    ev = json.loads((out / "events" / f"{eid}.json").read_text())
    mine = [r for r in calibrated if r.m.event_id == eid]
    raws = [r for r in raw_recs if r.m.event_id == eid]
    assert len(ev["matches"]) == len(mine) > 10
    for shown, r, r0 in zip(ev["matches"], mine, raws):
        assert shown["p"] == pytest.approx(r.pred.p_red, abs=6e-4)
    assert any(abs(r.pred.p_red - r0.pred.p_red) > 0.01 for r, r0 in zip(mine, raws))


def test_old_unplayed_matches_dont_keep_an_event_live(tmp_path):
    """Scheduled matches that were never played (cancelled, or results never
    entered) must not leave a finished event showing as live forever."""
    raw = tmp_path / "raw"
    generate(raw, n_teams=80, n_events=6, n_skills_events=2, seed=5)
    path = raw / "events" / "50001.json"
    rec = json.loads(path.read_text())
    quals = [m for m in rec["matches"] if m["round"] == 2][-3:]
    for m in quals:
        m["started"] = None
        for a in m["alliances"]:
            a["score"] = 0
    path.write_text(json.dumps(rec))
    season = load_season("t", root=raw)
    assert len(season.pending[50001]) == 3
    ev = season.events[50001]
    during = publish.publish(season, "t", out=tmp_path / "a", now_ts=ev.end - 3600)
    later = publish.publish(season, "t", out=tmp_path / "b", now_ts=ev.end + 30 * 86400)
    e1 = json.loads((during / "events" / "50001.json").read_text())
    e2 = json.loads((later / "events" / "50001.json").read_text())
    assert e1["status"] == "live" and len(e1["pending"]) == 3
    assert e2["status"] == "done" and not e2["pending"] and "sim_live" not in e2


def test_hub_files(published):
    """Qualification, skills standings and the event planner come straight
    from the published results."""
    season, out = published
    q = json.loads((out / "qualify.json").read_text())
    names = {t["name"] for t in q["targets"]}
    assert names == {"Region championship (States)", "World Championship"}
    # every qualification is a real award win by that team
    wins = {(a.event_id, t) for a in season.awards for t in a.team_ids}
    for tid, rec in q["teams"].items():
        assert season.teams[int(tid)].is_hs
        for r in rec["quals"]:
            assert (r["event_id"], int(tid)) in wins
    sk = json.loads((out / "skills.json").read_text())
    assert [r["rank"] for r in sk] == list(range(1, len(sk) + 1))
    assert all(sk[i]["score"] >= sk[i + 1]["score"] for i in range(len(sk) - 1))
    assert all(r["score"] == r["auto"] + r["driver"] for r in sk)
    qualified = {int(t) for t in q["teams"]}
    assert any(r["qualified"] for r in sk) and all(bool(r["qualified"]) == (r["id"] in qualified) for r in sk)
    plan = json.loads((out / "plan.json").read_text())
    ids = {e["id"] for e in plan["events"]}
    assert 90000 in ids and {95000 + k for k in range(12)} <= ids           # registered and calendar-only
    up = next(e for e in plan["events"] if e["id"] == 90000)
    assert up["hs"] == len(up["teams"]) and up["ratings"] == sorted(up["ratings"], reverse=True)
    assert "hs" not in next(e for e in plan["events"] if e["id"] == 95000)   # no team list yet
    assert plan["team_loc"] and all(len(v) == 3 for v in plan["team_loc"].values())


def test_qualification_labels():
    """Every qualification lands on States or Worlds: a state championship's
    event code counts as States; Middle School and other championships don't
    count for a High School team."""
    from vexpredict import hub
    from vexpredict.dataset import Award, Event, Season, Team
    s = Season(name="x")
    s.teams[1] = Team(1, "1A", grade="High School")
    s.events[5] = Event(5, "E5", "Local", 0.0, 0.0, "Other")
    s.calendar[9] = Event(9, "VE-V5-26-9", "Illinois State Championship (HS)", 0.0, 0.0, "Regional")
    s.calendar[8] = Event(8, "VE-V5-26-8", "Illinois State Championship (MS)", 0.0, 0.0, "Regional")
    s.awards.append(Award(5, "Excellence Award (V5)", ("VE-V5-26-9", "Event Region Championship",
                                                      "VE-V5-26-8", "JROTC National Championship"), (1,)))
    got = [(r["target"], r["listed"]) for r in hub.qualifications(s)[1]]
    assert got == [("Region championship (States)", True)]


def test_unlisted_qualifications():
    """When an event lists no qualifications at all, its Excellence, Tournament
    Champions and Skills Champion winners qualify the usual way (local event to
    States, Signature to Worlds); an event that lists some is taken as written."""
    from vexpredict import hub
    from vexpredict.dataset import Award, Event, Season, Team
    s = Season(name="x")
    for t in range(1, 7):
        s.teams[t] = Team(t, f"{t}A", grade="High School")
    s.events[1] = Event(1, "E1", "Local", 0.0, 0.0, "Other")
    s.events[2] = Event(2, "E2", "Sig", 1.0, 1.0, "Signature")
    s.events[3] = Event(3, "E3", "Listed", 2.0, 2.0, "Other")
    s.events[4] = Event(4, "E4", "Scrimmage", 3.0, 3.0, "Other")
    s.awards += [Award(1, "Excellence Award (V5)", (), (1,)), Award(1, "Tournament Champions (V5)", (), (2,)),
                 Award(1, "Design Award (V5)", (), (3,)), Award(2, "Robot Skills Champion (V5)", (), (4,)),
                 Award(3, "Excellence Award (V5)", ("Event Region Championship",), (5,)),
                 Award(3, "Tournament Champions (V5)", (), (6,)), Award(4, "Excellence Award (V5)", (), (3,))]
    q = hub.qualifications(s)
    assert q[1] == [{"target": "Region championship (States)", "award": "Excellence Award", "event_id": 1,
                     "listed": False, "event": "Local", "date": "1970-01-01"}]
    assert q[2][0]["target"] == "Region championship (States)" and q[4][0]["target"] == "World Championship"
    assert q[5][0]["listed"] and 3 not in q and 6 not in q


def test_schedule_luck():
    """Easy draws (strong partners, weak opponents) score positive, hard draws
    negative; across a division the effects cancel out."""
    import random
    from types import SimpleNamespace as M
    from vexpredict import hub
    rng = random.Random(1)
    rating = {t: rng.uniform(10, 40) for t in range(1, 25)}
    rating[100], rating[101] = 80.0, 2.0          # one star, one very weak team
    teams = list(rating)
    group = []
    for _ in range(10):
        rng.shuffle(teams)
        group += [M(red=tuple(teams[i:i + 2]), blue=tuple(teams[i + 2:i + 4])) for i in range(0, len(teams) - 3, 4)]
    # team 1 always plays with the star against the weak team; team 2 the reverse
    group += [M(red=(1, 100), blue=(101, 3)) for _ in range(3)] + [M(red=(2, 101), blue=(100, 4)) for _ in range(3)]
    luck = hub.schedule_luck({1: group}, rating, scale=10.0)
    assert abs(sum(v["luck"] for v in luck.values())) < 1e-9
    assert luck[1]["luck"] > 1.0 and luck[2]["luck"] < -1.0
    assert luck[1]["n"] == sum(1 in x.red + x.blue for x in group)


def test_web_pairs(published):
    """Every thread in the web is a real partnership, counted right, in the
    order the pairs first played together."""
    season, out = published
    w = json.loads((out / "web.json").read_text())
    t, p = w["t"], w["p"]
    ids = {num: tid for tid, tm in season.teams.items() for num in [tm.number]}
    together = {}
    first = {}
    for m in season.matches:
        for side in (m.red, m.blue):
            key = tuple(sorted(side))
            together[key] = together.get(key, 0) + 1
            first.setdefault(key, m.idx)
    seen = []
    for i in range(0, len(p), 5):
        a, b, n, wins = (ids[t["num"][p[i]]], ids[t["num"][p[i + 1]]], p[i + 2], p[i + 3])
        key = tuple(sorted((a, b)))
        assert together[key] == n and 0 <= wins <= n
        seen.append(first[key])
    assert len(seen) == len(together) and seen == sorted(seen)
    assert w["champ"] == []          # this season's Worlds is still being played
    assert all(season.teams[tid].number == num for tid, num in zip(t["id"], t["num"]))


def test_world_champions(tmp_path):
    from vexpredict.web import world_champions
    generate(tmp_path, n_teams=200, n_events=12, n_skills_events=2, seed=6)
    s = load_season("t", root=tmp_path)
    champ = world_champions(s)
    worlds = next(e for e in s.events.values() if e.is_worlds)
    final = max((m for m in s.matches if m.event_id == worlds.id and m.round == 5), key=lambda m: m.ts)
    winner = final.red if final.red_score >= final.blue_score else final.blue
    assert len(champ) == 2 and set(champ) == set(winner)


def test_scan_file(published):
    """VEX Scan's file: every High School team once, ratings and ranks that
    match the leaderboard, event lists that point at real teams, and a win
    formula that agrees with the model."""
    season, out = published
    d = json.loads((out / "scan.json").read_text())
    t = d["t"]
    n = len(t["id"])
    assert n == len({x.id for x in season.teams.values() if x.is_hs}) and len(set(t["num"])) == n
    assert all(len(col) == n for col in t.values())
    board = {b["id"]: b for b in json.loads((out / "leaderboard.json").read_text())}
    for i, tid in enumerate(t["id"]):
        if tid in board:
            assert t["rk"][i] == board[tid]["rank"] and abs(t["r"][i] - board[tid]["rating"]) < 0.06
        else:
            assert t["r"][i] is None and t["rk"][i] == 0
    assert d["e"] and all(e["t"] and max(e["t"]) < n for e in d["e"])
    assert 0.005 < d["k"] < 0.5


def test_scan_short_names():
    from vexpredict.scan import short_name
    assert short_name("Lake Park High School VEX V5 Robotics Competition: Override High School Teams") == "Lake Park"
    assert short_name("WAVE at WPI Signature Event") == "WAVE at WPI Signature Event"
    assert short_name("VEX V5 Robotics Competition") == "VEX V5 Robotics Competition"   # nothing left: keep it
