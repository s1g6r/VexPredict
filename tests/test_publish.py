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
