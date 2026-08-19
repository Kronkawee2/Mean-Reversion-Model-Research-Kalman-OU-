"""
Backtest Results — per symbol/mode/period metrics from
curated_<symbol>.backtest_runs, plus trade-level analysis computed live
from backtest_trades (R-multiple distribution, win/loss streaks, drawdown
recovery time, monthly/quarterly breakdown, time-in-market %, best/worst
trade, and a USD-at-fixed-0.01-lot equity curve -- a DISPLAY CONVENIENCE
for intuitive reading, not a real position-sizing feature: contract_
multiplier converts each trade's own risk distance (entry-stop, already
stored) into USD at a fixed 0.01 lot (1 XAUUSD lot = 100oz -> 0.01 lot =
1oz -> $1 price move = $1 P&L; 1 EURUSD lot = 100,000 units -> 0.01 lot =
1,000 units -> $1 price move = $1,000 P&L). Also shows the structural-TP
stop/target variant comparison (curated_<symbol>.tp_variant_comparison,
gold only -- EURUSD variants were never run, see
scripts/backtest/compare_structural_tp_variants.py) with the multiple-
comparisons caveat printed directly on the page, not just in a report.

Rebuilt from the original 2_stats.py, which computed win rate/PF/equity
curve from mart.trade_signals (old ad-hoc confluence model, always empty
in this project's actual history). mart.trade_signals itself is now
unused by any dashboard page -- see dashboard/signal_store.py (no longer
imported here).

2026-08 redesign: the floor pass/fail verdict moved out of a paragraph of
caveat text into a color-coded hero banner (impossible to miss, matching
how LTF Triggers' production banner works) with the headline metrics
directly underneath; everything past the headline metrics moved into
st.tabs (Trade Analysis / Time & Periods / Equity Curve / Variant
Comparison) instead of one long continuous scroll of dense panels -- same
data, same computations, no logic changes, purely navigation/hierarchy.
"""

import os, sys, json
import pymysql, pymysql.cursors
import pandas as pd
import numpy as np
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

DASH = Path(__file__).parent.parent
if str(DASH) not in sys.path:
    sys.path.insert(0, str(DASH))
ROOT = DASH.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from analysis.rolling_window import rolling_window_start  # noqa: E402

