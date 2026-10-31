# Backtest: VEX V5 Robotics Competition 2025-2026: Push Back

110219 matches; hyper-parameters tuned on the first 40%, every number below is from the remaining 66132 matches (predict first, then update; nothing from the future is used).

Accuracy ignores ties. Brier and log loss: lower is better. Score MAE = average miss on each alliance's score.

## All matches (MS+HS) (n = 66111)

| Model | Accuracy | Brier | Log loss | Score MAE |
|---|---|---|---|---|
| TrueSkill | 74.4% | 0.1706 | 0.5207 | n/a |
| Win rate | 72.1% | 0.1854 | 0.5554 | n/a |
| OPR (in-event) | 70.1% | 0.1874 | 0.5564 | 21.8 |
| CCWM (in-event) | 69.0% | 0.1929 | 0.5701 | n/a |
| EPA | 76.1% | 0.1597 | 0.4893 | 20.2 |
| EPA + skills prior | 77.3% | 0.1533 | 0.4715 | 20.0 |
| **EPA + skills, adaptive** | 78.7% | 0.1457 | 0.4526 | 19.1 |

## HS, all matches (n = 37364)

| Model | Accuracy | Brier | Log loss | Score MAE |
|---|---|---|---|---|
| TrueSkill | 74.6% | 0.1698 | 0.5191 | n/a |
| Win rate | 72.3% | 0.1845 | 0.5525 | n/a |
| OPR (in-event) | 69.6% | 0.1901 | 0.5623 | 22.6 |
| CCWM (in-event) | 69.1% | 0.1933 | 0.5704 | n/a |
| EPA | 75.5% | 0.1636 | 0.4993 | 21.1 |
| EPA + skills prior | 76.9% | 0.1559 | 0.4780 | 20.9 |
| **EPA + skills, adaptive** | 78.8% | 0.1461 | 0.4543 | 19.8 |

## HS qualification (n = 31056)

| Model | Accuracy | Brier | Log loss | Score MAE |
|---|---|---|---|---|
| TrueSkill | 73.4% | 0.1768 | 0.5383 | n/a |
| Win rate | 71.2% | 0.1895 | 0.5643 | n/a |
| OPR (in-event) | 67.6% | 0.2003 | 0.5882 | 21.9 |
| CCWM (in-event) | 67.0% | 0.2038 | 0.5964 | n/a |
| EPA | 74.4% | 0.1703 | 0.5179 | 20.4 |
| EPA + skills prior | 75.9% | 0.1619 | 0.4945 | 20.3 |
| **EPA + skills, adaptive** | 77.9% | 0.1517 | 0.4702 | 19.3 |

## HS eliminations (n = 6308)

| Model | Accuracy | Brier | Log loss | Score MAE |
|---|---|---|---|---|
| TrueSkill | 80.5% | 0.1353 | 0.4244 | n/a |
| Win rate | 77.6% | 0.1598 | 0.4943 | n/a |
| OPR (in-event) | 79.3% | 0.1398 | 0.4352 | 26.2 |
| CCWM (in-event) | 79.5% | 0.1416 | 0.4426 | n/a |
| EPA | 81.1% | 0.1307 | 0.4080 | 24.2 |
| EPA + skills prior | 82.0% | 0.1265 | 0.3966 | 23.7 |
| **EPA + skills, adaptive** | 82.8% | 0.1188 | 0.3759 | 22.4 |

## HS cold start (a team with <5 matches) (n = 5308)

| Model | Accuracy | Brier | Log loss | Score MAE |
|---|---|---|---|---|
| TrueSkill | 69.0% | 0.1955 | 0.5808 | n/a |
| Win rate | 66.9% | 0.2072 | 0.6064 | n/a |
| OPR (in-event) | 66.8% | 0.1998 | 0.5870 | 22.1 |
| CCWM (in-event) | 64.9% | 0.2103 | 0.6123 | n/a |
| EPA | 75.9% | 0.1617 | 0.4945 | 20.0 |
| EPA + skills prior | 77.4% | 0.1541 | 0.4753 | 19.9 |
| **EPA + skills, adaptive** | 78.3% | 0.1511 | 0.4672 | 19.4 |

## HS Worlds (n = 2762)

| Model | Accuracy | Brier | Log loss | Score MAE |
|---|---|---|---|---|
| TrueSkill | 69.4% | 0.2053 | 0.6197 | n/a |
| Win rate | 66.3% | 0.2116 | 0.6144 | n/a |
| OPR (in-event) | 66.9% | 0.2102 | 0.6149 | 20.9 |
| CCWM (in-event) | 67.1% | 0.2080 | 0.6075 | n/a |
| EPA | 67.0% | 0.2153 | 0.6361 | 20.3 |
| EPA + skills prior | 70.1% | 0.1987 | 0.5891 | 19.8 |
| **EPA + skills, adaptive** | 72.7% | 0.1857 | 0.5657 | 18.5 |

## Calibration, EPA + skills, adaptive (HS test matches)

When the model says the favorite wins X% of the time, how often does it?

| Predicted | Matches | Predicted avg | Actual |
|---|---|---|---|
| 50%-60% | 5589 | 55.0% | 55.4% |
| 60%-70% | 5753 | 64.9% | 64.7% |
| 70%-80% | 6113 | 75.1% | 74.6% |
| 80%-90% | 7103 | 85.2% | 83.5% |
| 90%-100% | 12806 | 95.9% | 94.0% |

## Tuned parameters

Skills map (fit on training events only): contribution / field average = 0.827 + 0.258 x (skills / field median), R^2 = 0.25, n = 7633.

- **TrueSkill**: {"mu": 25.0, "sigma": 8.333333333333334, "beta": 4.166666666666667, "tau": 0.08333333333333333, "draw_probability": 0.1}, temperature 1.00
- **Win rate**: {"prior_games": 2.0, "k": 4.0}, temperature 0.65
- **OPR (in-event)**: {"lam": 1.0, "prob_k": 1.0}, temperature 0.59
- **CCWM (in-event)**: {"lam": 1.0, "prob_k": 1.0}, temperature 1.15
- **EPA**: {"k_start": 0.3, "k_end": 0.1, "k_tau": 8.0, "elim_weight": 0.66, "huber_c": 100.0, "prob_k": 0.6, "init_frac": 0.6, "margin_w": 0.0, "gap_tau": 30.0}, temperature 0.66
- **EPA + skills prior**: {"k_start": 0.3, "k_end": 0.1, "k_tau": 8.0, "elim_weight": 0.66, "huber_c": 100.0, "prob_k": 0.6, "init_frac": 0.6, "margin_w": 0.0, "gap_tau": 30.0, "skills_a": 0.8269, "skills_b": 0.2584, "anchor_n": 6.0}, temperature 0.61
- **EPA + skills, adaptive**: {"k_start": 0.3, "k_end": 0.1, "k_tau": 8.0, "elim_weight": 0.66, "huber_c": 100.0, "prob_k": 0.6, "init_frac": 0.6, "gap_tau": 30.0, "skills_a": 0.8269, "skills_b": 0.2584, "anchor_n": 6.0, "margin_ws": [0.0, 0.25, 0.5, 0.75, 1.0], "sub_temps": [0.607, 0.6039, 0.6087, 0.6257, 0.6696], "half_life": 300.0}, temperature 0.99
