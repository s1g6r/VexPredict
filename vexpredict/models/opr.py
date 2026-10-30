"""In-event OPR / CCWM, computed only from the qualification matches already
played at the current event (what VEX via, RoboScout etc. show live)."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from ..dataset import Match, Season
from .base import Model, Pred, ScoreScale, sigmoid


class _EventLSQ:
    """Ridge least squares, rebuilt lazily: x = argmin |Ax-b|^2 + lam|x-prior|^2."""

    def __init__(self, lam: float):
        self.lam = lam
        self.index: dict[int, int] = {}
        self.rows: list[tuple[tuple[int, ...], float]] = []
        self.sol: dict[int, float] | None = None

    def add(self, teams: tuple[int, ...], target: float) -> None:
        for t in teams:
            self.index.setdefault(t, len(self.index))
        self.rows.append((teams, target))
        self.sol = None

    def solve(self, prior: float) -> dict[int, float]:
        if self.sol is not None and self._prior == prior:
            return self.sol
        n = len(self.index)
        if n == 0:
            self.sol, self._prior = {}, prior
            return self.sol
        ata = np.zeros((n, n))
        atb = np.zeros(n)
        for teams, y in self.rows:
            ids = [self.index[t] for t in teams]
            for i in ids:
                atb[i] += y
                for j in ids:
                    ata[i, j] += 1.0
        ata[np.diag_indices(n)] += self.lam
        atb += self.lam * prior
        x = np.linalg.solve(ata, atb)
        self.sol = {t: float(x[i]) for t, i in self.index.items()}
        self._prior = prior
        return self.sol


class EventOPR(Model):
    """Predicts alliance score = sum of in-event OPRs; win prob from the margin."""

    name = "OPR (in-event)"
    has_scores = True

    def __init__(self, lam: float = 1.0, prob_k: float = 1.0):
        self.lam, self.prob_k = lam, prob_k

    def params(self) -> dict:
        return {"lam": self.lam, "prob_k": self.prob_k}

    def reset(self, season: Season) -> None:
        super().reset(season)
        self.events: dict[int, _EventLSQ] = defaultdict(lambda: _EventLSQ(self.lam))
        self.scale = ScoreScale()

    def predict(self, m: Match) -> Pred:
        prior = self.scale.mean / 2
        sol = self.events[m.event_id].solve(prior)
        red = sum(sol.get(t, prior) for t in m.red)
        blue = sum(sol.get(t, prior) for t in m.blue)
        return Pred(sigmoid((red - blue) / (self.prob_k * self.scale.std)), red, blue)

    def update(self, m: Match) -> None:
        if m.is_qual:
            ev = self.events[m.event_id]
            ev.add(m.red, m.red_score)
            ev.add(m.blue, m.blue_score)
        self.scale.add(m.red_score)
        self.scale.add(m.blue_score)


class EventCCWM(Model):
    """CCWM = OPR - DPR, fit directly on winning margins."""

    name = "CCWM (in-event)"

    def __init__(self, lam: float = 1.0, prob_k: float = 1.0):
        self.lam, self.prob_k = lam, prob_k

    def params(self) -> dict:
        return {"lam": self.lam, "prob_k": self.prob_k}

    def reset(self, season: Season) -> None:
        super().reset(season)
        self.events: dict[int, _EventLSQ] = defaultdict(lambda: _EventLSQ(self.lam))
        self.scale = ScoreScale()

    def predict(self, m: Match) -> Pred:
        sol = self.events[m.event_id].solve(0.0)
        margin = sum(sol.get(t, 0.0) for t in m.red) - sum(sol.get(t, 0.0) for t in m.blue)
        return Pred(sigmoid(margin / (self.prob_k * self.scale.std)))

    def update(self, m: Match) -> None:
        if m.is_qual:
            ev = self.events[m.event_id]
            d = m.red_score - m.blue_score
            ev.add(m.red, d)
            ev.add(m.blue, -d)
        self.scale.add(m.red_score)
        self.scale.add(m.blue_score)


class WinRate(Model):
    """Baseline: season win rate (smoothed toward 50%)."""

    name = "Win rate"

    def __init__(self, prior_games: float = 2.0, k: float = 4.0):
        self.prior_games, self.k = prior_games, k

    def params(self) -> dict:
        return {"prior_games": self.prior_games, "k": self.k}

    def reset(self, season: Season) -> None:
        super().reset(season)
        self.w: dict[int, float] = defaultdict(float)
        self.g: dict[int, int] = defaultdict(int)

    def _wr(self, t: int) -> float:
        return (self.w[t] + 0.5 * self.prior_games) / (self.g[t] + self.prior_games)

    def predict(self, m: Match) -> Pred:
        r = sum(self._wr(t) for t in m.red) / len(m.red)
        b = sum(self._wr(t) for t in m.blue) / len(m.blue)
        return Pred(sigmoid(self.k * (r - b)))

    def update(self, m: Match) -> None:
        o = m.outcome
        for t in m.red:
            self.w[t] += o
            self.g[t] += 1
        for t in m.blue:
            self.w[t] += 1 - o
            self.g[t] += 1
