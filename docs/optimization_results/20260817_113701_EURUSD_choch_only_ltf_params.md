# LTF structural-TP parameter grid search — EURUSD / choch_only / m15

Generated 2026-08-17 11:37:01 by `scripts/backtest/grid_search_structural_tp.py`. Exploratory only — not written to `ltf_trigger_signals`/`backtest_runs`.

## Split

- Full range: 2026-01-27 00:30:43 → 2026-08-15 00:30:43
- Train (60%): 2026-01-27 00:30:43 → 2026-05-27 00:30:43  (floor=66)
- Validation (20%): 2026-05-27 00:30:43 → 2026-07-06 00:30:43  (floor=22)
- Test (20%): 2026-07-06 00:30:43 → 2026-08-15 00:30:43  (floor=22)

Grid size: 81 combinations (fraction=[0.7, 0.85, 1.0] × min_risk=[0.3, 0.5, 0.7] × max_stop=[1.5, 2.0, 2.5] × confirm_window=[10, 20, 30])

## Top 10 by train expectancy (floor-clearing combos only)

| fraction | min_risk | max_stop | confirm_window | train_n | train_expectancy | train_winrate | train_dd |
|---|---|---|---|---|---|---|---|
| 1.0 | 0.3 | 2.5 | 30.0 | 380.0 | 0.1177 | 0.7553 | 6.1353 |
| 1.0 | 0.3 | 2.0 | 30.0 | 403.0 | 0.1094 | 0.7469 | 6.1613 |
| 1.0 | 0.3 | 1.5 | 30.0 | 432.0 | 0.1093 | 0.7361 | 6.3324 |
| 1.0 | 0.3 | 2.5 | 20.0 | 307.0 | 0.1042 | 0.7655 | 7.2470 |
| 1.0 | 0.3 | 1.5 | 20.0 | 346.0 | 0.1004 | 0.7486 | 5.4699 |
| 1.0 | 0.3 | 2.0 | 20.0 | 319.0 | 0.0992 | 0.7586 | 8.0745 |
| 0.85 | 0.3 | 2.5 | 30.0 | 415.0 | 0.0957 | 0.7711 | 7.0983 |
| 0.85 | 0.3 | 1.5 | 30.0 | 468.0 | 0.0931 | 0.7564 | 7.3714 |
| 0.85 | 0.3 | 2.0 | 30.0 | 440.0 | 0.0930 | 0.7659 | 7.3371 |
| 0.85 | 0.3 | 2.0 | 20.0 | 350.0 | 0.0865 | 0.7800 | 8.9633 |

## Current production defaults

| 0.85 | 0.5 | 1.5 | 20.0 | 362.0 | 0.0433 | 0.7652 | 7.0351 |

Rank by train expectancy among 81 floor-clearing combos: **33**

## Top 5 train candidates, evaluated on validation

| fraction | min_risk | max_stop | confirm_window | val_n | val_expectancy | val_winrate | val_dd |
|---|---|---|---|---|---|---|---|
| 1.0 | 0.3 | 2.5 | 30.0 | 101.0 | 0.1766 | 0.7426 | 3.7706 |
| 1.0 | 0.3 | 2.0 | 30.0 | 105.0 | 0.1794 | 0.7333 | 3.7348 |
| 1.0 | 0.3 | 1.5 | 30.0 | 115.0 | 0.1756 | 0.6957 | 4.8136 |
| 1.0 | 0.3 | 2.5 | 20.0 | 92.0 | 0.1503 | 0.7717 | 3.4298 |
| 1.0 | 0.3 | 1.5 | 20.0 | 102.0 | 0.1433 | 0.7059 | 5.3226 |

## Final candidate

Selected via train → validation only. Params: fraction=1.0, min_risk=0.3, max_stop=2.0, confirm_window=30.0.

**Reliability: a validation-floor-clearing top-5 train candidate.**

| period | n | floor | meets floor | expectancy_r | win_rate | max_dd_r | sharpe |
|---|---|---|---|---|---|---|---|
| train | 403.0 | 66 | yes | 0.1094 | 0.7469 | 6.1613 | 0.1333 |
| val | 105.0 | 22 | yes | 0.1794 | 0.7333 | 3.7348 | 0.1962 |
| test | 140.0 | 22 | yes | 0.2809 | 0.8143 | 5.8813 | 0.2715 |

Train → validation → test gap is the overfitting signal: expectancy 0.1094R (train) → 0.1794R (val) → 0.2809R (test).

## Deflated Sharpe Ratio

n_trials = 81 (every grid combination actually tested), sr_variance_across_trials = 0.002279 (variance of train-period Sharpe across the grid).

- train Sharpe (plain): 0.1333
- DSR (probability true Sharpe exceeds the deflation threshold, corrected for 81 trials): 0.6326376222877701
- sr0_threshold: 0.11721390776822334

## Multiple-comparisons caveat

81 combinations were tested against the same single-regime ~200-day history. The DSR above corrects for having tried all 81 of them (unlike the Mode-A-vs-B-only correction used elsewhere in this project's exploratory scripts) but does not make this a second, independent dataset — it is still the same underlying price history the stop-cap fix and min-R:R threshold comparisons were also evaluated against.

No change to production defaults is being recommended by this report.
