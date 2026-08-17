# LTF structural-TP parameter grid search — XAUUSD / choch_sweep / m15

Generated 2026-08-17 11:26:45 by `scripts/backtest/grid_search_structural_tp.py`. Exploratory only — not written to `ltf_trigger_signals`/`backtest_runs`.

## Split

- Full range: 2026-01-27 00:30:43 → 2026-08-15 00:30:43
- Train (60%): 2026-01-27 00:30:43 → 2026-05-27 00:30:43  (floor=66)
- Validation (20%): 2026-05-27 00:30:43 → 2026-07-06 00:30:43  (floor=22)
- Test (20%): 2026-07-06 00:30:43 → 2026-08-15 00:30:43  (floor=22)

Grid size: 81 combinations (fraction=[0.7, 0.85, 1.0] × min_risk=[0.3, 0.5, 0.7] × max_stop=[1.5, 2.0, 2.5] × confirm_window=[10, 20, 30])

## Top 10 by train expectancy (floor-clearing combos only)

| fraction | min_risk | max_stop | confirm_window | train_n | train_expectancy | train_winrate | train_dd |
|---|---|---|---|---|---|---|---|
| 1.0 | 0.3 | 2.0 | 20.0 | 234.0 | 0.1841 | 0.7821 | 4.4240 |
| 1.0 | 0.3 | 2.5 | 20.0 | 232.0 | 0.1752 | 0.7888 | 4.4785 |
| 1.0 | 0.3 | 1.5 | 20.0 | 253.0 | 0.1747 | 0.7589 | 5.4624 |
| 1.0 | 0.5 | 2.0 | 20.0 | 225.0 | 0.1672 | 0.7956 | 4.1012 |
| 0.7 | 0.3 | 2.0 | 20.0 | 263.0 | 0.1669 | 0.8479 | 2.4331 |
| 0.7 | 0.5 | 2.0 | 20.0 | 250.0 | 0.1588 | 0.8640 | 2.3672 |
| 0.7 | 0.3 | 2.5 | 20.0 | 260.0 | 0.1582 | 0.8500 | 2.8595 |
| 1.0 | 0.5 | 2.5 | 20.0 | 223.0 | 0.1579 | 0.8027 | 3.6569 |
| 0.85 | 0.3 | 2.0 | 20.0 | 249.0 | 0.1578 | 0.8112 | 4.6604 |
| 0.85 | 0.5 | 2.0 | 20.0 | 238.0 | 0.1526 | 0.8277 | 3.2317 |

## Current production defaults

| 0.85 | 0.5 | 1.5 | 20.0 | 254.0 | 0.1221 | 0.7913 | 4.1836 |

Rank by train expectancy among 81 floor-clearing combos: **26**

## Top 5 train candidates, evaluated on validation

| fraction | min_risk | max_stop | confirm_window | val_n | val_expectancy | val_winrate | val_dd |
|---|---|---|---|---|---|---|---|
| 1.0 | 0.3 | 2.0 | 20.0 | 81.0 | 0.0619 | 0.7284 | 5.2629 |
| 1.0 | 0.3 | 2.5 | 20.0 | 76.0 | 0.0734 | 0.7368 | 5.3332 |
| 1.0 | 0.3 | 1.5 | 20.0 | 83.0 | 0.0880 | 0.7349 | 5.1366 |
| 1.0 | 0.5 | 2.0 | 20.0 | 74.0 | 0.0189 | 0.7297 | 4.2629 |
| 0.7 | 0.3 | 2.0 | 20.0 | 85.0 | 0.0132 | 0.7529 | 5.2511 |

## Final candidate

Selected via train → validation only. Params: fraction=1.0, min_risk=0.3, max_stop=1.5, confirm_window=20.0.

**Reliability: a validation-floor-clearing top-5 train candidate.**

| period | n | floor | meets floor | expectancy_r | win_rate | max_dd_r | sharpe |
|---|---|---|---|---|---|---|---|
| train | 253.0 | 66 | yes | 0.1747 | 0.7589 | 5.4624 | 0.1916 |
| val | 83.0 | 22 | yes | 0.0880 | 0.7349 | 5.1366 | 0.1063 |
| test | 84.0 | 22 | yes | 0.0894 | 0.7262 | 5.3234 | 0.1116 |

Train → validation → test gap is the overfitting signal: expectancy 0.1747R (train) → 0.0880R (val) → 0.0894R (test).

## Deflated Sharpe Ratio

n_trials = 81 (every grid combination actually tested), sr_variance_across_trials = 0.001943 (variance of train-period Sharpe across the grid).

- train Sharpe (plain): 0.1916
- DSR (probability true Sharpe exceeds the deflation threshold, corrected for 81 trials): 0.9338767728111634
- sr0_threshold: 0.10824269705937119

## Multiple-comparisons caveat

81 combinations were tested against the same single-regime ~200-day history. The DSR above corrects for having tried all 81 of them (unlike the Mode-A-vs-B-only correction used elsewhere in this project's exploratory scripts) but does not make this a second, independent dataset — it is still the same underlying price history the stop-cap fix and min-R:R threshold comparisons were also evaluated against.

No change to production defaults is being recommended by this report.
