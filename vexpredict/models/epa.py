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
  * margin_w blends each alliance's own score error with the match margin
    error. Push Back is contested (alliances fight over the same goals and
    blocks), so how much an alliance scores depends on who it plays against
  * gap_tau: after a long break (a rebuild between events) a team's update
    step grows again, as if it had played fewer matches
  * predicted scores carry a running offset for scoring the ratings haven't
    absorbed (margin-weighted updates are zero-sum, so the season's rising
    scores would otherwise be missed); it cancels out of win probabilities
  * EPAMix ("adaptive"): several margin_w versions run side by side and are
    weighted by how well each predicted recent matches (past only). Early in
    a season own-score updates predict best; once fields get strong and play
    is contested, margin updates do. The mix follows that without peeking
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
                 init_frac: float = 1.0, margin_w: float = 0.0, gap_tau: float = 0.0, temp: float = 1.0):
        self.temp = temp   # probability temperature fitted by the backtest (not tuned with the rest)
        self.k_start, self.k_end, self.k_tau = k_start, k_end, k_tau
        self.elim_weight, self.huber_c, self.prob_k, self.init_frac = elim_weight, huber_c, prob_k, init_frac
        self.margin_w, self.gap_tau = margin_w, gap_tau

    def params(self) -> dict:
        return {k: getattr(self, k) for k in
                ("k_start", "k_end", "k_tau", "elim_weight", "huber_c", "prob_k", "init_frac", "margin_w", "gap_tau")}

    def reset(self, season: Season) -> None:
        super().reset(season)
        self.e: dict[int, float] = {}
        self.n: dict[int, float] = defaultdict(float)
        self.last: dict[int, float] = {}
        self.bias = 0.0
        self.scale = ScoreScale()

    # -- hooks for subclasses ------------------------------------------
    def _initial(self, team: int, m: Match) -> float:
        return self.init_frac * self.scale.mean / 2

    def _on_predict(self, m: Match) -> None:
        pass

    # ------------------------------------------------------------------
    def rating(self, team: int) -> Optional[float]:
        """Points the team adds to its alliance's score, offset included."""
        v = self.e.get(team)
        return None if v is None else v + self.bias / 2

    def _prob(self, red: float, blue: float) -> float:
        z = (red - blue) / (self.prob_k * self.scale.std)
        return sigmoid(z / self.temp)

    def predict_teams(self, red: tuple, blue: tuple) -> Pred:
        """Prediction from current ratings with no side effects (for matches
        on the schedule that haven't been played)."""
        r = sum(self.e[t] if t in self.e else self._initial(t, None) for t in red)
        b = sum(self.e[t] if t in self.e else self._initial(t, None) for t in blue)
        return Pred(self._prob(r, b), r + self.bias, b + self.bias)

    def _get(self, team: int, m: Match) -> float:
        v = self.e.get(team)
        if v is None:
            v = self.e[team] = self._initial(team, m)
        return v

    def predict(self, m: Match) -> Pred:
        self._on_predict(m)
        red = sum(self._get(t, m) for t in m.red)
        blue = sum(self._get(t, m) for t in m.blue)
        return Pred(self._prob(red, blue), red + self.bias, blue + self.bias)

    def _k(self, n: int) -> float:
        return self.k_end + (self.k_start - self.k_end) * math.exp(-n / self.k_tau)

    def update(self, m: Match) -> None:
        cap = self.huber_c * self.scale.std
        w = self.elim_weight if m.is_elim else 1.0
        if self.gap_tau > 0:
            for t in m.teams:
                gap = (m.ts - self.last.get(t, m.ts)) / 86400
                if gap > 1:
                    self.n[t] *= math.exp(-gap / self.gap_tau)
                self.last[t] = m.ts
        errs = []
        for teams, actual in ((m.red, m.red_score), (m.blue, m.blue_score)):
            errs.append(actual - sum(self._get(t, m) for t in teams))
        margin = errs[0] - errs[1]
        self.bias += 0.002 * ((errs[0] + errs[1]) / 2 - self.bias)
        for teams, err, sign in ((m.red, errs[0], 1), (m.blue, errs[1], -1)):
            err = (1 - self.margin_w) * err + self.margin_w * sign * margin / 2
            if self.scale.n > 20:
                err = max(-cap, min(cap, err))
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


