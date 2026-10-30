"""Scoring rules for match predictions."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class Row:
    p: float                  # predicted P(red wins)
    y: float                  # 1 red won, 0 blue won, 0.5 tie
    red_pred: Optional[float]
    blue_pred: Optional[float]
    red: int
    blue: int


def summarize(rows: Iterable[Row]) -> dict:
    rows = list(rows)
    n = len(rows)
    if n == 0:
        return {"n": 0}
    decided = [r for r in rows if r.y != 0.5]
    correct = 0.0
    for r in decided:
        if r.p == 0.5:
            correct += 0.5
        elif (r.p > 0.5) == (r.y == 1.0):
            correct += 1
    brier = sum((r.p - r.y) ** 2 for r in rows) / n
    ll = 0.0
    for r in rows:
        p = min(max(r.p, 1e-6), 1 - 1e-6)
        ll -= r.y * math.log(p) + (1 - r.y) * math.log(1 - p)
    out = {
        "n": n,
        "accuracy": correct / len(decided) if decided else float("nan"),
        "brier": brier,
        "log_loss": ll / n,
    }
    scored = [r for r in rows if r.red_pred is not None]
    if scored:
        errs = [abs(r.red_pred - r.red) for r in scored] + [abs(r.blue_pred - r.blue) for r in scored]
        out["score_mae"] = sum(errs) / len(errs)
        merr = [abs((r.red_pred - r.blue_pred) - (r.red - r.blue)) for r in scored]
        out["margin_mae"] = sum(merr) / len(merr)
    return out


def calibration(rows: Iterable[Row], bins: int = 10) -> list[dict]:
    """Reliability table on the 'favorite' side: predicted vs actual win rate."""
    buckets: list[list[Row]] = [[] for _ in range(bins // 2)]
    for r in rows:
        p, y = (r.p, r.y) if r.p >= 0.5 else (1 - r.p, 1 - r.y)
        i = min(int((p - 0.5) / 0.5 * len(buckets)), len(buckets) - 1)
        buckets[i].append(Row(p, y, None, None, 0, 0))
    out = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        lo = 0.5 + i * 0.5 / len(buckets)
        out.append({"range": f"{lo:.0%}-{lo + 0.5 / len(buckets):.0%}", "n": len(b),
                    "predicted": sum(r.p for r in b) / len(b),
                    "actual": sum(r.y for r in b) / len(b)})
    return out
