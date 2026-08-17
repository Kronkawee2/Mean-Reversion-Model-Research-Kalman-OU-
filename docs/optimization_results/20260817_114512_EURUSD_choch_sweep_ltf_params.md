# LTF structural-TP parameter grid search — EURUSD / choch_sweep / m15

Generated 2026-08-17 11:45:12 by `scripts/backtest/grid_search_structural_tp.py`. Exploratory only — not written to `ltf_trigger_signals`/`backtest_runs`.

## Split

- Full range: 2026-01-27 00:30:43 → 2026-08-15 00:30:43
- Train (60%): 2026-01-27 00:30:43 → 2026-05-27 00:30:43  (floor=66)
- Validation (20%): 2026-05-27 00:30:43 → 2026-07-06 00:30:43  (floor=22)
- Test (20%): 2026-07-06 00:30:43 → 2026-08-15 00:30:43  (floor=22)

Grid size: 81 combinations (fraction=[0.7, 0.85, 1.0] × min_risk=[0.3, 0.5, 0.7] × max_stop=[1.5, 2.0, 2.5] × confirm_window=[10, 20, 30])

## Top 10 by train expectancy (floor-clearing combos only)

| fraction | min_risk | max_stop | confirm_window | train_n | train_expectancy | train_winrate | train_dd |
|---|---|---|---|---|---|---|---|
| 1.0 | 0.3 | 2.5 | 20.0 | 273.0 | 0.1504 | 0.7692 | 3.8933 |
| 1.0 | 0.3 | 2.0 | 10.0 | 196.0 | 0.1495 | 0.8010 | 4.7645 |
| 1.0 | 0.3 | 2.5 | 10.0 | 189.0 | 0.1461 | 0.8095 | 4.9035 |
| 1.0 | 0.3 | 1.5 | 20.0 | 313.0 | 0.1424 | 0.7508 | 4.6384 |
| 1.0 | 0.3 | 1.5 | 10.0 | 207.0 | 0.1346 | 0.7778 | 5.9086 |
| 1.0 | 0.3 | 2.0 | 20.0 | 288.0 | 0.1319 | 0.7500 | 4.6421 |
| 0.85 | 0.3 | 2.5 | 20.0 | 289.0 | 0.1202 | 0.7855 | 4.0299 |
| 0.85 | 0.3 | 1.5 | 20.0 | 328.0 | 0.1180 | 0.7713 | 4.6360 |
| 0.85 | 0.3 | 2.0 | 20.0 | 304.0 | 0.1142 | 0.7763 | 4.1967 |
| 0.85 | 0.3 | 2.0 | 10.0 | 200.0 | 0.1055 | 0.8100 | 5.0998 |

## Current production defaults

| 0.85 | 0.5 | 1.5 | 20.0 | 310.0 | 0.0454 | 0.7645 | 5.7445 |

Rank by train expectancy among 81 floor-clearing combos: **39**

## Top 5 train candidates, evaluated on validation

| fraction | min_risk | max_stop | confirm_window | val_n | val_expectancy | val_winrate | val_dd |
|---|---|---|---|---|---|---|---|
| 1.0 | 0.3 | 2.5 | 20.0 | 83.0 | 0.1718 | 0.7590 | 2.2730 |
| 1.0 | 0.3 | 2.0 | 10.0 | 60.0 | 0.1156 | 0.7667 | 2.7294 |
| 1.0 | 0.3 | 2.5 | 10.0 | 56.0 | 0.1532 | 0.8036 | 2.0000 |
| 1.0 | 0.3 | 1.5 | 20.0 | 97.0 | 0.1739 | 0.7113 | 3.9704 |
| 1.0 | 0.3 | 1.5 | 10.0 | 64.0 | 0.1258 | 0.7344 | 3.0422 |

## Final candidate

Selected via train → validation only. Params: fraction=1.0, min_risk=0.3, max_stop=1.5, confirm_window=20.0.

**Reliability: a validation-floor-clearing top-5 train candidate.**

| period | n | floor | meets floor | expectancy_r | win_rate | max_dd_r | sharpe |
|---|---|---|---|---|---|---|---|
| train | 313.0 | 66 | yes | 0.1424 | 0.7508 | 4.6384 | 0.1593 |
| val | 97.0 | 22 | yes | 0.1739 | 0.7113 | 3.9704 | 0.1710 |
| test | 112.0 | 22 | yes | 0.2200 | 0.7679 | 3.8000 | 0.2321 |

Train → validation → test gap is the overfitting signal: expectancy 0.1424R (train) → 0.1739R (val) → 0.2200R (test).

## Deflated Sharpe Ratio

n_trials = 81 (every grid combination actually tested), sr_variance_across_trials = 0.003778 (variance of train-period Sharpe across the grid).

- train Sharpe (plain): 0.1593
- DSR (probability true Sharpe exceeds the deflation threshold, corrected for 81 trials): 0.5650192918977925
- sr0_threshold: 0.1509305095186349

## Multiple-comparisons caveat

81 combinations were tested against the same single-regime ~200-day history. The DSR above corrects for having tried all 81 of them (unlike the Mode-A-vs-B-only correction used elsewhere in this project's exploratory scripts) but does not make this a second, independent dataset — it is still the same underlying price history the stop-cap fix and min-R:R threshold comparisons were also evaluated against.

No change to production defaults is being recommended by this report.
