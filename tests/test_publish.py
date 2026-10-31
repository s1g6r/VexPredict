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
