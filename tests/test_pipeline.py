import math
import random

import numpy as np
import pytest

from vexpredict import backtest
from vexpredict.dataset import Match, load_season
from vexpredict.models.epa import EPA, EPASkills, fit_skills_map
from vexpredict.models.opr import EventCCWM, EventOPR, WinRate
from vexpredict.models.trueskill_model import TrueSkill
from vexpredict.synth import generate


@pytest.fixture(scope="module")
def season(tmp_path_factory):
    root = tmp_path_factory.mktemp("synth")
    info = generate(root, seed=1)
    s = load_season("synthetic", root=root)
    s._truth = info
    return s


def test_loader_orders_and_counts(season):
    ts = [m.ts for m in season.matches]
    assert ts == sorted(ts)
    assert [m.idx for m in season.matches] == list(range(len(season.matches)))
    assert len(season.matches) > 3000
    for eid in {m.event_id for m in season.matches}:
        rounds = [m.round for m in season.matches if m.event_id == eid]
        first_elim = next((i for i, r in enumerate(rounds) if r != 2), len(rounds))
        assert all(r == 2 for r in rounds[:first_elim]) and all(r != 2 for r in rounds[first_elim:])
    assert any(season.events[e].is_worlds for e in season.events)


def test_trueskill_matches_reference_package():
    ts = pytest.importorskip("trueskill")
    env = ts.TrueSkill(draw_probability=0.10)
    ref = {i: env.create_rating() for i in range(8)}
    mine = TrueSkill()
    mine.reset(None)
    rng = random.Random(3)
    for k in range(300):
        four = rng.sample(range(8), 4)
        rs, bs = rng.randint(0, 60), rng.randint(0, 60)
        if k % 25 == 0:
            bs = rs
        m = Match(k, 1, 1, 2, 1, k, float(k), tuple(four[:2]), tuple(four[2:]), rs, bs)
        p_mine = mine.predict(m).p_red
        mu = sum(ref[t].mu for t in four[:2]) - sum(ref[t].mu for t in four[2:])
        s2 = sum(ref[t].sigma ** 2 for t in four)
        p_ref = 0.5 * math.erfc(-mu / math.sqrt(2 * (4 * env.beta ** 2 + s2)))
        assert p_mine == pytest.approx(p_ref, abs=1e-6)
        ranks = [0, 1] if rs > bs else ([1, 0] if bs > rs else [0, 0])
        new = env.rate([[ref[t] for t in four[:2]], [ref[t] for t in four[2:]]], ranks=ranks)
        for t, r in zip(four, new[0] + new[1]):
            ref[t] = r
        mine.update(m)
    for t in range(8):
        mu, sigma = mine.rating(t)
        assert mu == pytest.approx(ref[t].mu, abs=1e-4)
        assert sigma == pytest.approx(ref[t].sigma, abs=1e-4)


@pytest.mark.parametrize("factory", [TrueSkill, WinRate, EventOPR, EventCCWM, EPA, EPASkills])
def test_no_future_leakage(season, factory):
    """Predictions for the first half must be identical whether or not the
    second half of the season exists."""
    cut = season.matches[len(season.matches) // 2].ts
    full = backtest.run(factory(), season)
    part = backtest.run(factory(), season, until_ts=cut)
    assert len(part) > 100
    for a, b in zip(part, full):
        assert a.m.idx == b.m.idx
        assert a.pred.p_red == pytest.approx(b.pred.p_red, abs=1e-12)


def test_in_event_opr_recovers_truth(season):
    """Full-event OPR at a big event should correlate strongly with the true
    contribution the generator used."""
    eid = max(season.events, key=lambda e: sum(m.event_id == e for m in season.matches))
    model = EventOPR(lam=0.1)
    model.reset(season)
    for m in season.matches:
        if m.event_id == eid:
            model.update(m)
    sol = model.events[eid].solve(0.0)
    truth = season._truth["truth_by_event"][eid]
    ids = [t for t in sol if t in truth]
    r = np.corrcoef([sol[t] for t in ids], [truth[t] for t in ids])[0, 1]
    assert r > 0.7


def test_skills_map_positive(season):
    split = season.matches[int(len(season.matches) * 0.4)].ts
    a, b, r2, n = fit_skills_map(season, split)
    assert n > 100 and b > 0 and r2 > 0.2


def test_end_to_end_backtest_and_report(season, tmp_path):
    res = backtest.evaluate(season, quick=True, log=lambda *_: None)
    hs = {k: v["slices"]["HS, all matches"] for k, v in res["results"].items()}
    for name, m in hs.items():
        assert m["n"] > 300, name
        assert 0.5 < m["accuracy"] <= 1.0, name
    # On data generated as "score = sum of contributions", point models should
    # beat win/loss-only TrueSkill.
    assert hs["EPA"]["brier"] < hs["TrueSkill"]["brier"]
    path = backtest.write_report(res, tmp_path)
    text = path.read_text()
    assert "HS Worlds" in text and "Calibration" in text


def test_skills_prior_beats_field_average_at_first_appearance(season):
    """When a team first shows up, the skills-based starting rating should be
    much closer to its true strength than starting everyone at the average."""
    split = season.matches[int(len(season.matches) * 0.4)].ts
    a, b, _, _ = fit_skills_map(season, split)
    model = EPASkills(skills_map=(a, b))
    model.reset(season)
    truth = season._truth["truth_by_event"]
    err_prior, err_mean = [], []
    for m in season.matches:
        model.feed.advance(m.ts)
        for t in m.teams:
            if t not in model.e:
                p = model._prior(t)
                if p is not None:
                    err_prior.append(abs(p - truth[m.event_id][t]))
                    err_mean.append(abs(model.scale.mean / 2 - truth[m.event_id][t]))
        model.predict(m)
        model.update(m)
    assert len(err_prior) > 50
    assert np.mean(err_prior) < 0.8 * np.mean(err_mean)
