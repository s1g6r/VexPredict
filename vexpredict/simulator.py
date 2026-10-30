"""Monte Carlo simulation of the rest of an event's qualification matches.

For each simulated run:
  1. draw every team's "true" rating for the day from its rating and the
     rating's uncertainty (new teams are uncertain, veterans less so)
  2. play every remaining scheduled match: alliance score = sum of the two
     drawn ratings + score noise (fitted from past prediction errors)
  3. hand out WP (2 win, 1 tie), autonomous win points, autonomous bonus
     points and SP the way V5RC ranking does
  4. rank teams by WP, then AP, then SP

Repeating that a few thousand times gives each team a probability for every
final rank, an expected rank, and its odds of finishing as an alliance captain.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from .dataset import Match, Ranking, Season


@dataclass
class Standing:
    wp: float = 0.0
    ap: float = 0.0
    sp: float = 0.0
    wins: int = 0
    losses: int = 0
    ties: int = 0

    @property
    def played(self) -> int:
        return self.wins + self.losses + self.ties


@dataclass
class ScoreNoise:
    """Score standard deviation as a function of the predicted score."""
    c0: float = 4.0
    c1: float = 0.25

    def sd(self, mu: np.ndarray) -> np.ndarray:
        return self.c0 + self.c1 * np.maximum(mu, 0.0)


@dataclass
class TeamRates:
    """Per-team autonomous tendencies from earlier events (smoothed)."""
    awp: dict[int, float] = field(default_factory=dict)       # P(team earns AWP in a match)
    ap_share: dict[int, float] = field(default_factory=dict)  # P(team's alliance wins the auton bonus)
    ap_value: float = 0.0                                      # AP for winning the auton bonus
    awp_default: float = 0.1


@dataclass
class SimInputs:
    teams: list[int]
    standings: dict[int, Standing]
    remaining: list[tuple[tuple[int, ...], tuple[int, ...]]]
    rating: dict[int, float]
    uncertainty: dict[int, float]
    rates: TeamRates
    noise: ScoreNoise


@dataclass
class SimResult:
    teams: list[int]
    rank_probs: np.ndarray      # [team, rank-1] probability
    mean_rank: np.ndarray
    sims: int

    def p_top(self, k: int) -> np.ndarray:
        return self.rank_probs[:, :k].sum(axis=1)

    def as_dict(self, captains: int) -> dict[int, dict]:
        top = self.p_top(captains)
        first = self.rank_probs[:, 0]
        return {t: {"mean_rank": float(self.mean_rank[i]), "p_captain": float(top[i]),
                    "p_first": float(first[i])} for i, t in enumerate(self.teams)}


def simulate(inp: SimInputs, sims: int = 2000, seed: int = 0) -> SimResult:
    rng = np.random.default_rng(seed)
    teams = list(inp.teams)
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    mean = np.array([inp.rating.get(t, 0.0) for t in teams])
    unc = np.array([inp.uncertainty.get(t, 0.0) for t in teams])
    r = mean[None, :] + unc[None, :] * rng.standard_normal((sims, T))  # drawn ratings

    wp = np.tile([inp.standings.get(t, Standing()).wp for t in teams], (sims, 1)).astype(float)
    ap = np.tile([inp.standings.get(t, Standing()).ap for t in teams], (sims, 1)).astype(float)
    sp = np.tile([inp.standings.get(t, Standing()).sp for t in teams], (sims, 1)).astype(float)

    awp_p = np.array([inp.rates.awp.get(t, inp.rates.awp_default) for t in teams])
    share = np.array([inp.rates.ap_share.get(t, 0.5) for t in teams])

    for red, blue in inp.remaining:
        ri = [idx[t] for t in red if t in idx]
        bi = [idx[t] for t in blue if t in idx]
        if not ri or not bi:
            continue
        mu_r, mu_b = r[:, ri].sum(axis=1), r[:, bi].sum(axis=1)
        sr = np.maximum(0.0, np.rint(mu_r + inp.noise.sd(mu_r) * rng.standard_normal(sims)))
        sb = np.maximum(0.0, np.rint(mu_b + inp.noise.sd(mu_b) * rng.standard_normal(sims)))
        w_r = np.where(sr > sb, 2.0, np.where(sr == sb, 1.0, 0.0))
        loser = np.minimum(sr, sb)
        if inp.rates.ap_value > 0:
            a_r, a_b = share[ri].sum(), share[bi].sum()
            red_auton = rng.random(sims) < a_r / max(a_r + a_b, 1e-9)
        for side, w in ((ri, w_r), (bi, 2.0 - w_r)):
            for i in side:
                wp[:, i] += w + (rng.random(sims) < awp_p[i])
                sp[:, i] += loser
                if inp.rates.ap_value > 0:
                    got = red_auton if side is ri else ~red_auton
                    ap[:, i] += inp.rates.ap_value * got

    # rank: WP desc, AP desc, SP desc, then random
    tie = rng.random((sims, T))
    order = np.lexsort((tie, -sp, -ap, -wp), axis=1)
    ranks = np.empty_like(order)
    rows = np.arange(sims)[:, None]
    ranks[rows, order] = np.arange(T)[None, :]
    probs = np.zeros((T, T))
    for k in range(T):
        probs[:, k] = (ranks == k).mean(axis=0)
    return SimResult(teams, probs, ranks.mean(axis=0) + 1, sims)


# --- inputs from history -----------------------------------------------------

def team_rates(season: Season, before_ts: float, prior_n: float = 8.0) -> TeamRates:
    """AWP rate and auton-bonus share per team from events that ended before
    `before_ts` (final rankings), smoothed toward the league average."""
    tot_awp = tot_played = tot_ap = 0.0
    per: dict[int, list[float]] = {}
    for eid, ranks in season.rankings.items():
        ev = season.events.get(eid)
        if not ev or ev.end + 86400 > before_ts:
            continue
        for r in ranks.values():
            if r.played == 0:
                continue
            p = per.setdefault(r.team_id, [0.0, 0.0, 0.0])
            p[0] += r.awp
            p[1] += r.played
            p[2] += r.ap
            tot_awp += r.awp
            tot_played += r.played
            tot_ap += r.ap
    rates = TeamRates()
    if tot_played == 0:
        return rates
    league_awp = tot_awp / tot_played
    # Exactly one alliance (2 of 4 teams) gets the bonus each match, so the
    # average team earns ap_value/2 AP per match.
    rates.ap_value = 2 * tot_ap / tot_played
    rates.awp_default = league_awp
    for t, (awp, n, apt) in per.items():
        rates.awp[t] = (awp + prior_n * league_awp) / (n + prior_n)
        if rates.ap_value > 0:
            rates.ap_share[t] = (apt / rates.ap_value + prior_n * 0.5) / (n + prior_n)
    return rates


def standings_from_matches(played: Sequence[Match], rates: TeamRates) -> dict[int, Standing]:
    """Current standings from played quals. Match results don't include the
    autonomous outcome, so AWP and AP so far are filled in with each team's
    expected values (exact standings come from the live rankings instead)."""
    st: dict[int, Standing] = {}
    for m in played:
        if not m.is_qual:
            continue
        loser = min(m.red_score, m.blue_score)
        for side, mine, theirs in ((m.red, m.red_score, m.blue_score), (m.blue, m.blue_score, m.red_score)):
            for t in side:
                s = st.setdefault(t, Standing())
                if mine > theirs:
                    s.wins += 1
                    s.wp += 2
                elif mine == theirs:
                    s.ties += 1
                    s.wp += 1
                else:
                    s.losses += 1
                s.wp += rates.awp.get(t, rates.awp_default)
                s.ap += rates.ap_value * rates.ap_share.get(t, 0.5)
                s.sp += loser
    return st


def standings_from_rankings(ranks: dict[int, Ranking]) -> dict[int, Standing]:
    return {t: Standing(r.wp, r.ap, r.sp, r.wins, r.losses, r.ties) for t, r in ranks.items()}


def fit_score_noise(pairs: Sequence[tuple[float, float]]) -> ScoreNoise:
    """Fit sd(score | predicted mu) = c0 + c1*mu from (predicted, actual)
    pairs, using E|err| = sd*sqrt(2/pi) for a normal error."""
    if len(pairs) < 50:
        return ScoreNoise()
    mu = np.array([p for p, _ in pairs])
    err = np.abs(np.array([a for _, a in pairs]) - mu) / math.sqrt(2 / math.pi)
    X = np.column_stack([np.ones_like(mu), np.maximum(mu, 0)])
    c, *_ = np.linalg.lstsq(X, err, rcond=None)
    return ScoreNoise(max(float(c[0]), 1.0), max(float(c[1]), 0.0))


def captain_count(n_teams: int) -> int:
    """Typical number of alliances: 16 at 32+ teams, 8 at 16+, then 4, then 2."""
    for size, k in ((32, 16), (16, 8), (8, 4)):
        if n_teams >= size:
            return k
    return 2
