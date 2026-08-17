# Optimization results

Output of `scripts/backtest/grid_search_structural_tp.py` and similar exploratory grid-search scripts. Each run writes two timestamped files here rather than overwriting the previous run, so this directory accumulates a history as more data comes in:

- `<timestamp>_ltf_params.md` — human-readable report: split definition, top candidates by train expectancy, the train→validation→test comparison for the selected final candidate, and the Deflated Sharpe Ratio corrected for the actual number of grid combinations tested.
- `<timestamp>_<symbol>_<mode>_grid.csv` — every combination tested, every parameter and metric, for re-analysis without re-running the grid search.

None of this is written back to `ltf_trigger_signals`/`backtest_runs`/`backtest_trades` — it's exploratory only. A report here recommending or ranking a parameter set is not itself a production change; see `docs/DECISIONS.md` for what's actually deployed and why.
