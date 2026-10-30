"""EPA (Expected Points Added) for VEX, with an optional skills prior.

Each team has a rating in *points*: its expected contribution to its
alliance's score. Predicted alliance score = sum of the two ratings. After a
match, each team moves toward the observed score by a share of the error.

Differences from plain Elo/TrueSkill:
  * point units, so it predicts scores, not just winners
  * errors are clipped (Huber) so a single blowout or a disconnected robot
    can't wreck a rating; VEX scores are lumpy and non-linear
  * the update step starts large and shrinks as a team plays more
  * win probability is scaled by the current spread of scores, which grows
    as the season's meta develops
  * EPASkills: a team's skills results (solo runs, so a clean individual
    signal) seed its rating and re-anchor it at the start of each event,
    weighted less the more matches the team has played
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

import numpy as np

from ..dataset import Match, Season
from .base import Model, Pred, ScoreScale, SkillsFeed, sigmoid


class EPA(Model):
    name = "EPA"
    has_scores = True

    def __init__(self, k_start: float = 0.5, k_end: float = 0.25, k_tau: float = 8.0,
                 elim_weight: float = 0.5, huber_c: float = 2.0, prob_k: float = 0.6,
                 init_frac: float = 1.0):
        self.k_start, self.k_end, self.k_tau = k_start, k_end, k_tau
        self.elim_weight, self.huber_c, self.prob_k, self.init_frac = elim_weight, huber_c, prob_k, init_frac

    def params(self) -> dict:
        return {k: getattr(self, k) for k in
                ("k_start", "k_end", "k_tau", "elim_weight", "huber_c", "prob_k", "init_frac")}

    def reset(self, season: Season) -> None:
        super().reset(season)
        self.e: dict[int, float] = {}
        self.n: dict[int, int] = defaultdict(int)
        self.scale = ScoreScale()

    # -- hooks for subclasses ------------------------------------------
    def _initial(self, team: int, m: Match) -> float:
        return self.init_frac * self.scale.mean / 2

    def _on_predict(self, m: Match) -> None:
        pass

    # ------------------------------------------------------------------
    def rating(self, team: int) -> Optional[float]:
        return self.e.get(team)

    def _get(self, team: int, m: Match) -> float:
        v = self.e.get(team)
        if v is None:
            v = self.e[team] = self._initial(team, m)
        return v

    def predict(self, m: Match) -> Pred:
        self._on_predict(m)
        red = sum(self._get(t, m) for t in m.red)
        blue = sum(self._get(t, m) for t in m.blue)
        p = sigmoid((red - blue) / (self.prob_k * self.scale.std))
        return Pred(p, red, blue)

    def _k(self, n: int) -> float:
        return self.k_end + (self.k_start - self.k_end) * math.exp(-n / self.k_tau)

    def update(self, m: Match) -> None:
        cap = self.huber_c * self.scale.std
        w = self.elim_weight if m.is_elim else 1.0
        for teams, actual in ((m.red, m.red_score), (m.blue, m.blue_score)):
            pred = sum(self._get(t, m) for t in teams)
            err = max(-cap, min(cap, actual - pred)) if self.scale.n > 20 else actual - pred
            for t in teams:
                self.e[t] += w * self._k(self.n[t]) * err / len(teams)
        for t in m.teams:
            self.n[t] += 1
        self.scale.add(m.red_score)
        self.scale.add(m.blue_score)


class EPASkills(EPA):
    """EPA seeded and re-anchored by skills scores (`skills_map` = (a, b): the
    expected contribution of a team with combined skills s is a + b*s)."""

    name = "EPA + skills prior"

    def __init__(self, skills_map: tuple[float, float] = (0.0, 0.0), anchor_n: float = 6.0,
                 skills_map_rel: bool = True, **kw):
        super().__init__(**kw)
        self.skills_map = skills_map
        self.anchor_n = anchor_n
        self.skills_map_rel = skills_map_rel

    def params(self) -> dict:
        p = super().params()
        p.update(skills_a=round(self.skills_map[0], 4), skills_b=round(self.skills_map[1], 4),
                 anchor_n=self.anchor_n)
        return p

    def reset(self, season: Season) -> None:
        super().reset(season)
        self.feed = SkillsFeed(season)
        self.seen_event: dict[int, int] = {}

    def _prior(self, team: int) -> Optional[float]:
        s = self.feed.get(team)
        if s is None:
            return None
        a, b = self.skills_map
        # Relative form: skills and match scores inflate together over a season,
        # so map skills relative to the field's current skills level.
        if self.skills_map_rel:
            ref = self._skills_ref()
            if ref <= 0:
                return None
            return max(0.0, (self.scale.mean / 2) * (a + b * s / ref))
        return max(0.0, a + b * s)

    def _skills_ref(self) -> float:
        vals = list(self.feed.best.values())
        if not vals:
            return 0.0
        # cache: recompute only when the feed grows
        if getattr(self, "_ref_n", -1) != len(vals) or getattr(self, "_ref_pos", -1) != self.feed.pos:
            self._ref = float(np.median(vals))
            self._ref_n, self._ref_pos = len(vals), self.feed.pos
        return self._ref

    def _initial(self, team: int, m: Match) -> float:
        p = self._prior(team)
        return p if p is not None else super()._initial(team, m)

    def _on_predict(self, m: Match) -> None:
        self.feed.advance(m.ts)
        for t in m.teams:
            if self.seen_event.get(t) == m.event_id:
                continue
            self.seen_event[t] = m.event_id
            if t in self.e:
                p = self._prior(t)
                if p is not None:
                    w = self.anchor_n / (self.anchor_n + self.n[t])
                    self.e[t] = (1 - w) * self.e[t] + w * p


def fit_skills_map(season: Season, until_ts: float, rel: bool = True, lam: float = 1.0) -> tuple[float, float, float, int]:
    """Fit contribution ~ a + b * skills on events that finished before
    `until_ts` (training period only). The target is each team's full-event
    qualification OPR at that event; the feature is the best skills result
    published *before* that event started. Returns (a, b, r2, n)."""
    feed = SkillsFeed(season)
    by_event: dict[int, list[Match]] = defaultdict(list)
    for m in season.matches:
        if m.ts >= until_ts:
            break
        if m.is_qual:
            by_event[m.event_id].append(m)
    events = sorted(by_event, key=lambda e: season.events[e].start)
    xs, ys = [], []
    scale = ScoreScale()
    for eid in events:
        ev = season.events[eid]
        if ev.end + 86400 > until_ts:
            continue
        ms = by_event[eid]
        feed.advance(ev.start)
        idx: dict[int, int] = {}
        rows, b = [], []
        for m in ms:
            for teams, sc in ((m.red, m.red_score), (m.blue, m.blue_score)):
                for t in teams:
                    idx.setdefault(t, len(idx))
                rows.append([idx[t] for t in teams])
                b.append(sc)
        n = len(idx)
        if n < 4 or len(rows) < n:
            continue
        mean = float(np.mean(b)) / 2
        A = np.zeros((len(rows), n))
        for r, ids in enumerate(rows):
            A[r, ids] = 1.0
        x = np.linalg.solve(A.T @ A + lam * np.eye(n), A.T @ np.array(b, float) + lam * mean)
        vals = list(feed.best.values())
        ref = float(np.median(vals)) if vals else 0.0
        for t, i in idx.items():
            s = feed.get(t)
            if s is None or (rel and ref <= 0) or mean <= 0:
                continue
            if rel:
                xs.append(s / ref)
                ys.append(x[i] / mean)
            else:
                xs.append(s)
                ys.append(x[i])
        for sc in b:
            scale.add(sc)
    if len(xs) < 30:
        return (1.0, 0.0, 0.0, len(xs)) if rel else (0.0, 0.0, 0.0, len(xs))
    X = np.column_stack([np.ones(len(xs)), xs])
    coef, *_ = np.linalg.lstsq(X, np.array(ys), rcond=None)
    pred = X @ coef
    ss_res = float(np.sum((np.array(ys) - pred) ** 2))
    ss_tot = float(np.sum((np.array(ys) - np.mean(ys)) ** 2)) or 1.0
    return float(coef[0]), float(coef[1]), 1 - ss_res / ss_tot, len(xs)
