"""TrueSkill for 2v2 matches, the rating most VEX apps and vrc-data-analysis use.

Closed-form two-team update (Herbrich et al. 2007). Defaults match the
`trueskill` Python package, which is what the community leaderboards run, so
this is a faithful baseline. Verified against that package in tests.
"""
from __future__ import annotations

import math
from statistics import NormalDist

from ..dataset import Match, Season
from .base import Model, Pred

_N = NormalDist()


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _v_win(t: float, e: float) -> float:
    d = _cdf(t - e)
    return _pdf(t - e) / d if d > 1e-12 else -(t - e)


def _w_win(t: float, e: float) -> float:
    v = _v_win(t, e)
    return v * (v + t - e)


def _v_draw(t: float, e: float) -> float:
    a, b = e - t, -e - t
    denom = _cdf(a) - _cdf(b)
    if denom < 1e-12:
        return -t + e if t < 0 else -t - e
    return (_pdf(b) - _pdf(a)) / denom


def _w_draw(t: float, e: float) -> float:
    a, b = e - t, -e - t
    denom = _cdf(a) - _cdf(b)
    if denom < 1e-12:
        return 1.0
    v = _v_draw(t, e)
    return v * v + (a * _pdf(a) - b * _pdf(b)) / denom


class TrueSkill(Model):
    name = "TrueSkill"

    def __init__(self, mu: float = 25.0, sigma: float = 25.0 / 3, beta: float = 25.0 / 6,
                 tau: float = 25.0 / 300, draw_probability: float = 0.10):
        self.mu0, self.sigma0, self.beta, self.tau, self.p_draw = mu, sigma, beta, tau, draw_probability

    def params(self) -> dict:
        return {"mu": self.mu0, "sigma": self.sigma0, "beta": self.beta, "tau": self.tau,
                "draw_probability": self.p_draw}

    def reset(self, season: Season) -> None:
        super().reset(season)
        self.r: dict[int, list[float]] = {}

    def _get(self, t: int) -> list[float]:
        r = self.r.get(t)
        if r is None:
            r = self.r[t] = [self.mu0, self.sigma0 ** 2]
        return r

    def predict(self, m: Match) -> Pred:
        red = [self._get(t) for t in m.red]
        blue = [self._get(t) for t in m.blue]
        dmu = sum(r[0] for r in red) - sum(r[0] for r in blue)
        n = len(red) + len(blue)
        denom = math.sqrt(n * self.beta ** 2 + sum(r[1] for r in red + blue))
        return Pred(_cdf(dmu / denom))

    def update(self, m: Match) -> None:
        red = [self._get(t) for t in m.red]
        blue = [self._get(t) for t in m.blue]
        for r in red + blue:  # dynamics
            r[1] += self.tau ** 2
        n = len(red) + len(blue)
        c2 = sum(r[1] for r in red + blue) + n * self.beta ** 2
        c = math.sqrt(c2)
        eps = _N.inv_cdf((self.p_draw + 1) / 2) * math.sqrt(n) * self.beta / c
        if m.outcome == 0.5:
            t = (sum(r[0] for r in red) - sum(r[0] for r in blue)) / c
            v, w = _v_draw(t, eps), _w_draw(t, eps)
            win, lose = red, blue
        else:
            win, lose = (red, blue) if m.outcome == 1.0 else (blue, red)
            t = (sum(r[0] for r in win) - sum(r[0] for r in lose)) / c
            v, w = _v_win(t, eps), _w_win(t, eps)
        for r in win:
            r[0] += r[1] / c * v
            r[1] *= max(1 - r[1] / c2 * w, 1e-6)
        for r in lose:
            r[0] -= r[1] / c * v
            r[1] *= max(1 - r[1] / c2 * w, 1e-6)

    def rating(self, team_id: int) -> tuple[float, float]:
        mu, var = self._get(team_id)
        return mu, math.sqrt(var)
