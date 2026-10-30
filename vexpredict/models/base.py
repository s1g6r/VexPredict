"""Shared model interface and helpers.

Every model sees matches strictly in time order and must call nothing that
looks at the future: the backtest asks for `predict(m)` and only afterwards
calls `update(m)` with the result.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Optional

from ..dataset import Match, Season


@dataclass
class Pred:
    p_red: float                       # probability red wins (ties count as half)
    red: Optional[float] = None        # predicted red alliance score, if the model has one
    blue: Optional[float] = None


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


class ScoreScale:
    """Running mean / std of alliance scores (EMA) so win probabilities adapt
    as scoring grows over the season."""

    def __init__(self, alpha: float = 0.002, mean: float = 0.0, var: float = 0.0):
        self.alpha = alpha
        self.mean = mean
        self.var = var
        self.n = 0

    def add(self, score: float) -> None:
        self.n += 1
        a = max(self.alpha, 1.0 / self.n)  # exact mean/var for the first matches
        d = score - self.mean
        self.mean += a * d
        self.var = (1 - a) * (self.var + a * d * d)

    @property
    def std(self) -> float:
        return math.sqrt(self.var) if self.var > 1e-9 else 1.0


class SkillsFeed:
    """Best same-event combined skills score per team, revealed only once that
    event's results are public (the day after it ends)."""

    def __init__(self, season: Season):
        self.items = season.skills  # sorted by available_ts
        self.keys = [s.available_ts for s in self.items]
        self.pos = 0
        self.best: dict[int, int] = {}

    def advance(self, ts: float) -> None:
        end = bisect.bisect_right(self.keys, ts, lo=self.pos)
        for s in self.items[self.pos:end]:
            if s.combined > self.best.get(s.team_id, -1):
                self.best[s.team_id] = s.combined
        self.pos = end

    def get(self, team_id: int) -> Optional[int]:
        return self.best.get(team_id)


class Model:
    name = "base"
    has_scores = False

    def reset(self, season: Season) -> None:
        self.season = season

    def predict(self, m: Match) -> Pred:  # pragma: no cover - interface
        raise NotImplementedError

    def update(self, m: Match) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def params(self) -> dict:
        return {}
