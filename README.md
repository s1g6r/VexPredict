# VexPredict

Calibrated match prediction for **VEX V5RC High School**: who wins, by how much,
and how sure we are, with published accuracy against the ratings every other
VEX app uses (TrueSkill, OPR, CCWM). There's also a ranking forecast for every
event, a match brief for your team, and a live pick list for alliance selection.

```
fetch ──> data/raw/<season>/events/*.json          (VEX Events API, resumable)
            │
            ├─> backtest  ──> reports/<season>/backtest.md   which model predicts best
            ├─> simcheck  ──> reports/<season>/simcheck.md   are ranking forecasts right
            └─> publish   ──> site/data/<season>/*.json      what the website reads
                                   │
                                 site/  (static: index.html, app.js, style.css)
```

## Quick start

```bash
cd VexPredict
cp ../VexCompare/.env .env                    # same VEX_TOKEN as VexCompare
python3 -m pip install -r requirements.txt    # numpy

python3 -m vexpredict.fetch    --season "Push Back"   # pull last season (resumable, takes a while)
python3 -m vexpredict.backtest --season "Push Back"   # tune + score all models
python3 -m vexpredict.simcheck --season "Push Back"   # check the ranking forecasts
python3 -m vexpredict.publish  --season "Push Back"   # build the site data

python3 -m http.server -d site 8000            # open http://localhost:8000
```

No API access? `python3 -m vexpredict.demo` runs the whole pipeline on a
synthetic season (made-up teams, clearly labelled on the site).

The data pull uses only the Python standard library (3.9+), so it runs before
anything is installed. Stop it any time with Ctrl-C and rerun it to continue.

## What the site does

| Page | What it answers |
|---|---|
| Event, Matches | Every match's win probability and predicted score, made before it was played; "called it" or "upset" afterwards |
| Event, Ranking forecast | Each team's expected final rank, odds of being an alliance captain, and odds of finishing first (pre-event, and live during quals) |
| Event, Brief | For your team: each upcoming match, your partner and opponents' ratings, autonomous rates, skills and your scouting notes |
| Event, Pick list | Available teams ranked by rating plus an adjustable weight on autonomous. Tap "Picked" as alliance selection happens and the list reorders |
| Team | Rating through the season, match log, scouting tags and notes |
| Ratings | All HS teams, filterable by region |
| Accuracy | Backtest results vs TrueSkill, OPR and CCWM, plus how good the ranking forecasts are |

There are no accounts and no login. Scouting notes and pick lists stay in the
browser. To share notes with teammates, use "Export all notes" and then "Import notes".

## How it's tested

- **Backtest:** one time-ordered stream of all season matches. Each model predicts and only then sees the result. Settings are tuned on the first 40% of the season; every reported number comes from the remaining 60% (States and Worlds included). Slices: HS overall, quals, elims, cold start, and Worlds.
- **Simulator check:** at the start and halfway point of every division's quals, predicted final rankings are compared with the real ones, against a "current standings" baseline.
- **Tests (`python3 -m pytest -q`, 25 of them):**
  - TrueSkill matches the reference package.
  - No model's past predictions change when future matches are added.
  - OPR recovers the true strengths.
  - The skills prior beats a field-average start.
  - The simulator stays calibrated and beats the standings baseline.
  - Predictions shown on the site are the exact pre-match predictions.
  - The data pull is checked against a fake API (pagination, HTTP 429, resume, bad token).
  - Every site page loads in a real browser with no errors and no sideways scrolling on a phone.

## Models

| Model | What it is |
|---|---|
| TrueSkill | What vrc-data-analysis, RoboScout and Robot Stats use (default `trueskill` settings) |
| OPR / CCWM (in-event) | What VEX via shows live: least squares over the event's quals so far |
| Win rate | Sanity-check baseline |
| **EPA** | A rating in points (expected contribution to the alliance score). Errors are clipped, the update size shrinks with experience, and the win-probability scale follows the season's score spread |
| **EPA + skills prior** | Published skills results (solo runs) set a team's starting rating and re-anchor it at each new event. The mapping is fit on training events only |

The **event simulator** plays out the remaining schedule 1,500 times using the
ratings, rating uncertainty, a fitted score-noise model, and V5RC ranking rules:
WP (win 2, tie 1, plus autonomous win points), then AP, then SP. Autonomous
tendencies come from each team's earlier events.

## Going live at stats.2360arachnid.com

1. Push this repo to GitHub.
2. Add the secret: repo **Settings → Secrets and variables → Actions → New secret**, name `VEX_TOKEN`.
3. **Settings → Pages → Source: GitHub Actions.**
4. Commit `reports/push-back/metrics.json` and `simcheck.json` after running the backtest, so Override predictions use the settings tuned on Push Back.
5. DNS: add a `CNAME` record `stats` pointing to `<github-username>.github.io` (`site/CNAME` already says `stats.2360arachnid.com`).
6. Run **Actions → Update predictions → Run workflow** once.

After that, `.github/workflows/update.yml` re-pulls and republishes every
10 minutes Friday to Sunday (tournament days) and daily otherwise. The API
token stays in GitHub's secret store and never reaches the site.

## Roadmap

1. ~~Backtest harness~~ (real Push Back numbers pending the first pull)
2. ~~Event simulator~~
3. ~~Match briefs and scouting tags~~ (tags are per-browser; a shared team notebook needs a small backend)
4. ~~Live pick list~~
5. Launch: real data, forum post, public JSON API (the files in `site/data` already are one)
