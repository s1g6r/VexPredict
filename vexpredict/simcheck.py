"""Validate the event simulator on a past season.

    python3 -m vexpredict.simcheck --season "Push Back"

For every division with final rankings, at two moments (before the first
qualification match, and halfway through quals), the simulator predicts final
rankings using only what was known then. Those predictions are compared with
the real final rankings, against two baselines:
  * current standings: rank teams by their record so far
  * rating order: rank teams by rating alone, without simulating the schedule
Tuning (rating uncertainty) uses training-period events only.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .config import REPORTS_DIR, slugify
from .dataset import Match, Season, load_season
from .models.epa import EPA, EPASkills
from .simulator import (ScoreNoise, SimInputs, fit_score_noise, simulate, standings_from_matches,
                        team_rates)

CUTS = (0.0, 0.5)
TOP_K = 8


@dataclass
class Snapshot:
    event_id: int
    division_id: int
    cut: float
    start_ts: float
    teams: list[int]
    rating: dict[int, float]
    played_n: dict[int, int]
    score_std: float
    played: list[Match]
    remaining: list[tuple[tuple[int, ...], tuple[int, ...]]]


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return float("nan")
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def collect(season: Season, model: EPA, min_teams: int = 12) -> tuple[list[Snapshot], list[tuple[float, float]]]:
    """Run the model through the season once, snapshotting ratings at each cut.
    Also returns (predicted, actual) alliance scores for fitting score noise."""
    divs: dict[tuple[int, int], list[Match]] = defaultdict(list)
    for m in season.matches:
        if m.is_qual:
            divs[(m.event_id, m.division_id)].append(m)
    hooks: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    for (eid, did), qs in divs.items():
        ranks = season.rankings.get(eid)
        if not ranks:
            continue
        teams = [t for t, r in ranks.items() if r.division_id in (did, 0)]
        if len(teams) < min_teams or len(qs) < len(teams) // 2:
            continue
        for c in CUTS:
            hooks[qs[min(int(c * len(qs)), len(qs) - 1)].idx].append((eid, did, c))

    model.reset(season)
    played_n: dict[int, int] = defaultdict(int)
    snaps: list[Snapshot] = []
    pairs: list[tuple[float, float, float]] = []
    for m in season.matches:
        for eid, did, c in hooks.get(m.idx, []):
            if hasattr(model, "feed"):
                model.feed.advance(m.ts)
            ranks = season.rankings[eid]
            teams = [t for t, r in ranks.items() if r.division_id in (did, 0)]
            qs = divs[(eid, did)]
            k = next(i for i, q in enumerate(qs) if q.idx == m.idx)
            rating = {t: (model.e[t] if t in model.e else model._initial(t, m)) for t in teams}
            snaps.append(Snapshot(eid, did, c, m.ts, teams, rating, {t: played_n[t] for t in teams},
                                  model.scale.std, qs[:k], [(q.red, q.blue) for q in qs[k:]]))
        p = model.predict(m)
        pairs.append((m.ts, p.red, m.red_score))
        pairs.append((m.ts, p.blue, m.blue_score))
        model.update(m)
        for t in m.teams:
            played_n[t] += 1
    return snaps, pairs


def evaluate_snap(season: Season, s: Snapshot, u0: float, noise: ScoreNoise, sims: int, seed: int) -> dict:
    seed = seed * 1_000_003 + s.event_id * 101 + s.division_id + int(s.cut * 10)
    rates = team_rates(season, season.events[s.event_id].start)
    unc = {t: u0 * s.score_std / math.sqrt(1 + s.played_n[t] / 4) for t in s.teams}
    st = standings_from_matches(s.played, rates)
    res = simulate(SimInputs(s.teams, st, s.remaining, s.rating, unc, rates, noise), sims=sims, seed=seed)
    ranks = season.rankings[s.event_id]
    true_rank = np.array([ranks[t].rank for t in s.teams], float)
    # a division's ranks are 1..N within the division; renumber to be safe
    true_rank = np.argsort(np.argsort(true_rank)).astype(float) + 1
    k = min(TOP_K, len(s.teams) // 2)
    y = (true_rank <= k).astype(float)
    p_top = res.p_top(k)

    # Baseline 1: current standings (WP per match, then AP, SP); at cut 0 everyone ties.
    rng = np.random.default_rng(seed)
    cur = np.array([[st.get(t).wp / max(st.get(t).played, 1) if t in st else 0.0,
                     st.get(t).ap if t in st else 0.0, st.get(t).sp if t in st else 0.0] for t in s.teams])
    cur_order = np.lexsort((rng.random(len(s.teams)), -cur[:, 2], -cur[:, 1], -cur[:, 0]))
    cur_rank = np.empty(len(s.teams))
    cur_rank[cur_order] = np.arange(len(s.teams)) + 1
    # Baseline 2: rating order only.
    rating_rank = np.argsort(np.argsort(-np.array([s.rating[t] for t in s.teams]))) + 1.0
    return {
        "cut": s.cut, "n": len(s.teams),
        "spearman_sim": _spearman(res.mean_rank, true_rank),
        "spearman_standings": _spearman(cur_rank, true_rank),
        "spearman_rating": _spearman(rating_rank, true_rank),
        "brier_sim": float(np.mean((p_top - y) ** 2)),
        "brier_standings": float(np.mean(((cur_rank <= k).astype(float) - y) ** 2)),
        "mae_rank_sim": float(np.mean(np.abs(res.mean_rank - true_rank))),
        "mae_rank_standings": float(np.mean(np.abs(cur_rank - true_rank))),
        "p_top": p_top.tolist(), "y": y.tolist(),
    }


def _agg(rows: list[dict]) -> dict:
    if not rows:
        return {"divisions": 0}
    w = np.array([r["n"] for r in rows], float)
    out = {"divisions": len(rows), "teams": int(w.sum())}
    for key in ("spearman_sim", "spearman_standings", "spearman_rating", "brier_sim", "brier_standings",
                "mae_rank_sim", "mae_rank_standings"):
        v = np.array([r[key] for r in rows], float)
        ok = ~np.isnan(v)
        out[key] = float(np.average(v[ok], weights=w[ok])) if ok.any() else float("nan")
    p = np.concatenate([r["p_top"] for r in rows])
    y = np.concatenate([r["y"] for r in rows])
    cal = []
    for lo in np.arange(0, 1, 0.2):
        sel = (p >= lo) & (p < lo + 0.2 + (1e-9 if lo >= 0.8 else 0))
        if sel.sum():
            cal.append({"range": f"{lo:.0%}-{lo + 0.2:.0%}", "n": int(sel.sum()),
                        "predicted": float(p[sel].mean()), "actual": float(y[sel].mean())})
    out["calibration_top8"] = cal
    return out


def run_check(season: Season, model: EPA, train_frac: float = 0.4, sims: int = 1000,
              log=print) -> dict:
    split = season.matches[int(len(season.matches) * train_frac)].ts
    snaps, pairs = collect(season, model)
    noise = fit_score_noise([(p, a) for ts, p, a in pairs if ts < split])
    log(f"  {len(snaps)} snapshots; score noise sd = {noise.c0:.1f} + {noise.c1:.2f} x predicted")
    train = [s for s in snaps if s.start_ts < split]
    test = [s for s in snaps if s.start_ts >= split]
    best_u, best = 0.0, math.inf
    for u0 in (0.0, 0.1, 0.2, 0.3, 0.45, 0.6):
        b = np.mean([evaluate_snap(season, s, u0, noise, max(200, sims // 4), 1)["brier_sim"]
                     for s in train]) if train else 0.0
        log(f"    rating uncertainty u0={u0}: train top-{TOP_K} brier {b:.4f}")
        if b < best:
            best_u, best = u0, b
    rows = [evaluate_snap(season, s, best_u, noise, sims, 2) for s in test]
    res = {"season": season.name, "u0": best_u, "noise": {"c0": noise.c0, "c1": noise.c1},
           "model": model.name, "params": model.params()}
    for c in CUTS:
        res[f"cut_{int(c * 100)}"] = _agg([r for r in rows if r["cut"] == c])
    return res


def write_report(res: dict, out_dir) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "simcheck.json").write_text(json.dumps(res, indent=2))
    L = [f"# Event simulator check: {res['season']}", "",
         f"Model: {res['model']}. Rating uncertainty u0 = {res['u0']} (tuned on training events). "
         f"Score noise sd = {res['noise']['c0']:.1f} + {res['noise']['c1']:.2f} x predicted score.", "",
         "Predicted final qualification rankings vs the real final rankings, on test-period divisions. "
         "Spearman: 1 = perfect order, higher is better. Rank MAE: average places off. "
         f"Top-{TOP_K} Brier: probability of finishing top {TOP_K}, lower is better.", ""]
    for c in CUTS:
        a = res[f"cut_{int(c * 100)}"]
        when = "Before the first qualification match" if c == 0 else f"After {c:.0%} of qualification matches"
        L += [f"## {when} ({a.get('divisions', 0)} divisions, {a.get('teams', 0)} teams)", ""]
        if not a.get("divisions"):
            L += ["No divisions.", ""]
            continue
        L += ["| Method | Spearman | Rank MAE | Top-8 Brier |", "|---|---|---|---|",
              f"| **Simulator** | {a['spearman_sim']:.3f} | {a['mae_rank_sim']:.2f} | {a['brier_sim']:.4f} |",
              f"| Current standings | {a['spearman_standings']:.3f} | {a['mae_rank_standings']:.2f} | "
              f"{a['brier_standings']:.4f} |",
              f"| Rating order (no schedule) | {a['spearman_rating']:.3f} | - | - |", "",
              "Calibration of P(top 8):", "", "| Predicted | Teams | Predicted avg | Actual |", "|---|---|---|---|"]
        for r in a["calibration_top8"]:
            L.append(f"| {r['range']} | {r['n']} | {r['predicted']:.1%} | {r['actual']:.1%} |")
        L.append("")
    path = out_dir / "simcheck.md"
    path.write_text("\n".join(L) + "\n")
    return str(path)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", default="Push Back")
    ap.add_argument("--sims", type=int, default=1000)
    args = ap.parse_args(argv)
    slug = slugify(args.season)
    season = load_season(slug)
    params = _tuned_params(slug)
    model = EPASkills(**params) if params else EPA()
    res = run_check(season, model, sims=args.sims)
    print("Report:", write_report(res, REPORTS_DIR / slug))


def _tuned_params(slug: str) -> dict:
    """Reuse the backtest's tuned EPA + skills parameters if the backtest ran."""
    path = REPORTS_DIR / slug / "metrics.json"
    if not path.exists():
        return {}
    p = dict(json.loads(path.read_text())["results"]["EPA + skills prior"]["params"])
    a, b = p.pop("skills_a"), p.pop("skills_b")
    p["skills_map"] = (a, b)
    return p


if __name__ == "__main__":
    main()
