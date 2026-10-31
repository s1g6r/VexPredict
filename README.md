# VexPredict

Calibrated match prediction for **VEX V5RC High School**: who wins, by how much,
and how sure we are, with published accuracy against the ratings every other
VEX app uses (TrueSkill, OPR, CCWM). There's also a ranking forecast for every
event (division by division), a match brief for your team, and a live pick list
for alliance selection.

```
fetch ──> data/raw/<season>/events/*.json          (VEX Events API, resumable)
            │
            ├─> backtest  ──> reports/<season>/backtest.md   which model predicts best
            ├─> simcheck  ──> reports/<season>/simcheck.md   are ranking forecasts right
            ├─> analyze   ──> reports/<season>/analysis.md   where the model wins and loses
            └─> publish   ──> site/data/<season>/*.json      what the website reads
                                   │
                                 site/  (static: index.html, app.js, style.css)
```

## How accurate is it? (Push Back, 2025-26, real data)

Every match of the season (110,219 matches, 1,790 events) is replayed in time
order. Each model predicts a match before it sees the result. Settings are tuned
on the first 40% of the season, and every number below comes from the other 60%
(37,364 High School matches, States and Worlds included). Full tables:
[`reports/push-back/backtest.md`](reports/push-back/backtest.md).

| High School matches | VexPredict | TrueSkill | OPR | CCWM |
|---|---|---|---|---|
| Winner right, all | **78.8%** | 74.6% | 69.6% | 69.1% |
| Winner right, Worlds | **72.7%** | 69.4% | 66.9% | 67.1% |
| Winner right, eliminations | **82.8%** | 80.5% | 79.3% | 79.5% |
| Winner right, a team's first 5 matches | **78.3%** | 69.0% | 66.8% | 64.9% |
| Brier score, all (lower is better) | **0.146** | 0.170 | 0.190 | 0.193 |

The probabilities are calibrated: when VexPredict says 65%, the favorite wins
65% of the time (64.7% in the test). At 90%+ it is about two points too sure.

Ranking forecasts, on 813 real divisions:
- **Before the first match:** the simulator's predicted order has a rank correlation of 0.64 with the final rankings. Rating order alone gets 0.52.
- **Halfway through quals:** 0.85 for the simulator, against 0.77 for the current standings.

Details: [`reports/push-back/simcheck.md`](reports/push-back/simcheck.md).

## Quick start