class _MixRatings:
    """Read-only dict view of the mixed ratings (points, offset included)."""

    def __init__(self, mix: "EPAMix"):
        self.mix = mix

    def __contains__(self, t) -> bool:
        return t in self.mix.subs[0].e

    def __getitem__(self, t) -> float:
        return float(sum(w * (s.e[t] + s.bias / 2) for w, s in zip(self.mix.w, self.mix.subs)))

    def get(self, t, default=None):
        return self[t] if t in self else default

    def __iter__(self):
        return iter(self.mix.subs[0].e)

    def __len__(self) -> int:
        return len(self.mix.subs[0].e)

    def keys(self):
        return self.mix.subs[0].e.keys()

    def items(self):
        return ((t, self[t]) for t in self.mix.subs[0].e)


class _MultiFeed:
    def __init__(self, subs):
        self.subs = subs

    def advance(self, ts: float) -> None:
        for s in self.subs:
            s.feed.advance(ts)


class EPAMix(Model):
    """EPA + skills prior, adaptive: an online mixture over margin_w. Each
    version's probabilities are calibrated with a temperature fitted on the
    training period (`sub_temps`); weights follow each version's log loss on
    past matches with exponential forgetting (`half_life`, in matches)."""

    name = "EPA + skills, adaptive"
    has_scores = True

    def __init__(self, margin_ws=(0.0, 0.25, 0.5, 0.75, 1.0), sub_temps=None, half_life: float = 1000.0,
                 temp: float = 1.0, **base):
        base.pop("margin_w", None)
        base.pop("temp", None)
        self.base = base
        self.margin_ws = tuple(margin_ws)
        self.sub_temps = tuple(sub_temps) if sub_temps else (1.0,) * len(self.margin_ws)
        self.half_life, self.temp = half_life, temp

    def params(self) -> dict:
        p = EPASkills(**self.base).params()
        p.pop("margin_w", None)
        p.update(margin_ws=list(self.margin_ws), sub_temps=[round(t, 4) for t in self.sub_temps],
                 half_life=self.half_life)
        return p

    def reset(self, season: Season) -> None:
        super().reset(season)
        self.subs = [EPASkills(**self.base, margin_w=w, temp=t) for w, t in zip(self.margin_ws, self.sub_temps)]
        for s in self.subs:
            s.reset(season)
        self.loss = np.zeros(len(self.subs))
        self.decay = 0.5 ** (1 / self.half_life)
        self.w = np.full(len(self.subs), 1 / len(self.subs))
        self._cache: tuple[int, list[Pred]] | None = None

    # the parts of the EPA interface that publishing uses
    @property
    def scale(self) -> ScoreScale:
        return self.subs[0].scale

    @property
    def prob_k(self) -> float:
        return self.subs[0].prob_k

    @property
    def feed(self) -> _MultiFeed:
        return _MultiFeed(self.subs)

    @property
    def e(self) -> _MixRatings:
        return _MixRatings(self)

    @property
    def weights(self) -> dict[float, float]:
        return {w: round(float(x), 4) for w, x in zip(self.margin_ws, self.w)}

    def rating(self, team: int) -> Optional[float]:
        return self.e.get(team)

    def _initial(self, team: int, m) -> float:
        return float(sum(w * (s._initial(team, m) + s.bias / 2) for w, s in zip(self.w, self.subs)))

    def _combine(self, prs: list[Pred]) -> Pred:
        p = float(np.dot(self.w, [x.p_red for x in prs]))
        if self.temp != 1.0:
            p = min(max(p, 1e-9), 1 - 1e-9)
            p = sigmoid(math.log(p / (1 - p)) / self.temp)
        return Pred(p, float(np.dot(self.w, [x.red for x in prs])), float(np.dot(self.w, [x.blue for x in prs])))

    def predict(self, m: Match) -> Pred:
        prs = [s.predict(m) for s in self.subs]
        self._cache = (m.idx, prs)
        return self._combine(prs)

    def predict_teams(self, red: tuple, blue: tuple) -> Pred:
        return self._combine([s.predict_teams(red, blue) for s in self.subs])

    def update(self, m: Match) -> None:
        prs = self._cache[1] if self._cache and self._cache[0] == m.idx else [s.predict(m) for s in self.subs]
        o = m.outcome
        for i, pr in enumerate(prs):
            q = min(max(pr.p_red, 1e-6), 1 - 1e-6)
            self.loss[i] = self.loss[i] * self.decay - (o * math.log(q) + (1 - o) * math.log(1 - q))
        z = np.exp(-(self.loss - self.loss.min()))
        self.w = z / z.sum()
        for s in self.subs:
            s.update(m)


def build_epa(params: dict, temp: float = 1.0) -> Model:
    """The rating model from saved backtest settings (metrics.json params)."""
    p = dict(params)
    if "skills_a" in p:
        p["skills_map"] = (p.pop("skills_a"), p.pop("skills_b"))
    if "margin_ws" in p:
        return EPAMix(temp=temp, **p)
    return EPASkills(temp=temp, **p)


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
