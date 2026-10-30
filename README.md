# VexPredict

Calibrated match prediction for **VEX V5RC High School**: who wins, by how much,
and how sure we are, with published accuracy against the ratings every other
VEX app uses (TrueSkill, OPR, CCWM).

Status: **step 1 of 5, the backtest.** Before any UI exists, the rating has to
be shown to beat the community baselines on a real past season.

## Setup

```bash
cd VexPredict
cp ../VexCompare/.env .env          # same VEX_TOKEN as VexCompare
python3 -m pip install -r requirements.txt   # numpy (only needed for the backtest)
```

The data pull uses only the Python standard library, so it works before
installing anything.

## 1. Pull a season

```bash
python3 -m vexpredict.fetch --season "Push Back"
```

This saves every Push Back event (teams, skills, all matches) to
`data/raw/push-back/events/<id>.json`. It's resumable: stop it with Ctrl-C and
run the same command again to continue. Finished events are never downloaded
twice. A full season is a few thousand events, so let it run.

## 2. Backtest

```bash
python3 -m vexpredict.backtest --season "Push Back"
```

This writes `reports/push-back/backtest.md` and `metrics.json`.

How the backtest works (no peeking at the future):

- all matches of the season form a single time-ordered stream
- for each match, every model predicts first and only then sees the result
- hyper-parameters are tuned on the first 40% of the season; every number in
  the report comes from the remaining 60% (state championships and Worlds included)
- skills results only count once they're published (the day after their event ends)

Reported slices: HS overall, HS quals, HS elims, HS cold start (a team with
fewer than 5 matches), and HS Worlds. Metrics: accuracy, Brier score, log loss,
score MAE, and a calibration table.

## Models

| Model | What it is |
|---|---|
| TrueSkill | What vrc-data-analysis, RoboScout and Robot Stats use. Default `trueskill` parameters; verified against that package in the tests. |
| OPR / CCWM (in-event) | What VEX via shows live: least squares over the qualification matches already played at the current event. |
| Win rate | Sanity-check baseline. |
| **EPA** | A rating in points (expected contribution to the alliance score). Errors are clipped so blowouts don't wreck ratings, the update size shrinks as a team plays more, and win probability scales with the current spread of scores. |
| **EPA + skills prior** | EPA where a team's published skills results (solo runs, so a clean individual signal) set its starting rating and re-anchor it at each new event. The skills-to-points mapping is fit on training events only. |

## Tests

```bash
python3 -m pip install pytest trueskill
python3 -m pytest -q
```

The tests generate a synthetic season with known team strengths in the same
format the API returns, then check:

- TrueSkill matches the reference package
- no model's past predictions change when future matches are added (leakage test)
- in-event OPR recovers the true strengths
- the skills prior beats a field-average start
- the full backtest and report run end to end

## Roadmap

1. Backtest on Push Back (this step)
2. Event simulator: predicted final rankings, alliance-captain odds, and a win probability for every match
3. Match briefs plus shared scouting tags
4. Live alliance-selection pick list
5. Public launch at `stats.2360arachnid.com`: an accuracy page and a JSON API
