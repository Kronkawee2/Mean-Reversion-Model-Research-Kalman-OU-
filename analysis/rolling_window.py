"""
Shared 2-year rolling-window default for divergence models, backtest runs,
and dashboard aggregates (see docs/DECISIONS.md: "2-year rolling window
default"). This only bounds calculation/display queries via a WHERE-clause
date filter -- full history stays in the database untouched, nothing is
deleted. Centralized here so the window can be adjusted or reverted in one
place instead of hunting down every query that uses it.
"""
import datetime

ROLLING_WINDOW_DAYS = 730  # ~2 years


def rolling_window_start(as_of: datetime.datetime = None) -> datetime.date:
    as_of = as_of or datetime.datetime.utcnow()
    return (as_of - datetime.timedelta(days=ROLLING_WINDOW_DAYS)).date()
