"""
Demonstrates the new Inverse-Volatility + Fixed-Fractional risk sizing
(analysis/backtester/risk_management.py) layered on top of the existing
Kalman/OU engine's trade signals, instead of the flat "1 unit per trade"
convention every other script in this project uses.

This is a RISK/EXECUTION-LAYER demo, not a new edge-validation experiment
-- it does not re-litigate whether any OU config has a statistically
significant edge (see RESULTS.md experiment 19-22: none does yet). It
answers a different, narrower question: given a fixed, already-specified
signal-generation config, how does dynamic position sizing change the
resulting DOLLAR equity curve and drawdown compared to trading the exact
same signals at a flat size?

Usage:
    python scripts/research/risk_sizing_demo.py --symbol XAUUSD --timeframe m5
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.research.kalman_walkforward import load, PIP, ROUND_TRIP_PIPS, HMM_CALIB_BARS  # noqa: E402
from analysis.strategies.kalman_mean_reversion import run_mean_reversion  # noqa: E402
from analysis.backtester.risk_management import rolling_volatility, simulate_equity_with_sizing  # noqa: E402


# The "ค่าที่ใช้จริงกับ config ที่เคยผ่านเกณฑ์ (XAUUSD M5)" config documented in
# README.md's Kalman section -- a fixed, already-specified rule, not something
# re-optimized here.
FIXED_CONFIG = dict(
    calib_window=120, recalib_every=5, k=1.8, z_stop=2.8, q_mult=1.0, obs_noise_scale=1.0,
    tau_threshold=120, half_life_mult=2.0, friction_hurdle_mult=2.5,
    hmm_calib_bars=HMM_CALIB_BARS, hmm_block_states=(2,),
)


def extract_trades_with_entry_idx(res):
    """Same entry/exit pairing logic as kalman_walkforward.sim_pnl(), but
    also returns each trade's ENTRY bar index so its volatility-at-entry
    can be looked up for sizing."""
    trades = []  # (entry_idx, pnl_price_units)
    pos, entry_price, entry_idx = 0, None, None
    for i, sig in enumerate(res["signal"]):
        if sig in ("long", "short"):
            pos = 1 if sig == "long" else -1
            entry_price, entry_idx = res["close"].iloc[i], i
        elif sig is not None and entry_price is not None:
            pnl = pos * (res["close"].iloc[i] - entry_price)
            trades.append((entry_idx, pnl))
            pos, entry_price, entry_idx = 0, None, None
    return trades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="m5")
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--risk-fraction", type=float, default=0.01)
    parser.add_argument("--vol-window", type=int, default=20)
    args = parser.parse_args()

    df = load(args.symbol, args.timeframe)
    cost = ROUND_TRIP_PIPS * PIP[args.symbol]

    res = run_mean_reversion(
        df["price_datetime"], df["close_price"], df["high_price"], df["low_price"],
        spread=cost, **FIXED_CONFIG,
    )
    trades = extract_trades_with_entry_idx(res)
    print(f"=== {args.symbol} {args.timeframe}: {len(trades)} trades from fixed config (no re-optimization) ===")
    if not trades:
        print("  no trades generated -- nothing to size")
        return

    entry_idxs = np.array([t[0] for t in trades])
    pnl_price_units = np.array([t[1] - cost for t in trades])  # net of cost, same convention as sim_pnl()
    sigma_series = rolling_volatility(df["close_price"], window=args.vol_window)
    sigma_at_entry = sigma_series[entry_idxs]

    # contract_value=1.0: for XAUUSD (quoted $/oz) or EURUSD (quoted $/unit),
    # this treats position_size's output as "units of the base instrument"
    # directly, so size * contract_value * price_diff = correct dollar P&L.
    dyn = simulate_equity_with_sizing(
        pnl_price_units, sigma_at_entry, contract_value=1.0,
        initial_capital=args.initial_capital, risk_fraction=args.risk_fraction,
    )

    # Flat-size baseline for comparison: constant size chosen so its AVERAGE
    # dollar risk per trade matches the dynamic system's average target risk
    # (equity*risk_fraction at each trade, using the dynamic run's own
    # equity trajectory) -- an apples-to-apples "same average risk budget,
    # fixed vs dynamic size" comparison, not an arbitrary flat lot size.
    avg_target_risk = np.mean([e * args.risk_fraction for e in dyn["equity_curve"][:-1]])
    flat_size = avg_target_risk / (np.nanmean(sigma_at_entry[np.isfinite(sigma_at_entry) & (sigma_at_entry > 0)]))
    flat_equity = [args.initial_capital]
    eq = args.initial_capital
    for pnl in pnl_price_units:
        eq += flat_size * 1.0 * pnl
        flat_equity.append(eq)
    flat_equity = np.array(flat_equity)
    flat_maxdd = float(np.max(np.maximum.accumulate(flat_equity) - flat_equity))

    print(f"\n  Dynamic (inverse-vol + fixed-fractional {args.risk_fraction*100:.1f}% risk), "
          f"starting capital=${args.initial_capital:,.0f}:")
    print(f"    final equity=${dyn['final_equity']:,.2f}  max_drawdown=${dyn['max_drawdown_dollars']:,.2f}  "
          f"n_halted={dyn['n_halted']}")
    print(f"    position size: min={dyn['position_sizes'][dyn['position_sizes']>0].min():.2f} "
          f"max={dyn['position_sizes'].max():.2f} mean={dyn['position_sizes'][dyn['position_sizes']>0].mean():.2f}")
    print(f"\n  Flat size (={flat_size:.2f}, same average risk budget, size never adjusts):")
    print(f"    final equity=${flat_equity[-1]:,.2f}  max_drawdown=${flat_maxdd:,.2f}")

    out_path = ROOT / "scripts" / "research" / "plots" / "other" / f"risk_sizing_{args.symbol}_{args.timeframe}.png"
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(dyn["equity_curve"], color="#2e8b57", linewidth=1.3, label="Dynamic (inverse-vol + fixed-fractional)")
    ax.plot(flat_equity, color="#3b6fa0", linewidth=1.1, linestyle="--", label="Flat size (same avg risk budget)")
    ax.axhline(args.initial_capital, color="#999999", linewidth=0.8)
    ax.set_title(f"{args.symbol} {args.timeframe} -- Dynamic vs Flat position sizing, same signal ({len(trades)} trades)")
    ax.set_xlabel("trade #")
    ax.set_ylabel("equity ($)")
    ax.legend()
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130)
    print(f"\n  saved equity comparison plot -> {out_path}")


if __name__ == "__main__":
    main()
