"""Build the whole pipeline on a synthetic season so the site can be tried
without API access:

    python3 -m vexpredict.demo
    python3 -m http.server -d site 8000     # then open http://localhost:8000
"""
from __future__ import annotations

import shutil

from .backtest import evaluate, write_report
from .config import REPORTS_DIR, season_dir
from .dataset import load_season
from .publish import publish
from .models.epa import EPASkills
from .simcheck import run_check
from .tuned import tuned_model
from .simcheck import write_report as write_sim
from .synth import add_upcoming, generate, make_live

SLUG = "demo"


def main() -> None:
    raw = season_dir(SLUG)
    shutil.rmtree(raw, ignore_errors=True)
    info = generate(raw, n_teams=900, n_events=220, n_skills_events=100, seed=7)
    now = make_live(raw, 50000 + 220, 0.5)
    add_upcoming(raw, now, [t for t in info["teams"] if t["grade"] == "High School"])
    season = load_season(SLUG)
    write_report(evaluate(season), REPORTS_DIR / SLUG)
    write_sim(run_check(season, tuned_model(SLUG) or EPASkills(), sims=800), REPORTS_DIR / SLUG)
    print("Published demo to", publish(season, SLUG, now_ts=now))


if __name__ == "__main__":
    main()
