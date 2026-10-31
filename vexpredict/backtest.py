"""Backtest every model on a past season and write a report.

    python3 -m vexpredict.backtest --season "Push Back"

Protocol (no peeking at the future):
  * all matches of the season form one time-ordered stream
  * for each match: model.predict() first, record it, then model.update()
  * hyper-parameters are tuned only on the first part of the season
    (default 40% of matches); every reported number is from the remainder,
    which includes state championships and Worlds
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import REPORTS_DIR, slugify
from .dataset import Match, Season, load_season
from .metrics import Row, calibration, summarize
from .models.base import Model, Pred, sigmoid
from .models.epa import EPA, EPAMix, EPASkills, fit_skills_map
from .models.opr import EventCCWM, EventOPR, WinRate
from .models.trueskill_model import TrueSkill

COLD_MATCHES = 5


@dataclass
class Record:
    m: Match
    pred: Pred
    min_prior: int   # fewest season matches any of the 4 teams had played before this one


def run(model: Model, season: Season, until_ts: float = math.inf) -> list[Record]:
    model.reset(season)
    played: dict[int, int] = defaultdict(int)
    out = []
    for m in season.matches:
        if m.ts >= until_ts:
            break
        p = model.predict(m)
        if m.dated:
            out.append(Record(m, p, min(played[t] for t in m.teams)))
        model.update(m)
        for t in m.teams:
            played[t] += 1
    return out


def _rows(recs: list[Record], temp: float = 1.0) -> list[Row]:
    rows = []
    for r in recs:
        p = r.pred.p_red
        if temp != 1.0:
            p = sigmoid(_logit(p) / temp)
        rows.append(Row(p, r.m.outcome, r.pred.red, r.pred.blue, r.m.red_score, r.m.blue_score))
    return rows


def _logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def fit_temperature(recs: list[Record]) -> float:
    """1-D golden-section search for the temperature minimising log loss."""
    lo, hi = math.log(0.2), math.log(5.0)
    f = lambda lt: summarize(_rows(recs, math.exp(lt)))["log_loss"]  # noqa: E731
    g = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(30):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = f(d)
    return math.exp((a + b) / 2)


def tune(factory: Callable[..., Model], grid: dict[str, list], season: Season, until_ts: float,
         base: dict | None = None, passes: int = 2, log: Callable[[str], None] = print) -> tuple[dict, float]:
    """Coordinate descent over `grid`, scoring each candidate by training-period
    log loss after fitting its probability temperature."""
    params = dict(base or {})
    for k, vals in grid.items():
        params.setdefault(k, vals[len(vals) // 2])
    cache: dict[tuple, float] = {}

    def score(p: dict) -> float:
        key = tuple(sorted(p.items()))
        if key not in cache:
            recs = run(factory(**p), season, until_ts)
            t = fit_temperature(recs)
            cache[key] = summarize(_rows(recs, t))["log_loss"]
        return cache[key]

    best = score(params)
    for _ in range(passes):
        improved = False
        for k, vals in grid.items():
            for v in vals:
                cand = dict(params, **{k: v})
                s = score(cand)
                if s < best - 1e-6:
                    best, params, improved = s, cand, True
            log(f"    {k} = {params[k]}  (train log loss {best:.4f})")
        if not improved:
            break
    return params, best


EPA_GRID = {
    "k_start": [0.3, 0.45, 0.6, 0.8, 1.0],
    "k_end": [0.04, 0.07, 0.1, 0.15, 0.22, 0.3],
    "k_tau": [2.0, 4.0, 8.0, 16.0, 32.0],
    "huber_c": [1.0, 1.5, 2.5, 100.0],
    "elim_weight": [0.0, 0.33, 0.66, 1.0],
    "init_frac": [0.6, 0.8, 1.0, 1.2],
    "gap_tau": [0.0, 30.0],
}
MARGIN_WS = (0.0, 0.25, 0.5, 0.75, 1.0)
from .tuned import ADAPTIVE  # noqa: E402  (the model the site uses)


def evaluate(season: Season, train_frac: float = 0.4, quick: bool = False,
             log: Callable[[str], None] = print) -> dict:
    ms = season.matches
    if len(ms) < 50:
        raise SystemExit(f"Only {len(ms)} matches loaded; need a full season.")
    split = ms[int(len(ms) * train_frac)].ts
    log(f"{len(ms)} matches, {len(season.teams)} teams, {len(season.events)} events; "
        f"tuning on the first {train_frac:.0%} ({sum(m.ts < split for m in ms)} matches)")

    specs: list[tuple[str, Callable[..., Model], dict, bool]] = []
    # (name, factory, params, temperature-calibrate?)
    specs.append(("TrueSkill", TrueSkill, {}, False))
    specs.append(("Win rate", WinRate, {"prior_games": 2.0}, True))
    specs.append(("OPR (in-event)", EventOPR, {"lam": 1.0}, True))
    specs.append(("CCWM (in-event)", EventCCWM, {"lam": 1.0}, True))

    t0 = time.time()
    if quick:
        epa_params = {}
    else:
        log("  tuning EPA ...")
        epa_params, _ = tune(EPA, EPA_GRID, season, split, log=log)
    specs.append(("EPA", EPA, epa_params, True))

    a, b, r2, n_fit = fit_skills_map(season, split)
    log(f"  skills map (training events only): contribution/avg = {a:.3f} + {b:.3f} * skills/median "
        f"(R^2 {r2:.2f}, n={n_fit})")
    sk_base = dict(epa_params, skills_map=(a, b))
    if quick:
        sk_params = sk_base
    else:
        log("  tuning EPA + skills prior ...")
        sk_params, _ = tune(EPASkills, {"anchor_n": [0.0, 2.0, 6.0, 15.0, 40.0]}, season, split, base=sk_base,
                            passes=1, log=log)
    specs.append(("EPA + skills prior", EPASkills, sk_params, True))

    # Adaptive: the margin_w versions side by side, each calibrated on the
    # training period, weighted online by recent log loss.
    sub_temps = []
    for w in MARGIN_WS:
        p = dict(sk_params, margin_w=w)
        sub_temps.append(1.0 if quick else fit_temperature(run(EPASkills(**p), season, until_ts=split)))
    mix_base = dict(sk_params, margin_ws=MARGIN_WS, sub_temps=tuple(sub_temps))
    if quick:
        mix_params = dict(mix_base, half_life=1000.0)
    else:
        log(f"  tuning {ADAPTIVE} (version temperatures {[round(t, 2) for t in sub_temps]}) ...")
        mix_params, _ = tune(EPAMix, {"half_life": [300.0, 1000.0, 3000.0, 10000.0]}, season, split,
                             base=mix_base, passes=1, log=log)
    specs.append((ADAPTIVE, EPAMix, mix_params, True))
    log(f"  tuning done in {time.time() - t0:.0f}s")

    results = {}
    for name, factory, params, calibrate in specs:
        t1 = time.time()
        model = factory(**params)
        recs = run(model, season)
        train = [r for r in recs if r.m.ts < split]
        temp = fit_temperature(train) if calibrate else 1.0
        test = [r for r in recs if r.m.ts >= split]
        results[name] = {"params": _jsonable(model.params()), "temperature": temp,
                         **({"final_weights": {str(k): v for k, v in model.weights.items()}} if isinstance(model, EPAMix) else {}),
                         "slices": _slices(season, test, temp),
                         "calibration": calibration(_rows([r for r in test if season.is_hs_match(r.m)], temp))}
        hs = results[name]["slices"]["HS, all matches"]
        log(f"  {name:22s} HS accuracy {hs.get('accuracy', float('nan')):.3f}  "
            f"brier {hs.get('brier', float('nan')):.4f}  ({time.time() - t1:.0f}s)")
    return {"season": season.name, "matches": len(ms), "train_frac": train_frac,
            "test_matches": sum(m.ts >= split for m in ms), "skills_fit": {"a": a, "b": b, "r2": r2, "n": n_fit},
            "results": results}


def _slices(season: Season, test: list[Record], temp: float) -> dict:
    hs = [r for r in test if season.is_hs_match(r.m)]
    worlds = [r for r in hs if season.events[r.m.event_id].is_worlds]
    defs = {
        "All matches (MS+HS)": test,
        "HS, all matches": hs,
        "HS qualification": [r for r in hs if r.m.is_qual],
        "HS eliminations": [r for r in hs if r.m.is_elim],
        f"HS cold start (a team with <{COLD_MATCHES} matches)": [r for r in hs if r.min_prior < COLD_MATCHES],
        "HS Worlds": worlds,
    }
    return {k: summarize(_rows(v, temp)) for k, v in defs.items()}


def _jsonable(d: dict) -> dict:
    return {k: (list(v) if isinstance(v, tuple) else v) for k, v in d.items()}


def write_report(res: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(res, indent=2))
    names = list(res["results"])
    slices = list(next(iter(res["results"].values()))["slices"])
    L = [f"# Backtest: {res['season']}", "",
         f"{res['matches']} matches; hyper-parameters tuned on the first {res['train_frac']:.0%}, "
         f"every number below is from the remaining {res['test_matches']} matches "
         "(predict first, then update; nothing from the future is used).", "",
         "Accuracy ignores ties. Brier and log loss: lower is better. "
         "Score MAE = average miss on each alliance's score.", ""]
    for s in slices:
        n = res["results"][names[0]]["slices"][s].get("n", 0)
        L += [f"## {s} (n = {n})", "", "| Model | Accuracy | Brier | Log loss | Score MAE |", "|---|---|---|---|---|"]
        rows = []
        for name in names:
            m = res["results"][name]["slices"][s]
            if not m.get("n"):
                continue
            rows.append((m.get("brier", 9), name, m))
        best = min(rows)[1] if rows else None
        for _, name, m in rows:
            mae = f"{m['score_mae']:.1f}" if "score_mae" in m else "n/a"
            label = f"**{name}**" if name == best else name
            L.append(f"| {label} | {m['accuracy']:.1%} | {m['brier']:.4f} | {m['log_loss']:.4f} | {mae} |")
        L.append("")
    best_name = min(names, key=lambda n: res["results"][n]["slices"]["HS, all matches"].get("brier", 9))
    L += [f"## Calibration, {best_name} (HS test matches)", "",
          "When the model says the favorite wins X% of the time, how often does it?", "",
          "| Predicted | Matches | Predicted avg | Actual |", "|---|---|---|---|"]
    for c in res["results"][best_name]["calibration"]:
        L.append(f"| {c['range']} | {c['n']} | {c['predicted']:.1%} | {c['actual']:.1%} |")
    sf = res["skills_fit"]
    L += ["", "## Tuned parameters", "",
          f"Skills map (fit on training events only): contribution / field average = "
          f"{sf['a']:.3f} + {sf['b']:.3f} x (skills / field median), R^2 = {sf['r2']:.2f}, n = {sf['n']}.", ""]
    for name in names:
        r = res["results"][name]
        L.append(f"- **{name}**: {json.dumps(r['params'])}, temperature {r['temperature']:.2f}")
    path = out_dir / "backtest.md"
    path.write_text("\n".join(L) + "\n")
    return path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", default="Push Back")
    ap.add_argument("--train-frac", type=float, default=0.4)
    ap.add_argument("--quick", action="store_true", help="skip hyper-parameter tuning")
    args = ap.parse_args(argv)
    slug = slugify(args.season)
    season = load_season(slug)
    res = evaluate(season, args.train_frac, args.quick)
    path = write_report(res, REPORTS_DIR / slug)
    print(f"\nReport: {path}")


if __name__ == "__main__":
    main()
