"""The rating model with the settings a backtest tuned (reports/<season>/metrics.json).

Everything that uses ratings (the site, the simulator check, the analysis)
loads the model from here, so they all use the same model with the same
calibration as the published backtest.
"""
from __future__ import annotations

import json

from .config import REPORTS_DIR
from .models.base import Model
from .models.epa import build_epa

ADAPTIVE = "EPA + skills, adaptive"
FALLBACK = "EPA + skills prior"


def tuned_settings(*slugs: str | None) -> tuple[dict | None, float, str | None, str | None]:
    """(params, temperature, season slug they came from, model name) from the
    first of `slugs` whose backtest has been run, else (None, 1.0, None, None)."""
    for src in slugs:
        if not src:
            continue
        path = REPORTS_DIR / src / "metrics.json"
        if not path.exists():
            continue
        results = json.loads(path.read_text())["results"]
        name = ADAPTIVE if ADAPTIVE in results else FALLBACK
        if name in results:
            r = results[name]
            return dict(r["params"]), float(r.get("temperature", 1.0)), src, name
    return None, 1.0, None, None


def tuned_model(*slugs: str | None) -> Model | None:
    params, temp, _, _ = tuned_settings(*slugs)
    return build_epa(params, temp) if params else None
