"""
HMM regime-filter ablation: takes the exact winning config from each
EURUSD/NDX100 timeframe's validation-selected best_kw (from the full
kalman_walkforward.py run, see scripts/research/RESULTS.md experiment 14)
and re-runs the TEST split twice -- once with the HMM filter on (as
originally run), once with it off (hmm_calib_bars=None, everything else
identical) -- to isolate whether the HMM filter is what's suppressing
performance on these two assets, or whether the config/asset itself is
the limiting factor regardless of HMM.

Usage:
    python scripts/research/hmm_ablation.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.research.kalman_walkforward import load, split_60_20_20, run_cfg, profit_factor, PIP, ROUND_TRIP_PIPS, HMM_CALIB_BARS  # noqa: E402
from analysis.backtester.deflated_sharpe import trade_metrics, deflated_sharpe_ratio  # noqa: E402

# best_kw taken verbatim from the user's own run 14 (RESULTS.md experiment 14)
CONFIGS = {
    ("EURUSD", "m5"): dict(calib_window=80, k=1.8, z_stop=2.8, q_mult=1.0, obs_noise_scale=1.0, tau_frac=1.0),
    ("EURUSD", "m15"): dict(calib_window=40, k=1.8, z_stop=2.8, q_mult=1.0, obs_noise_scale=0.5, tau_frac=1.0),
    ("EURUSD", "h1"): dict(calib_window=40, k=2.2, z_stop=3.2, q_mult=1.0, obs_noise_scale=1.0, tau_frac=1.0),
    ("NDX100", "m5"): dict(calib_window=80, k=1.8, z_stop=2.8, q_mult=1.0, obs_noise_scale=1.0, tau_frac=1.0),
    ("NDX100", "m15"): dict(calib_window=60, k=1.8, z_stop=2.8, q_mult=1.0, obs_noise_scale=1.0, tau_frac=1.0),
    ("NDX100", "h1"): dict(calib_window=40, k=1.8, z_stop=2.8, q_mult=1.0, obs_noise_scale=0.5, tau_frac=1.0),
}


def run_variant(dset, cost, cfg, hmm_on: bool):
    kw = dict(
        calib_window=cfg["calib_window"], recalib_every=5,
        obs_noise_scale=cfg["obs_noise_scale"], q_mult=cfg["q_mult"], k=cfg["k"],
        z_stop=cfg["z_stop"], half_life_mult=2.0,
        hmm_calib_bars=HMM_CALIB_BARS if hmm_on else None,
        hmm_block_states=(2,),
        tau_threshold=cfg["calib_window"] * cfg["tau_frac"],
        spread=cost, friction_hurdle_mult=2.5,
    )
    net = run_cfg(dset, cost, **kw)
    tm = trade_metrics(net)
    dsr = deflated_sharpe_ratio(net, n_trials=1, sr_variance_across_trials=0.0)
    return tm, dsr, net


def main():
    print(f"{'symbol':<8}{'tf':<5}{'HMM':<6}{'n':<5}{'win%':<8}{'PF':<8}{'expct':<12}{'maxDD':<10}{'DSR':<8}")
    for (symbol, table), cfg in CONFIGS.items():
        df = load(symbol, table)
        train, val, test = split_60_20_20(df)
        cost = ROUND_TRIP_PIPS * PIP[symbol]
        for hmm_on in (True, False):
            tm, dsr, net = run_variant(test, cost, cfg, hmm_on)
            pf = tm["profit_factor"] if tm["profit_factor"] is not None else 0.0
            print(f"{symbol:<8}{table:<5}{'ON' if hmm_on else 'OFF':<6}"
                  f"{tm['n_trades']:<5}{(tm['win_rate'] or 0)*100:<8.1f}{pf:<8.2f}"
                  f"{tm['expectancy_r'] or 0:<12.4f}{tm['max_drawdown_r'] or 0:<10.2f}{(dsr['dsr'] or 0):<8.4f}")


if __name__ == "__main__":
    main()
