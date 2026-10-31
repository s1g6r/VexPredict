"""Where does the model win or lose? Breaks test-period accuracy down by month,
experience, event size and confidence, and checks score predictions for bias.

    python3 -m vexpredict.analyze --season "Push Back"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict

import numpy as np

from .backtest import _rows, fit_temperature, run
from .config import REPORTS_DIR, slugify
from .dataset import Season, load_season
from .metrics import summarize
from .models.base import Model
from .models.epa import EPASkills
from .models.trueskill_model import TrueSkill
from .tuned import tuned_model


def _bucket(v: float, edges: list[float], labels: list[str]) -> str:
    for e, l in zip(edges, labels):
        if v < e:
            return l
    return labels[-1]


def analyze(season: Season, model: Model | None = None, train_frac: float = 0.4) -> dict:
    split = season.matches[int(len(season.matches) * train_frac)].ts
    model = model or EPASkills()
    epa = run(model, season)
    ts = run(TrueSkill(), season)
    t_epa = fit_temperature([r for r in epa if r.m.ts < split])
    ev_size = defaultdict(set)
    for m in season.matches:
        ev_size[m.event_id].update(m.teams)

    groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(lambda: ([], [])))
    score_pairs = []
    for re, rt in zip(epa, ts):
        m = re.m
        if m.ts < split or not season.is_hs_match(m):
            continue
        keys = {
            "Month": dt.datetime.fromtimestamp(m.ts, dt.timezone.utc).strftime("%Y-%m"),
            "Fewest season matches among the 4 teams": _bucket(re.min_prior, [1, 5, 10, 20, 40],
                                                               ["0", "1-4", "5-9", "10-19", "20-39", "40+"]),
            "Event size (teams)": _bucket(len(ev_size[m.event_id]), [16, 32, 48, 80],
                                          ["<16", "16-31", "32-47", "48-79", "80+"]),
            "Round": "Qualification" if m.is_qual else "Elimination",
        }
        if re.pred.red is not None:
            gap = abs(re.pred.red - re.pred.blue) / max(1.0, (re.pred.red + re.pred.blue) / 2)
            keys["Predicted margin (share of avg score)"] = _bucket(gap, [0.05, 0.15, 0.3, 0.6],
                                                                   ["<5%", "5-15%", "15-30%", "30-60%", "60%+"])
            score_pairs += [(re.pred.red, m.red_score), (re.pred.blue, m.blue_score)]
        for g, k in keys.items():
            groups[g][k][0].append(re)
            groups[g][k][1].append(rt)

    order = {"Fewest season matches among the 4 teams": ["0", "1-4", "5-9", "10-19", "20-39", "40+"],
             "Event size (teams)": ["<16", "16-31", "32-47", "48-79", "80+"],
             "Predicted margin (share of avg score)": ["<5%", "5-15%", "15-30%", "30-60%", "60%+"]}
    out = {"season": season.name, "model": model.name, "groups": {}}
    for g, buckets in groups.items():
        rows = []
        ranked = order.get(g)
        for k in sorted(buckets, key=lambda k: ranked.index(k) if ranked else k):
            e, t = buckets[k]
            se, st = summarize(_rows(e, t_epa)), summarize(_rows(t))
            rows.append({"bucket": k, "n": se["n"], "epa_acc": se["accuracy"], "ts_acc": st["accuracy"],
                         "epa_brier": se["brier"], "ts_brier": st["brier"]})
        out["groups"][g] = rows
    if score_pairs:
        pred = np.array([p for p, _ in score_pairs])
        act = np.array([a for _, a in score_pairs], float)
        qs = np.quantile(pred, np.linspace(0, 1, 11))
        cal = []
        for lo, hi in zip(qs[:-1], qs[1:]):
            sel = (pred >= lo) & (pred <= hi)
            if sel.sum():
                cal.append({"predicted": float(pred[sel].mean()), "actual": float(act[sel].mean()),
                            "n": int(sel.sum())})
        out["score_calibration"] = cal
        out["score_bias"] = float((act - pred).mean())
    return out


def write_report(res: dict, out_dir) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis.json").write_text(json.dumps(res, indent=2))
    L = [f"# Where the model wins and loses: {res['season']}", "",
         f"High School test-period matches. EPA = {res.get('model', 'EPA')} with the backtest's tuned settings; "
         "TrueSkill uses default settings. Brier: lower is better.", ""]
    for g, rows in res["groups"].items():
        L += [f"## {g}", "", "| Bucket | Matches | EPA acc | TrueSkill acc | EPA Brier | TrueSkill Brier |",
              "|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['bucket']} | {r['n']} | {r['epa_acc']:.1%} | {r['ts_acc']:.1%} | "
                     f"{r['epa_brier']:.4f} | {r['ts_brier']:.4f} |")
        L.append("")
    if "score_calibration" in res:
        L += ["## Score predictions by predicted-score decile", "",
              f"Average actual minus predicted: {res['score_bias']:+.1f} points.", "",
              "| Predicted avg | Actual avg | Alliance scores |", "|---|---|---|"]
        for c in res["score_calibration"]:
            L.append(f"| {c['predicted']:.1f} | {c['actual']:.1f} | {c['n']} |")
    path = out_dir / "analysis.md"
    path.write_text("\n".join(L) + "\n")
    return str(path)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", default="Push Back")
    args = ap.parse_args(argv)
    slug = slugify(args.season)
    res = analyze(load_season(slug), tuned_model(slug))
    print("Report:", write_report(res, REPORTS_DIR / slug))


if __name__ == "__main__":
    main()
