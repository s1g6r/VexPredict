import numpy as np
import pytest

from vexpredict import simcheck
from vexpredict.dataset import load_season
from vexpredict.models.epa import EPA
from vexpredict.simulator import (ScoreNoise, SimInputs, Standing, TeamRates, captain_count,
                                  fit_score_noise, simulate)
from vexpredict.synth import generate


def _inputs(rating, remaining, standings=None, unc=0.0):
    teams = list(rating)
    return SimInputs(teams, standings or {}, remaining, rating, {t: unc for t in teams},
                     TeamRates(), ScoreNoise(2.0, 0.1))


def _round_robin(teams, rounds, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(rounds):
        p = list(rng.permutation(teams))
        for i in range(0, len(p) - 3, 4):
            out.append((tuple(p[i:i + 2]), tuple(p[i + 2:i + 4])))
    return out


def test_probabilities_are_distributions():
    rating = {t: float(10 + t) for t in range(12)}
    res = simulate(_inputs(rating, _round_robin(list(rating), 6)), sims=500)
    assert np.allclose(res.rank_probs.sum(axis=1), 1)
    assert np.allclose(res.rank_probs.sum(axis=0), 1)
    assert res.mean_rank.min() >= 1 and res.mean_rank.max() <= 12


def test_dominant_team_ranks_first():
    rating = {t: 10.0 for t in range(12)}
    rating[7] = 60.0
    res = simulate(_inputs(rating, _round_robin(list(rating), 8)), sims=500)
    assert res.rank_probs[7, 0] > 0.8


def test_no_matches_left_keeps_current_order():
    rating = {t: 20.0 for t in range(6)}
    st = {t: Standing(wp=2 * t, wins=t, losses=5 - t) for t in range(6)}
    res = simulate(_inputs(rating, [], st), sims=200)
    assert list(np.argsort(res.mean_rank)) == [5, 4, 3, 2, 1, 0]


def test_uncertainty_flattens_predictions():
    rating = {t: float(10 + 2 * t) for t in range(16)}
    sched = _round_robin(list(rating), 6)
    sharp = simulate(_inputs(rating, sched, unc=0.0), sims=800, seed=1)
    flat = simulate(_inputs(rating, sched, unc=15.0), sims=800, seed=1)
    assert sharp.rank_probs[15, 0] > flat.rank_probs[15, 0]


def test_fit_score_noise_recovers_parameters():
    rng = np.random.default_rng(0)
    mu = rng.uniform(10, 100, 5000)
    actual = mu + (3 + 0.2 * mu) * rng.standard_normal(5000)
    n = fit_score_noise(list(zip(mu, actual)))
    assert n.c0 == pytest.approx(3, abs=1.0) and n.c1 == pytest.approx(0.2, abs=0.03)


def test_captain_count():
    assert [captain_count(n) for n in (6, 12, 20, 40)] == [2, 4, 8, 16]


def test_simcheck_beats_standings(tmp_path):
    generate(tmp_path, n_teams=300, n_events=60, n_skills_events=30, seed=5)
    season = load_season("x", root=tmp_path)
    res = simcheck.run_check(season, EPA(), sims=300, log=lambda *_: None)
    for cut in ("cut_0", "cut_50"):
        a = res[cut]
        assert a["divisions"] > 5
        assert a["spearman_sim"] > a["spearman_standings"]
        assert a["brier_sim"] < a["brier_standings"]
    path = simcheck.write_report(res, tmp_path / "rep")
    assert "Simulator" in open(path).read()
