# Statistical rigor checks — negative control, random baseline, median, bootstrap CI, MCC

Generated 2026-08-17 by `scripts/backtest/negative_control_temporal_shift.py`, `random_entry_baseline.py`, and `bootstrap_ci_and_mcc.py`. Layered on top of the existing strict-aligned grid search (`docs/optimization_results/20260817_11{1916,2645,3701,4512}_*`) — reads those CSVs and re-derives triggers/trades from raw data, does not modify or replace them. All 4 combinations use the same shared window as the grid search: 2026-01-27 → 2026-08-15 (200 days).

## 1. Negative control (temporal shift, -12h) — highest priority, checked first

Real triggers (production defaults) shifted -12h with entry price re-anchored at the shifted timestamp and $ risk/reward preserved from the real trigger — same frequency/direction mix/R:R shape, but detached from the real structural moment.

| symbol/mode | real expectancy | real win rate | shifted expectancy | shifted win rate | gap |
|---|---|---|---|---|---|
| XAUUSD choch_only | +0.0774R | 77.8% | **-0.1028R** | 67.9% | +0.1802R |
| XAUUSD choch_sweep | +0.0922R | 77.9% | **-0.0816R** | 69.8% | +0.1738R |
| EURUSD choch_only | +0.0714R | 76.6% | **-0.0676R** | 70.3% | +0.1389R |
| EURUSD choch_sweep | +0.0827R | 77.2% | **-0.0785R** | 68.9% | +0.1612R |

**Result: clean, all 4 combinations.** Every shifted (structurally-broken) version flips to negative expectancy — not just weaker, but negative — while win rate drops 8-10 points. A lookahead bug would not be expected to produce this pattern (it wouldn't care which specific -12h-shifted moment it's attached to). No evidence of lookahead bias found.

## 2. Random-entry baseline (10 draws per combination)

Real triggers' direction and $ risk/reward preserved, entry re-anchored to an independently-drawn uniform-random bar per trigger, 10 different random seeds.

| symbol/mode | real expectancy | random mean (10 draws) | random std | z-score | real exceeds all 10 draws |
|---|---|---|---|---|---|
| XAUUSD choch_only | 0.0774R | -0.0296R | 0.0148 | 7.23 | yes |
| XAUUSD choch_sweep | 0.0922R | -0.0176R | 0.0130 | 8.47 | yes |
| EURUSD choch_only | 0.0714R | -0.0050R | 0.0120 | 6.36 | yes |
| EURUSD choch_sweep | 0.0827R | -0.0033R | 0.0297 | 2.90 | yes |

**Result: clean, all 4 combinations.** Real signal expectancy exceeds every one of 10 random draws in every combination, z-scores 2.9-8.5. Genuine information content beyond generic favorable drift, consistent with the negative control.

## 3. Grid median vs. production defaults (81-combination grid, train period)

| symbol/mode | grid median (train exp.) | defaults (train exp.) | defaults' rank /81 | defaults above median |
|---|---|---|---|---|
| XAUUSD choch_only | 0.0920R | 0.0901R | 43 | no (46.9th pctile) |
| XAUUSD choch_sweep | 0.1063R | 0.1221R | 26 | **yes** |
| EURUSD choch_only | 0.0335R | 0.0433R | 33 | **yes** |
| EURUSD choch_sweep | 0.0440R | 0.0454R | 39 | **yes** |

**Result: defaults are at-or-above median in 3 of 4 combinations**, and essentially at the median in the 4th (XAUUSD choch_only, 46.9th percentile — not a below-median outlier, just short of 50th). Defaults are not a case that's only defensible by comparison to a lucky top-of-grid outlier.

## 4. Bootstrap 95% CI + Cliff's delta (winner vs. defaults, full 200-day window, 2000 resamples)

| symbol/mode | defaults expectancy [95% CI] | winner expectancy [95% CI] | Cliff's delta | magnitude | CIs overlap |
|---|---|---|---|---|---|
| XAUUSD choch_only | 0.0774R [0.021, 0.133] | 0.0990R [0.028, 0.171] | 0.0073 | negligible | **yes** |
| XAUUSD choch_sweep | 0.0922R [0.027, 0.161] | 0.1405R [0.060, 0.228] | 0.0336 | negligible | **yes** |
| EURUSD choch_only | 0.0714R [0.014, 0.127] | 0.1578R [0.093, 0.227] | 0.0625 | negligible | **yes** |
| EURUSD choch_sweep | 0.0827R [0.022, 0.146] | 0.1649R [0.088, 0.246] | 0.0384 | negligible | **yes** |

**Result: important finding, reported plainly.** Despite the grid-search winner having a higher point-estimate expectancy in all 4 combinations, Cliff's delta is negligible (<0.15) in every case and the 95% confidence intervals overlap substantially in every case. **The apparent improvement from grid-search optimization is not statistically distinguishable from noise at this sample size, over the full period.** This tempers the earlier grid-search framing — the winning combination is not demonstrated to be genuinely better than production defaults, only that it scored higher on this specific ~4-month train slice (consistent with the overfitting signal already found in the XAUUSD sensitivity plots).

## 5. MCC (direction vs. outcome) — confirms `backtest_trades` schema is sufficient, adds one more metric

`backtest_trades` already has `direction`, `exit_reason`, `r_outcome`, `entry_bar_datetime` (see `storage/schema_curated.sql`) — confirmed sufficient to compute MCC and every other metric here without re-running the backtest. MCC computed as `matthews_corrcoef(direction_is_bullish, won)` — this specifically tests whether the edge is direction-dependent (relevant given gold's flagged one-directional bull-run regime).

| symbol/mode | defaults MCC | winner MCC |
|---|---|---|
| XAUUSD choch_only | -0.0767 | -0.0164 |
| XAUUSD choch_sweep | -0.0590 | -0.0770 |
| EURUSD choch_only | -0.0177 | -0.0428 |
| EURUSD choch_sweep | -0.0282 | -0.0131 |

**Result: all 8 values near zero (|MCC| < 0.08).** No meaningful correlation between trade direction and win/loss outcome in either parameter set — the edge is not concentrated in the bullish direction despite the underlying bull-run regime. A reassuring result given the context, not a finding that changes any prior conclusion.

## Overall conclusion

Items 1 and 2 (the checks capable of invalidating everything else) came back clean across all 4 combinations — no evidence of lookahead bias or an artifact of generic drift. The system has genuine information content. Items 3-5 add a more sobering, honest layer: the grid-search "winner" is not statistically distinguishable from production defaults once tested properly (bootstrap CI, Cliff's delta), which is consistent with — not contradicting — the overfitting signal already visualized for XAUUSD. **No change to production defaults is recommended by any of this.**
