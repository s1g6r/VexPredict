# Event simulator check: VEX V5 Robotics Competition 2025-2026: Push Back

Model: EPA + skills, adaptive. Rating uncertainty u0 = 0.0 (tuned on training events). Score noise sd = 10.0 + 0.34 x predicted score.

Predicted final qualification rankings vs the real final rankings, on test-period divisions. Spearman: 1 = perfect order, higher is better. Rank MAE: average places off. Top-8 Brier: probability of finishing top 8, lower is better.

## Before the first qualification match (813 divisions, 28492 teams)

| Method | Spearman | Rank MAE | Top-8 Brier |
|---|---|---|---|
| **Simulator** | 0.643 | 7.34 | 0.1114 |
| Current standings | -0.005 | 14.15 | 0.3331 |
| Rating order (no schedule) | 0.516 | - | - |

Calibration of P(top 8):

| Predicted | Teams | Predicted avg | Actual |
|---|---|---|---|
| 0%-20% | 17013 | 6.7% | 5.8% |
| 20%-40% | 5574 | 28.9% | 28.0% |
| 40%-60% | 3079 | 49.0% | 52.1% |
| 60%-80% | 1771 | 69.2% | 73.3% |
| 80%-100% | 1055 | 89.0% | 91.9% |

## After 50% of qualification matches (826 divisions, 28793 teams)

| Method | Spearman | Rank MAE | Top-8 Brier |
|---|---|---|---|
| **Simulator** | 0.846 | 4.89 | 0.0778 |
| Current standings | 0.769 | 6.24 | 0.1445 |
| Rating order (no schedule) | 0.711 | - | - |

Calibration of P(top 8):

| Predicted | Teams | Predicted avg | Actual |
|---|---|---|---|
| 0%-20% | 18957 | 3.0% | 3.2% |
| 20%-40% | 2841 | 29.1% | 29.0% |
| 40%-60% | 2090 | 49.5% | 47.8% |
| 60%-80% | 1926 | 70.0% | 70.1% |
| 80%-100% | 2979 | 92.2% | 92.2% |

