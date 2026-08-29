"""
Position sizing and pre-trade risk controls, layered on top of an existing
signal-generation engine's trade list (e.g. kalman_mean_reversion.py's
run_mean_reversion() output). Everything upstream of this module works in
PRICE units per trade (net = pos * (exit_price - entry_price) - cost); this
module is what turns that into DOLLAR P&L against an actual account
balance, with position size that moves with both volatility and equity.

Two mechanisms, from the same underlying idea (risk a fixed dollar amount
per trade, not a fixed lot size):

1. Inverse volatility sizing: Position Size_t = Target Risk ($) / (sigma_t
   * contract_value). When the market is choppy (sigma_t wide), size
   shrinks automatically; when it's quiet (sigma_t narrow), size grows --
   keeping the DOLLAR risk per trade constant instead of the LOT size.

2. Fixed-fractional dynamic risk cap: Target Risk ($) is itself a fixed
   fraction of CURRENT equity (not a constant dollar figure), so the
   dollar amount at risk shrinks automatically after a losing streak
   (protecting remaining capital) and grows after a winning streak
   (compounding) -- the classic fixed-fractional position sizing rule.
   A pre-trade halt stops opening new trades once equity has fallen below
   a floor, so a losing streak can't compound into ruin.
"""

import numpy as np
import pandas as pd


def rolling_volatility(close: pd.Series, window: int = 20) -> np.ndarray:
    """Rolling standard deviation of price (sigma_t), shifted by 1 bar so
    the value used to size a trade at bar t never includes bar t's own
    price. window=14-20 bars per the spec (ATR(14) is an equally valid
    substitute -- kalman_mean_reversion.py already has an ATR helper if a
    caller prefers that instead of plain rolling std)."""
    return close.rolling(window).std().shift(1).to_numpy()


def position_size(equity: float, sigma_t: float, contract_value: float, risk_fraction: float = 0.01) -> float:
    """Position Size = (equity * risk_fraction) / (sigma_t * contract_value).

    equity: current account balance in $.
    risk_fraction: fraction of CURRENT equity to risk on this trade (the
    fixed-fractional rule -- e.g. 0.01 = 1%). Target Risk ($) = equity *
    risk_fraction; at a $10,000 starting balance and 1%, that is $100 per
    trade, matching the spec's "fix starting at $100."
    sigma_t: recent volatility (see rolling_volatility) standing in for
    the expected adverse-excursion distance, in the same price units as
    the traded instrument.
    contract_value: $ value of a 1.0 price-unit move for a position size
    of 1.0 (e.g. for XAUUSD, 1 lot = 100 oz, so a $1 move = $100;
    contract_value=100 in that convention -- caller decides the units, as
    long as sigma_t and contract_value are expressed consistently).

    Returns 0.0 if sigma_t is non-positive/non-finite (no sizing signal
    yet -- e.g. still inside the rolling window's warm-up).
    """
    if not np.isfinite(sigma_t) or sigma_t <= 0 or equity <= 0:
        return 0.0
    return (equity * risk_fraction) / (sigma_t * contract_value)


def simulate_equity_with_sizing(
    trade_returns_price_units: np.ndarray,
    sigma_at_entry: np.ndarray,
    contract_value: float,
    initial_capital: float = 10_000.0,
    risk_fraction: float = 0.01,
    equity_floor_frac: float = 0.5,
) -> dict:
    """Replays a trade list (already-computed price-unit P&L per trade,
    e.g. from kalman_walkforward.sim_pnl(), IN ENTRY ORDER) as dollar P&L
    under dynamic inverse-volatility + fixed-fractional sizing, instead of
    the flat "1 unit per trade" assumption used everywhere else in this
    project's backtests so far.

    trade_returns_price_units: net P&L of each trade in PRICE units (i.e.
    pos * (exit-entry) - cost, the same convention as sim_pnl()'s output),
    one entry per trade, in chronological (entry) order.
    sigma_at_entry: rolling_volatility()'s value at each trade's ENTRY
    bar, same length and order as trade_returns_price_units. A trade
    whose sigma is 0/NaN (still warming up) is skipped (0 position size).

    equity_floor_frac: pre-trade circuit breaker -- once equity drops
    below equity_floor_frac * initial_capital, no further trades are
    sized (position size forced to 0 for the rest of the run). This is
    the "make sure there's enough capital left for the next statistical
    trade" check from the spec, applied as a hard floor rather than a
    soft warning.

    Returns dict with equity_curve (array, one value per trade including
    the starting capital as index 0), dollar_pnl (array, per trade),
    position_sizes (array), and n_halted (count of trades skipped because
    the equity floor had already been breached).
    """
    n = len(trade_returns_price_units)
    equity = initial_capital
    equity_curve = [equity]
    dollar_pnl = np.zeros(n)
    sizes = np.zeros(n)
    floor = equity_floor_frac * initial_capital
    n_halted = 0

    for i in range(n):
        if equity <= floor:
            n_halted += 1
            equity_curve.append(equity)
            continue
        size = position_size(equity, sigma_at_entry[i], contract_value, risk_fraction)
        sizes[i] = size
        pnl = size * contract_value * trade_returns_price_units[i]
        dollar_pnl[i] = pnl
        equity += pnl
        equity_curve.append(equity)

    return dict(
        equity_curve=np.array(equity_curve),
        dollar_pnl=dollar_pnl,
        position_sizes=sizes,
        n_halted=n_halted,
        final_equity=equity,
        max_drawdown_dollars=float(np.max(np.maximum.accumulate(equity_curve) - equity_curve)),
    )