st.set_page_config(
    page_title="Backtest Results",
    page_icon="R",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
  .stApp { background:#000; font-family:'Inter',sans-serif; }
  header[data-testid="stHeader"] { background:#000; }
  .block-container { padding:2.6rem 1rem 0 1rem; max-width:100%; }

  .metric-card {
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:6px;
    padding:14px 16px; text-align:center; height:100%;
  }
  .metric-label { font-size:11px; color:#555; margin-bottom:4px; }
  .metric-value { font-size:22px; font-weight:700; color:#d1d4dc; white-space:nowrap; }
  .metric-value-8up { font-size:17px; }
  .metric-sub   { font-size:11px; color:#787b86; margin-top:2px; }

  .panel-title {
    font-size:11px; font-weight:600; letter-spacing:0.08em; color:#787b86;
    text-transform:uppercase; margin-bottom:10px; border-bottom:1px solid #1e1e2e; padding-bottom:6px;
  }
  .caveat-box {
    background:#140d0d; border:1px solid #2e1e1e; border-radius:6px;
    padding:14px 16px; margin:10px 0 16px 0; font-size:12px; color:#a08080; line-height:1.6;
  }
  .caveat-box b { color:#d4b16a; }
  .floor-pass { color:#26a69a; font-weight:700; }
  .floor-fail { color:#ef5350; font-weight:700; }

  .hero-banner {
    border-radius:8px; padding:16px 20px; margin-bottom:16px;
    display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
  }
  .hero-banner.pass { background:#0a1a12; border:1px solid #1a4d34; }
  .hero-banner.fail { background:#1a0d0d; border:1px solid #4d1a1a; }
  .hero-verdict { font-size:15px; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; }
  .hero-verdict.pass { color:#5fc9a4; }
  .hero-verdict.fail { color:#ef8a85; }
  .hero-sub { font-size:12px; color:#8a8a8a; }

  footer { visibility:hidden; } #MainMenu { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

DB = {
    "host":    os.getenv("DB_HOST", "localhost"),
    "port":    int(os.getenv("DB_PORT", "3308")),
    "user":    os.getenv("DB_USER", "quant_user"),
    "password":os.getenv("DB_PASSWORD", ""),
    "charset": "utf8mb4",
}
ASSETS = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}
MODE_LABELS = {"choch_only": "Mode A — CHoCH only", "choch_sweep": "Mode B — CHoCH + Sweep"}
# 1.0 lot = 100oz for gold, 100,000 units for EURUSD -> 0.01 lot contract multiplier per $1 price move.
CONTRACT_MULTIPLIER = {"XAUUSD": 1.0, "EURUSD": 1000.0}


def _conn(db_name):
    return pymysql.connect(**DB, database=db_name, cursorclass=pymysql.cursors.DictCursor)


@st.cache_data(ttl=30)
def load_run(db_name, symbol, mode, period):
    conn = _conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM backtest_runs WHERE symbol=%s AND mode=%s AND period=%s",
                (symbol, mode, period),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return row


@st.cache_data(ttl=30)
def load_trades(db_name, symbol, mode) -> pd.DataFrame:
    conn = _conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT direction, entry_bar_datetime, entry_price, stop_price, target_price, "
                "structural_rr, exit_bar_datetime, exit_reason, bars_held, r_outcome "
                "FROM backtest_trades WHERE symbol=%s AND mode=%s AND entry_bar_datetime >= %s "
                "ORDER BY entry_bar_datetime ASC",
                (symbol, mode, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["entry_bar_datetime"] = pd.to_datetime(df["entry_bar_datetime"])
    df["exit_bar_datetime"] = pd.to_datetime(df["exit_bar_datetime"])
    for c in ("entry_price", "stop_price", "target_price", "structural_rr", "r_outcome"):
        df[c] = df[c].astype(float)
    return df


@st.cache_data(ttl=30)
def load_variant_comparison(db_name, symbol, mode) -> pd.DataFrame:
    conn = _conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM tp_variant_comparison WHERE symbol=%s AND mode=%s ORDER BY variant, period",
                (symbol, mode),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def compute_streaks(r: np.ndarray):
    max_win_streak = max_loss_streak = cur_win = cur_loss = 0
    for v in r:
        if v > 0:
            cur_win += 1; cur_loss = 0
        else:
            cur_loss += 1; cur_win = 0
        max_win_streak = max(max_win_streak, cur_win)
        max_loss_streak = max(max_loss_streak, cur_loss)
    return max_win_streak, max_loss_streak


def compute_drawdown_recovery(decided: pd.DataFrame):
    """Returns (trades_to_recover, calendar_days_to_recover) for the SINGLE
    largest drawdown -- from the pre-drawdown peak to the first later point
    equity exceeds that peak again. None if never recovered by the last trade."""
    if decided.empty:
        return None, None
    equity = decided["r_outcome"].cumsum().values
    times = decided["exit_bar_datetime"].values
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    trough_idx = int(np.argmax(dd))
    peak_val = peak[trough_idx]
    peak_idx = int(np.where(equity[:trough_idx + 1] == peak_val)[0][0])

    recovery_idx = None
    for i in range(trough_idx + 1, len(equity)):
        if equity[i] >= peak_val:
            recovery_idx = i
            break
    if recovery_idx is None:
        return None, None
    trades_to_recover = recovery_idx - trough_idx
    days_to_recover = (pd.Timestamp(times[recovery_idx]) - pd.Timestamp(times[trough_idx])).total_seconds() / 86400.0
    return trades_to_recover, days_to_recover


def compute_period_breakdown(decided: pd.DataFrame, freq: str, label_col: str) -> pd.DataFrame:
    """freq: 'W' (week, Mon-start) or 'M' (calendar month). Returns one row per
    period with trade count, win rate, and expectancy (mean R) -- the minimum
    fields requested for the weekly/monthly early-warning breakdown."""
    g = decided.copy()
    g[label_col] = g["entry_bar_datetime"].dt.to_period(freq).astype(str)
    agg = g.groupby(label_col).agg(
        trades=("r_outcome", "count"),
        win_rate=("r_outcome", lambda x: (x > 0).mean()),
        expectancy_r=("r_outcome", "mean"),
        sum_r=("r_outcome", "sum"),
    ).reset_index()
    agg["win_rate"] = (agg["win_rate"] * 100).round(1)
    agg["expectancy_r"] = agg["expectancy_r"].round(3)
    agg["sum_r"] = agg["sum_r"].round(2)
    return agg


def detect_declining_trend(expectancy: pd.Series, min_streak: int = 3):
    """Flags an early-warning trend if the most recent `min_streak`+ periods
    are either all negative-expectancy, or monotonically declining
    (each period's expectancy <= the one before it) — checked from the most
    recent period backwards. Returns (flagged, streak_len, streak_kind)."""
    vals = expectancy.values
    n = len(vals)
    if n < min_streak:
        return False, 0, None

    neg_streak = 0
    for v in vals[::-1]:
        if v < 0:
            neg_streak += 1
        else:
            break

    decl_streak = 1
    for i in range(n - 1, 0, -1):
        if vals[i] <= vals[i - 1]:
            decl_streak += 1
        else:
            break

    if neg_streak >= min_streak:
        return True, neg_streak, "negative"
    if decl_streak >= min_streak:
        return True, decl_streak, "declining"
    return False, 0, None


def render_period_breakdown(decided: pd.DataFrame, freq: str, title: str, label_col: str):
    agg = compute_period_breakdown(decided, freq, label_col)
    if agg.empty:
        st.info(f"No decided trades to build a {title.lower()} breakdown.")
        return

    flagged, streak_len, streak_kind = detect_declining_trend(agg["expectancy_r"])
    if flagged:
        kind_txt = "negative expectancy" if streak_kind == "negative" else "declining expectancy"
        st.markdown(f"""
<div class="caveat-box" style="border-color:#3a1e1e;background:#1a0d0d;">
  <b>⚠ Trending down:</b> last {streak_len} consecutive {title.lower()} periods show {kind_txt} —
  early-warning signal only, not a stop-trading instruction.
</div>
""", unsafe_allow_html=True)

    display = agg.rename(columns={
        label_col: title, "trades": "Trades", "win_rate": "Win Rate %",
        "expectancy_r": "Expectancy R", "sum_r": "Sum R",
    })
    st.dataframe(display, use_container_width=True, hide_index=True)


def render_usd_equity_curve(decided: pd.DataFrame, symbol: str):
    mult = CONTRACT_MULTIPLIER[symbol]
    usd = decided["r_outcome"] * (decided["entry_price"] - decided["stop_price"]).abs() * mult
    cum_usd = usd.cumsum()
    points = [{"time": int(t.timestamp()), "value": round(float(v), 2)}
              for t, v in zip(decided["exit_bar_datetime"], cum_usd)]
    color = "#26a69a" if (cum_usd.iloc[-1] if len(cum_usd) else 0) >= 0 else "#ef5350"
    html = f"""<!DOCTYPE html>
<html><head>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>html,body{{height:100%;margin:0;padding:0;background:#000;overflow:hidden;}}#chart{{width:100%;height:100%;}}</style>
</head><body>
<div id="chart"></div>
<script>
const container = document.getElementById('chart');
const chart = LightweightCharts.createChart(container, {{
  width: container.offsetWidth, height: container.offsetHeight,
  layout: {{background:{{type:'solid',color:'#000'}}, textColor:'#787b86', fontFamily:'Inter,sans-serif', fontSize:11}},
  grid: {{vertLines:{{color:'#111'}}, horzLines:{{color:'#111'}}}},
  rightPriceScale: {{borderColor:'#1e1e2e'}},
  timeScale: {{borderColor:'#1e1e2e', timeVisible:true}},
  crosshair: {{vertLine:{{color:'#333',style:2}}, horzLine:{{color:'#333',style:2}}}},
}});
chart.addAreaSeries({{
  lineColor:'{color}', topColor:'{color}33', bottomColor:'transparent',
  lineWidth:2, lastValueVisible:true, priceLineVisible:false,
}}).setData({json.dumps(points)});
chart.timeScale().fitContent();
window.addEventListener('resize', () => chart.applyOptions({{width:container.offsetWidth, height:container.offsetHeight}}));
</script>
</body></html>"""
    st.components.v1.html(html, height=240, scrolling=False)


# ── Main ──────────────────────────────────────────────────────────────────────

c1, c2, c3, _spacer = st.columns([1.2, 2.2, 1.2, 5.4])  # trailing spacer
# normalizes to total weight 10, matching every other page's filter row
# (see dashboard/1_Chart.py) so the Symbol dropdown is pixel-aligned
# across pages, not just proportioned relative to this page's own filters.
with c1:
    symbol = st.selectbox("Symbol", list(ASSETS.keys()), label_visibility="collapsed")
with c2:
    mode = st.selectbox("Mode", list(MODE_LABELS.keys()), format_func=lambda m: MODE_LABELS[m], label_visibility="collapsed")
with c3:
    period = st.selectbox("Period", ["full", "test"], format_func=lambda p: "Full Period" if p == "full" else "Held-Out Test", label_visibility="collapsed")

db_name = ASSETS[symbol]
run = load_run(db_name, symbol, mode, period)

if not run:
    st.warning(f"No backtest_runs row for {symbol}/{mode}/{period} — run scripts/backtest/run_structural_backtest.py first.")
    st.stop()

pass_floor = bool(run["meets_min_sample_floor"])
banner_cls = "pass" if pass_floor else "fail"
floor_text = "MEETS" if pass_floor else "BELOW"

st.markdown(f"""
<div class="hero-banner {banner_cls}">
  <span class="hero-verdict {banner_cls}">{floor_text} the ~200-trades/12-month floor</span>
  <span class="hero-sub">{run['n_wins'] + run['n_losses']} decided trades over {(run['period_end'] - run['period_start']).days}d
  ({run['min_sample_floor_required']} required) — mechanism/metrics view, not an endorsement of edge.
  See Variant Comparison for the multiple-comparisons caveat; the held-out test period is still within
  the same one-directional regime as the full period, not genuinely out-of-regime.</span>
</div>
""", unsafe_allow_html=True)

m1, m2, m3, m4, m5, m6, m7, m8 = st.columns(8)
metrics = [
    (m1, "Trades", f"{run['n_trades_taken']}", f"{run['n_wins']}W / {run['n_losses']}L / {run['n_open_at_data_end']} open"),
    (m2, "Win Rate", f"{float(run['win_rate'])*100:.1f}%" if run['win_rate'] is not None else "—", ""),
    (m3, "Profit Factor", f"{float(run['profit_factor']):.2f}" if run['profit_factor'] is not None else "—", ""),
    (m4, "Expectancy", f"{float(run['expectancy_r']):+.3f}R" if run['expectancy_r'] is not None else "—", "per trade"),
    (m5, "Max Drawdown", f"{float(run['max_drawdown_r']):.2f}R" if run['max_drawdown_r'] is not None else "—", ""),
    (m6, "Sharpe", f"{float(run['sharpe_ratio']):.3f}" if run['sharpe_ratio'] is not None else "—", "per-trade, not annualized"),
    (m7, "Deflated Sharpe", f"{float(run['deflated_sharpe_ratio']):.3f}" if run['deflated_sharpe_ratio'] is not None else "—", f"N={run['n_trials_for_dsr']} trials"),
    (m8, "Skipped (overlap)", f"{run['n_trades_skipped_overlap']}", "1 trade at a time"),
]
for col, label, value, sub in metrics:
    with col:
        st.markdown(f"""<div class="metric-card"><div class="metric-label">{label}</div>
<div class="metric-value metric-value-8up">{value}</div><div class="metric-sub">{sub}</div></div>""", unsafe_allow_html=True)

st.markdown("")

trades = load_trades(db_name, symbol, mode)
if period == "test":
    trades = trades[trades["entry_bar_datetime"] >= pd.Timestamp(run["oos_cutoff_date"])]
decided = trades[trades["exit_reason"].isin(["win", "loss"])].reset_index(drop=True)

if decided.empty:
    st.info("No decided trades in this period yet.")
    st.stop()

tab_trades, tab_time, tab_equity, tab_variants = st.tabs(
    ["Trade Analysis", "Time & Periods", "Equity Curve", "Variant Comparison"]
)

# ── R-multiple distribution + streaks/drawdown ───────────────────────────────

with tab_trades:
    left, right = st.columns([1.4, 1])
    with left:
        st.markdown('<div class="panel-title">R-Multiple Distribution</div>', unsafe_allow_html=True)
        bins = [-1.5, -1.0, -0.5, 0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 100.0]
        labels = ["<-1.0", "-1.0", "-0.5 to 0", "0 to 0.25", "0.25-0.5", "0.5-0.75", "0.75-1.0",
                  "1.0-1.5", "1.5-2.0", "2.0-3.0", "3.0-5.0", "5.0-10.0", ">10.0"]
        binned = pd.cut(decided["r_outcome"], bins=bins, labels=labels, right=True, include_lowest=True)
        dist = binned.value_counts().reindex(labels).fillna(0).astype(int)
        st.bar_chart(dist)

    with right:
        st.markdown('<div class="panel-title">Streaks &amp; Recovery</div>', unsafe_allow_html=True)
        max_win_streak, max_loss_streak = compute_streaks(decided["r_outcome"].values)
        trades_to_rec, days_to_rec = compute_drawdown_recovery(decided)
        rec_trades_txt = f"{trades_to_rec} trades" if trades_to_rec is not None else "not yet recovered"
        rec_days_txt = f"{days_to_rec:.1f}d" if days_to_rec is not None else "—"
        st.markdown(f"""
- **Max consecutive wins:** {max_win_streak}
- **Max consecutive losses:** {max_loss_streak}
- **Largest drawdown recovery:** {rec_trades_txt} ({rec_days_txt} calendar time)
""")
        best = decided.loc[decided["r_outcome"].idxmax()]
        worst = decided.loc[decided["r_outcome"].idxmin()]
        st.markdown(f"""
- **Best trade:** {best['r_outcome']:+.2f}R ({best['direction']}, entered {str(best['entry_bar_datetime'])[:16]})
- **Worst trade:** {worst['r_outcome']:+.2f}R ({worst['direction']}, entered {str(worst['entry_bar_datetime'])[:16]})
""")

# ── Time-in-market + weekly/monthly breakdown ────────────────────────────────

with tab_time:
    st.markdown('<div class="panel-title">Time-in-Market</div>', unsafe_allow_html=True)

    period_start, period_end = pd.Timestamp(run["period_start"]), pd.Timestamp(run["period_end"])
    total_duration_days = (period_end - period_start).total_seconds() / 86400.0
    in_market_days = (decided["exit_bar_datetime"] - decided["entry_bar_datetime"]).dt.total_seconds().sum() / 86400.0
    time_in_market_pct = (in_market_days / total_duration_days * 100) if total_duration_days > 0 else 0

    st.caption(f"Time in market: {time_in_market_pct:.1f}% ({in_market_days:.1f}d of {total_duration_days:.1f}d period)")

    wk_col, mo_col = st.columns(2)
    with wk_col:
        st.markdown('<div class="panel-title">Weekly Breakdown</div>', unsafe_allow_html=True)
        render_period_breakdown(decided, "W", "Week", "week")
    with mo_col:
        st.markdown('<div class="panel-title">Monthly Breakdown</div>', unsafe_allow_html=True)
        render_period_breakdown(decided, "M", "Month", "month")

# ── USD equity curve ─────────────────────────────────────────────────────────

with tab_equity:
    st.markdown('<div class="panel-title">Equity Curve — USD at fixed 0.01 lot (display convenience, not a sizing feature)</div>', unsafe_allow_html=True)
    render_usd_equity_curve(decided, symbol)

# ── Variant comparison ───────────────────────────────────────────────────────

with tab_variants:
    st.markdown('<div class="panel-title">Structural TP Variant Comparison</div>', unsafe_allow_html=True)
    st.markdown("""
<div class="caveat-box">
  <b>Multiple-comparisons caveat:</b> testing 4 stop/target variants against the same ~6-month,
  single-regime history is itself a form of multiple comparisons. The Deflated Sharpe Ratio shown
  per variant corrects only for the Mode A vs Mode B selection <i>within</i> that variant (N=2) —
  it does NOT know 4 variants were tried side by side here. A variant that looks best below has not
  been shown to be more real than the others; it may simply fit this specific bull-run window best.
  No variant is recommended.
</div>
""", unsafe_allow_html=True)

    variants = load_variant_comparison(db_name, symbol, mode)
    if variants.empty:
        st.info(f"No variant comparison persisted for {symbol}/{mode} — run "
                f"scripts/backtest/compare_structural_tp_variants.py --write (gold only has been run so far).")
    else:
        v = variants[variants["period"] == period].copy()
        v = v[["variant", "trades_taken", "win_rate", "profit_factor", "expectancy_r", "max_drawdown_r",
               "sharpe_ratio", "deflated_sharpe_ratio"]]
        v["win_rate"] = (v["win_rate"].astype(float) * 100).round(1)
        for col in ("profit_factor", "expectancy_r", "max_drawdown_r", "sharpe_ratio", "deflated_sharpe_ratio"):
            v[col] = v[col].astype(float).round(4)
        v.columns = ["Variant", "Trades", "Win Rate %", "Profit Factor", "Expectancy R", "Max DD R", "Sharpe", "DSR"]
        st.dataframe(v, use_container_width=True, hide_index=True)
