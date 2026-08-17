# LTF structural-TP parameter grid search — XAUUSD / choch_only / m15

Generated 2026-08-17 11:19:16 by `scripts/backtest/grid_search_structural_tp.py`. Exploratory only — not written to `ltf_trigger_signals`/`backtest_runs`.

## Split

- Full range: 2026-01-27 00:30:43 → 2026-08-15 00:30:43
- Train (60%): 2026-01-27 00:30:43 → 2026-05-27 00:30:43  (floor=66)
- Validation (20%): 2026-05-27 00:30:43 → 2026-07-06 00:30:43  (floor=22)
- Test (20%): 2026-07-06 00:30:43 → 2026-08-15 00:30:43  (floor=22)

Grid size: 81 combinations (fraction=[0.7, 0.85, 1.0] × min_risk=[0.3, 0.5, 0.7] × max_stop=[1.5, 2.0, 2.5] × confirm_window=[10, 20, 30])

## Top 10 by train expectancy (floor-clearing combos only)

| fraction | min_risk | max_stop | confirm_window | train_n | train_expectancy | train_winrate | train_dd |
|---|---|---|---|---|---|---|---|
| 1.0 | 0.3 | 2.5 | 30.0 | 307.0 | 0.1498 | 0.7622 | 7.2985 |
| 1.0 | 0.3 | 2.0 | 30.0 | 317.0 | 0.1460 | 0.7571 | 6.0428 |
| 0.7 | 0.3 | 2.0 | 20.0 | 309.0 | 0.1358 | 0.8414 | 3.0000 |
| 1.0 | 0.3 | 1.5 | 30.0 | 342.0 | 0.1356 | 0.7281 | 10.3251 |
| 0.85 | 0.3 | 2.5 | 30.0 | 333.0 | 0.1337 | 0.7898 | 6.1291 |
| 0.7 | 0.3 | 2.5 | 30.0 | 370.0 | 0.1331 | 0.8243 | 7.9503 |
| 1.0 | 0.3 | 1.5 | 20.0 | 286.0 | 0.1323 | 0.7483 | 5.9621 |
| 0.7 | 0.3 | 2.0 | 30.0 | 379.0 | 0.1322 | 0.8206 | 7.2685 |
| 0.85 | 0.3 | 2.0 | 30.0 | 345.0 | 0.1299 | 0.7855 | 5.7007 |
| 0.7 | 0.3 | 1.5 | 20.0 | 325.0 | 0.1277 | 0.8154 | 4.4423 |

## Current production defaults

| 0.85 | 0.5 | 1.5 | 20.0 | 294.0 | 0.0901 | 0.7823 | 4.3975 |

Rank by train expectancy among 81 floor-clearing combos: **43**

## Top 5 train candidates, evaluated on validation

| fraction | min_risk | max_stop | confirm_window | val_n | val_expectancy | val_winrate | val_dd |
|---|---|---|---|---|---|---|---|
| 1.0 | 0.3 | 2.5 | 30.0 | 101.0 | 0.0182 | 0.6634 | 9.1931 |
| 1.0 | 0.3 | 2.0 | 30.0 | 107.0 | 0.0250 | 0.6636 | 11.1331 |
| 0.7 | 0.3 | 2.0 | 20.0 | 100.0 | 0.0251 | 0.7800 | 6.5796 |
| 1.0 | 0.3 | 1.5 | 30.0 | 117.0 | 0.0477 | 0.6667 | 9.0348 |
| 0.85 | 0.3 | 2.5 | 30.0 | 106.0 | 0.0095 | 0.6887 | 10.3092 |

## Final candidate

Selected via train → validation only. Params: fraction=1.0, min_risk=0.3, max_stop=1.5, confirm_window=30.0.

**Reliability: a validation-floor-clearing top-5 train candidate.**

| period | n | floor | meets floor | expectancy_r | win_rate | max_dd_r | sharpe |
|---|---|---|---|---|---|---|---|
| train | 342.0 | 66 | yes | 0.1356 | 0.7281 | 10.3251 | 0.1434 |
| val | 117.0 | 22 | yes | 0.0477 | 0.6667 | 9.0348 | 0.0546 |
| test | 132.0 | 22 | yes | 0.0497 | 0.7045 | 9.4001 | 0.0599 |

Train → validation → test gap is the overfitting signal: expectancy 0.1356R (train) → 0.0477R (val) → 0.0497R (test).

## Deflated Sharpe Ratio

n_trials = 81 (every grid combination actually tested), sr_variance_across_trials = 0.001325 (variance of train-period Sharpe across the grid).

- train Sharpe (plain): 0.1434
- DSR (probability true Sharpe exceeds the deflation threshold, corrected for 81 trials): 0.8677028083537957
- sr0_threshold: 0.08936676176476827

## Multiple-comparisons caveat

81 combinations were tested against the same single-regime ~200-day history. The DSR above corrects for having tried all 81 of them (unlike the Mode-A-vs-B-only correction used elsewhere in this project's exploratory scripts) but does not make this a second, independent dataset — it is still the same underlying price history the stop-cap fix and min-R:R threshold comparisons were also evaluated against.

No change to production defaults is being recommended by this report.