```bash
cd VexPredict
cp ../VexCompare/.env .env                    # same VEX_TOKEN as VexCompare
python3 -m pip install -r requirements.txt    # numpy

python3 -m vexpredict.fetch    --season "Push Back"   # pull a season (resumable, takes a while)
python3 -m vexpredict.backtest --season "Push Back"   # tune + score all models (~10 min)
python3 -m vexpredict.simcheck --season "Push Back"   # check the ranking forecasts
python3 -m vexpredict.analyze  --season "Push Back"   # accuracy by month, experience, event size

python3 -m vexpredict.fetch    --season "Override"    # this season
python3 -m vexpredict.publish  --season "Override" --tune-from "Push Back"

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

Big events (Worlds, Signature events, large States) are split into divisions.
Each division is forecast on its own, since divisions rank and pick alliances
separately. The event page opens on your team's division.

There are no accounts and no login. Scouting notes and pick lists stay in the
browser. To share notes with teammates, use "Export all notes" and then "Import notes".

## Models

| Model | What it is |
|---|---|
| TrueSkill | What vrc-data-analysis, RoboScout and Robot Stats use (default `trueskill` settings) |
| OPR / CCWM (in-event) | What VEX via shows live: least squares over the event's quals so far |
| Win rate | Sanity-check baseline |
| EPA | A rating in points (expected contribution to the alliance score). The update size shrinks with experience and grows again after a long break (rebuilds). The win-probability scale follows the season's score spread |
| EPA + skills prior | Published skills results (solo runs) set a team's starting rating and re-anchor it at each new event. The mapping is fit on training events only |
| **EPA + skills, adaptive** (the site) | Several versions run side by side, from "judge a team by its alliance's score" to "judge it by the winning margin". Each prediction leans on whichever version has predicted recent matches best, using past matches only. In September and October of Push Back, own score predicted best. From December, once fields got strong and scoring was contested, the margin did: at Worlds, 97% of the weight was on the margin version. Predicted scores take the total from the own-score version and the margin from the mix |

Why the adaptive model matters: with own-score updates alone, EPA led TrueSkill
by 3.5 points in January but fell behind it by March and at Worlds. The tuning
period (the first 40% of the season) can't see that change. The online mix
follows it without looking ahead. It is ahead of TrueSkill in every month from
December to May, by 3 to 5 points; the summer months have under 50 matches.
Its score predictions miss by 19.8 points per alliance on average, against
22.6 for in-event OPR.

To be clear about how it was built: the adaptive model was added after the
first real backtest showed this late-season fade. Its settings were still chosen
on the training period only (that period alone already prefers it: training
log loss 0.4852 against 0.4873). But the idea itself came from looking at
test-period results, so the clean out-of-sample check is Override. That
season's accuracy will be published once enough of it has been played.

The **event simulator** plays out the remaining schedule 1,500 times using the
ratings, rating uncertainty, a fitted score-noise model, and V5RC ranking rules:
WP (win 2, tie 1, plus autonomous win points), then AP, then SP. Autonomous
tendencies come from each team's earlier events.

## Data quirks handled

- The API's `scored` flag is false on every match, played or not. A match counts as played if either alliance scored or it has a start time.
- Leagues run for months and don't record match times. Their matches go at the league's end date, never earlier than reality, and are left out of the accuracy numbers.
- Some matches have no start time (2 of 2,982 at Worlds). Each one takes the time of the next timed match in its division, which is never earlier than when it was really played.
- Worlds is detected from the API's event level, because names like "Worlds Scrimmage" also match.
- Practice matches are ignored.

## How it's tested

- **Backtest and simulator check:** described above. Both are rerun from the raw data with one command each.
- **Tests (`python3 -m pytest -q`, 34 of them):**
  - TrueSkill matches the reference `trueskill` package.
  - No model's past predictions change when future matches are added (all seven models, including the adaptive mix).
  - OPR recovers the true strengths on synthetic data.
  - The skills prior beats a field-average start.
  - The simulator stays calibrated and beats the standings baseline.
  - The site shows exactly the pre-match predictions, with the backtest's calibration applied.
  - League and missing-time ordering never puts a match earlier than reality.
  - Divisions are forecast separately.
  - The data pull is checked against a fake API (pagination, HTTP 429, resume, bad token), and the quick event-day refresh picks the right events.
  - Events with leftover unplayed matches don't stay "live" after they end.
  - Every site page loads in a real browser with no errors and no sideways scrolling on a phone, including switching divisions.

## Updating the data (no laptop needed)

The repo's **Backtest** workflow pulls a season on GitHub's machines and
saves the raw API data to a `data/<season>` branch (as a tar.gz). For a finished
season it also runs the backtest and simulator check and commits `reports/<season>/`.
Run it from **Actions → Backtest → Run workflow** (season name, and whether to run the backtest).
The token lives in the repository secret `VEX_TOKEN`, which is already set.

## Live at [stats.2360arachnid.com](https://stats.2360arachnid.com)

Served by GitHub Pages from the **Update predictions** workflow. DNS is a
`CNAME` record `stats` pointing to `s1g6r.github.io` on Cloudflare (DNS only,
grey cloud, so GitHub issues the HTTPS certificate). HTTPS is enforced.

The site re-pulls Override and republishes every 10 minutes from
Friday to Sunday (tournament days) and daily otherwise. It uses the settings the
Push Back backtest tuned.

- **10-minute runs:** these only re-pull events that are on today, and leagues every few hours, so each run stays short.
- **Daily run:** this re-pulls everything unfinished.
- **First run:** this starts from the exported `data/override` branch instead of pulling the whole season.

The API token stays in GitHub's secret store and never reaches the site.

For a private copy, `python3 -m vexpredict.bundle --seasons override` packs the
published site into a few files that can be hosted anywhere.

## Roadmap

1. ~~Backtest harness~~ (real Push Back numbers above)
2. ~~Event simulator~~ (checked on 813 real divisions)
3. ~~Match briefs and scouting tags~~ (tags are per-browser; a shared team notebook needs a small backend)
4. ~~Live pick list~~
5. ~~Divisions at big events~~
6. ~~Go live~~ (stats.2360arachnid.com). Next: forum post, public JSON API (the files in `site/data` already are one)
7. Re-tune on Override once it has enough matches (the game changed; Push Back settings are the starting point)
