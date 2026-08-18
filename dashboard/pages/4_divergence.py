"""
Divergence — recent signals across the 17 working divergence models
(curated_<symbol>.divergence_signals), filterable by timeframe/type/class/
direction. New page (the old dashboard never had a dedicated divergence
view -- divergence was folded into the old 7-point confluence scorer).

"Active" doesn't map onto divergence_signals directly -- unlike SMC zones
(state='active'/'mitigated'/'invalidated'), a divergence signal is a
point-in-time confirmed event, not a stateful object with a lifecycle. So
this page shows the most RECENT signals (default: last 30 days) rather
than a persisted "active" flag -- the practical equivalent for a
dashboard view.

Also carries the MTF Alignment Divergence negative finding in-dashboard
(previously only in analysis/divergence/technical_divergence_state.py and
docs/DECISIONS.md), per the user's explicit request to make it visible
here too, not just in code comments someone has to go looking for.
"""

import os, sys
import pymysql, pymysql.cursors
import pandas as pd
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

DASH = Path(__file__).parent.parent
if str(DASH) not in sys.path:
    sys.path.insert(0, str(DASH))
load_dotenv(DASH.parent / ".env")

st.set_page_config(
    page_title="Divergence",
    page_icon="D",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
  .stApp { background:#000; font-family:'Inter',sans-serif; }
  header[data-testid="stHeader"] { background:#000; }
  .block-container { padding:2.6rem 1rem 0 1rem; max-width:100%; }

  .div-row {
    display:grid; grid-template-columns: 130px 90px 90px 90px 1fr 1fr;
    gap:10px; align-items:center; padding:8px 10px;
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:5px; margin-bottom:6px;
    font-size:12px;
  }
  .div-bull { color:#26a69a; font-weight:700; }
  .div-bear { color:#ef5350; font-weight:700; }
  .div-class-regular { color:#d4b16a; }
  .div-class-hidden  { color:#8ca9c5; }
  .div-lbl { color:#555; font-size:10px; }

  .panel-title {
    font-size:11px; font-weight:600; letter-spacing:0.08em; color:#787b86;
    text-transform:uppercase; margin-bottom:10px; border-bottom:1px solid #1e1e2e; padding-bottom:6px;
  }
  .mtf-note {
    background:#140d0d; border:1px solid #2e1e1e; border-radius:6px;
    padding:14px 16px; margin-bottom:16px; font-size:12px; color:#a08080; line-height:1.6;
  }
  .mtf-note b { color:#d4b16a; }
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

# Kept in sync with the real distinct divergence_type values in the DB,
# not the original 11-model design doc -- 6 models were added later
# (xau_gpr, xau_xag, xau_tips, xau_fedfunds, xau_cpi, eur_yield_spread,
# see analysis/divergence/intermarket_divergence_state.py's module
# docstring) and this map silently fell behind them, so any of those 6
# rendered as a raw internal code instead of a label until this fix (see
# docs/DECISIONS.md). Re-check this map against
# `SELECT DISTINCT divergence_type FROM divergence_signals` if a new
# model is ever added.
MODEL_LABELS = {
    "rsi": "RSI (Technical)", "obv": "OBV (Technical)", "stochastic": "Stochastic (Technical)",
    "cci": "CCI (Technical)", "xau_dxy": "XAU vs DXY", "eur_dxy": "EUR vs DXY",
    "xau_us10y": "XAU vs US10Y", "xau_gdx": "XAU vs GDX", "xau_spdr": "XAU vs SPDR GLD",
    "cot_gold": "COT Gold", "cot_eur": "COT EUR",
    "xau_gpr": "XAU vs GPR (Geopolitical Risk)",
    "xau_xag": "XAU vs XAG (Silver)",
    "xau_tips": "XAU vs TIPS (Real Yield)",
    "xau_fedfunds": "XAU vs Fed Funds Rate (unconfirmed)",
    "xau_cpi": "XAU vs CPI (unconfirmed)",
    "eur_yield_spread": "EUR vs US-EU Yield Spread",
}


def _conn(db_name):
    return pymysql.connect(**DB, database=db_name, cursorclass=pymysql.cursors.DictCursor)


@st.cache_data(ttl=30)
def load_recent_divergence(db_name: str, symbol: str, days: int) -> pd.DataFrame:
    conn = _conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT timeframe, bar_datetime, divergence_type, divergence_class, direction, "
                "curr_pivot_datetime, curr_pivot_price, curr_pivot_indicator "
                "FROM divergence_signals WHERE symbol=%s AND bar_datetime >= DATE_SUB(NOW(), INTERVAL %s DAY) "
                "ORDER BY bar_datetime DESC",
                (symbol, days),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["bar_datetime"] = pd.to_datetime(df["bar_datetime"])
    return df


@st.cache_data(ttl=300)
def load_model_coverage(db_name: str, symbol: str) -> pd.DataFrame:
    conn = _conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT divergence_type, timeframe, COUNT(*) n, MAX(bar_datetime) latest "
                "FROM divergence_signals WHERE symbol=%s GROUP BY divergence_type, timeframe "
                "ORDER BY divergence_type",
                (symbol,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


# ── MTF Alignment Divergence note ────────────────────────────────────────────

st.markdown("""
<div class="mtf-note">
  <b>MTF Alignment Divergence — deferred (negative empirical finding, not unfinished work).</b><br>
  A candidate model (HTF Hidden Divergence confluence with LTF Regular Divergence, indicator-matched)
  was fully designed and empirically tested before building any persistence pipeline: for 5
  indicator×symbol combinations (RSI/OBV/Stochastic/CCI on gold, RSI on EURUSD), the real
  HTF/LTF match rate was compared against a random-null baseline across window candidates
  5h–720h. <b>None showed a meaningful positive lift over random chance</b> at any operationally
  useful window — real match rates sat at or below the null baseline out to ~320h in every case.
  It stays deferred on this basis. The matrix currently has 17 working models (14 for XAUUSD,
  7 for EURUSD, 4 technical models shared by both) — see
  <code>analysis/divergence/intermarket_divergence_state.py</code> for the full model list and
  <code>docs/DECISIONS.md</code> for the full MTF writeup, and
  <code>scripts/diagnostic/test_mtf_alignment_divergence_lift.py</code>
  to re-run the MTF test if more history accumulates later.
</div>
""", unsafe_allow_html=True)

# ── Main ──────────────────────────────────────────────────────────────────────

c1, c2, c3, c4, c5 = st.columns([1.2, 1.4, 1.4, 1.4, 1.4])
with c1:
    symbol = st.selectbox("Symbol", list(ASSETS.keys()), label_visibility="collapsed")
db_name = ASSETS[symbol]

coverage = load_model_coverage(db_name, symbol)
available_types = sorted(coverage["divergence_type"].unique()) if not coverage.empty else []

with c2:
    f_type = st.selectbox("Model", ["All"] + available_types, format_func=lambda t: MODEL_LABELS.get(t, t) if t != "All" else "All models")
with c3:
    f_class = st.selectbox("Class", ["All", "regular", "hidden"], format_func=lambda c: c if c == "All" else c.title())
with c4:
    f_dir = st.selectbox("Direction", ["All", "bullish", "bearish"], format_func=lambda d: d if d == "All" else d.title())
with c5:
    days = st.selectbox("Window", [7, 30, 90, 365], index=1, format_func=lambda d: f"Last {d}d")

df = load_recent_divergence(db_name, symbol, days)
if f_type != "All":
    df = df[df["divergence_type"] == f_type]
if f_class != "All":
    df = df[df["divergence_class"] == f_class]
if f_dir != "All":
    df = df[df["direction"] == f_dir]

st.markdown(f'<div class="panel-title">Recent Signals ({len(df)} in last {days}d)</div>', unsafe_allow_html=True)

if df.empty:
    st.info("No divergence signals in this window/filter combination.")
else:
    for _, r in df.head(100).iterrows():
        dir_class = "div-bull" if r["direction"] == "bullish" else "div-bear"
        cls_class = f"div-class-{r['divergence_class']}"
        st.markdown(f"""
<div class="div-row">
  <span>{MODEL_LABELS.get(r['divergence_type'], r['divergence_type'])}</span>
  <span style="text-transform:uppercase;font-size:10px;color:#787b86;">{r['timeframe']}</span>
  <span class="{cls_class}">{r['divergence_class']}</span>
  <span class="{dir_class}">{r['direction']}</span>
  <span><span class="div-lbl">bar</span> {str(r['bar_datetime'])[:16]}</span>
  <span><span class="div-lbl">pivot</span> {str(r['curr_pivot_datetime'])[:16]} @ {r['curr_pivot_price']:.5f}</span>
</div>
""", unsafe_allow_html=True)

st.markdown("")
st.markdown('<div class="panel-title">Model Coverage (all-time)</div>', unsafe_allow_html=True)
if not coverage.empty:
    coverage_display = coverage.copy()
    coverage_display["model"] = coverage_display["divergence_type"].map(lambda t: MODEL_LABELS.get(t, t))
    coverage_display = coverage_display[["model", "timeframe", "n", "latest"]]
    coverage_display.columns = ["Model", "Timeframe", "Total Signals", "Latest"]
    st.dataframe(coverage_display, use_container_width=True, hide_index=True)
else:
    st.info("No divergence data yet — run the detection pipeline first.")
