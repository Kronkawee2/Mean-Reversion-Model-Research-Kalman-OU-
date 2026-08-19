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
here too, not just in code comments someone has to go looking for -- moved
into a collapsed expander (2026-08 redesign) so it no longer forces every
visitor to scroll past a full negative-finding essay before reaching the
actual page content; still one click away, not buried in a code comment.

2026-08 redesign: added a hero stat row (mirrors the Chart/LTF Triggers
"info bar" pattern already established elsewhere) and switched the
signal list from thin data-grid rows to the same card style LTF Triggers
uses, for visual consistency across the dashboard.
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

  .hero-bar {
    display:flex; align-items:center; gap:14px; padding:7px 14px;
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:4px;
    margin-bottom:16px; font-size:13px; font-variant-numeric:tabular-nums;
  }
  .hero-bar .lbl { color:#555; font-size:11px; }
  .hero-bar .sep { width:1px; height:20px; background:#1e1e2e; }
  .hero-bull { color:#26a69a; font-weight:700; }
  .hero-bear { color:#ef5350; font-weight:700; }

  .split-bar-wrap { margin-bottom:16px; }
  .split-bar {
    display:flex; height:22px; border-radius:4px; overflow:hidden;
    background:#0d0d14; border:1px solid #1e1e2e;
  }
  .split-bar-bull { background:#1a4d3f; display:flex; align-items:center; justify-content:center;
                     font-size:11px; font-weight:700; color:#5fc9a4; transition:width 0.3s ease; }
  .split-bar-bear { background:#4d1a1a; display:flex; align-items:center; justify-content:center;
                     font-size:11px; font-weight:700; color:#ef8a85; transition:width 0.3s ease; }
  .split-bar-lbl { display:flex; justify-content:space-between; font-size:10px; color:#555; margin-top:4px; }

  .model-bar-row { display:flex; align-items:center; gap:10px; margin-bottom:5px; }
  .model-bar-name { width:170px; font-size:11px; color:#aaa; text-align:right; flex-shrink:0; }
  .model-bar-track { flex:1; height:14px; background:#0d0d14; border-radius:3px; overflow:hidden; }
  .model-bar-fill { display:block; height:100%; background:#d4b16a; border-radius:3px; }
  /* <span> is inline by default -- CSS width is ignored on inline elements
     entirely, so without this the fill bar never rendered at all (only its
     track background showed, uniform gray regardless of count). Caught by
     actually opening the page and looking, not assumed from the code. */
  .model-bar-count { width:28px; font-size:11px; color:#787b86; }

  .div-card {
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:6px;
    padding:10px 14px; margin-bottom:8px;
    display:flex; align-items:center; gap:14px; flex-wrap:wrap;
    transition:border-color 0.15s ease, background-color 0.15s ease;
  }
  .div-card:hover { border-color:#333; background:#111118; }
  .div-dir-bull { color:#26a69a; font-weight:700; font-size:14px; min-width:64px; }
  .div-dir-bear { color:#ef5350; font-weight:700; font-size:14px; min-width:64px; }
  .div-model { color:#d1d4dc; font-size:13px; font-weight:600; flex:1; min-width:160px; }
  .div-badge {
    display:inline-block; font-size:9px; font-weight:700; padding:2px 7px; border-radius:3px;
    text-transform:uppercase; letter-spacing:0.03em;
  }
  .div-badge-regular { background:#2e2200; color:#d4b16a; border:1px solid #55420c; }
  .div-badge-hidden  { background:#0d1c26; color:#8ca9c5; border:1px solid #1e3a4d; }
  .div-tf { background:#1a1a2e; color:#787b86; font-size:10px; padding:2px 7px; border-radius:3px; }
  .div-meta { color:#555; font-size:11px; margin-left:auto; text-align:right; white-space:nowrap; }
  .div-meta b { color:#8ca9c5; font-weight:600; }

  .panel-title {
    font-size:11px; font-weight:600; letter-spacing:0.08em; color:#787b86;
    text-transform:uppercase; margin-bottom:10px; border-bottom:1px solid #1e1e2e; padding-bottom:6px;
  }
  .mtf-note {
    background:#140d0d; border:1px solid #2e1e1e; border-radius:6px;
    padding:14px 16px; font-size:12px; color:#a08080; line-height:1.6;
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


# ── Top selectors ────────────────────────────────────────────────────────────

c1, c2, c3, c4, c5, _spacer = st.columns([1.2, 1.4, 1.4, 1.4, 1.4, 3.2])  # trailing
# spacer normalizes the row to total weight 10 -- same convention as
# dashboard/1_Chart.py's [1.2, 1.0, 7.8] -- so the Symbol dropdown (weight
# 1.2) is the same fraction of row width on every page, not just the same
# ratio relative to that page's own other filters.
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

# ── Hero stat bar ─────────────────────────────────────────────────────────────

n_bull = int((df["direction"] == "bullish").sum()) if not df.empty else 0
n_bear = int((df["direction"] == "bearish").sum()) if not df.empty else 0
top_model = (MODEL_LABELS.get(df["divergence_type"].mode().iat[0], df["divergence_type"].mode().iat[0])
             if not df.empty else "—")
n_models_active = int(df["divergence_type"].nunique()) if not df.empty else 0

st.markdown(f"""
<div class="hero-bar">
  <span><span class="lbl">Signals ({days}d)</span>&nbsp;<b>{len(df)}</b></span>
  <span class="sep"></span>
  <span class="hero-bull">▲ {n_bull} bullish</span>
  <span class="hero-bear">▼ {n_bear} bearish</span>
  <span class="sep"></span>
  <span><span class="lbl">Models Active</span>&nbsp;<b>{n_models_active}</b></span>
  <span class="sep"></span>
  <span><span class="lbl">Most Frequent</span>&nbsp;<b style="color:#d4b16a">{top_model}</b></span>
</div>
""", unsafe_allow_html=True)

# Visual bullish/bearish split + top-models bar chart -- added per explicit
# feedback that the hero bar's plain numbers were hard to read at a glance;
# a proportional bar and a horizontal frequency chart make the same numbers
# visible as shapes, not just text you have to parse.
bull_pct = (n_bull / len(df) * 100) if len(df) else 50
bear_pct = 100 - bull_pct
st.markdown(f"""
<div class="split-bar-wrap">
  <div class="split-bar">
    <div class="split-bar-bull" style="width:{bull_pct:.1f}%">{f'{bull_pct:.0f}%' if bull_pct > 12 else ''}</div>
    <div class="split-bar-bear" style="width:{bear_pct:.1f}%">{f'{bear_pct:.0f}%' if bear_pct > 12 else ''}</div>
  </div>
  <div class="split-bar-lbl"><span>▲ Bullish</span><span>Bearish ▼</span></div>
</div>
""", unsafe_allow_html=True)

if not df.empty:
    model_counts = df["divergence_type"].value_counts().head(6)
    max_count = int(model_counts.max())
    bars_html = ""
    for model_type, count in model_counts.items():
        pct = count / max_count * 100
        label = MODEL_LABELS.get(model_type, model_type)
        bars_html += (f'<div class="model-bar-row"><span class="model-bar-name">{label}</span>'
                      f'<span class="model-bar-track"><span class="model-bar-fill" style="width:{pct:.0f}%"></span></span>'
                      f'<span class="model-bar-count">{count}</span></div>')
    st.markdown(f'<div class="panel-title">Top Models by Signal Count</div>{bars_html}', unsafe_allow_html=True)

# ── Signal cards ──────────────────────────────────────────────────────────────

st.markdown("")
st.markdown(f'<div class="panel-title">Recent Signals ({len(df)} in last {days}d)</div>', unsafe_allow_html=True)

if df.empty:
    st.markdown(
        '<div style="text-align:center;color:#333;padding:60px 0;font-size:14px;">'
        'No divergence signals in this window/filter combination.</div>',
        unsafe_allow_html=True,
    )
else:
    with st.container(height=520, border=False):
        for _, r in df.head(150).iterrows():
            dir_class = "div-dir-bull" if r["direction"] == "bullish" else "div-dir-bear"
            dir_arrow = "▲ BULL" if r["direction"] == "bullish" else "▼ BEAR"
            cls_badge = f'<span class="div-badge div-badge-{r["divergence_class"]}">{r["divergence_class"]}</span>'
            st.markdown(f"""
<div class="div-card">
  <span class="{dir_class}">{dir_arrow}</span>
  <span class="div-model">{MODEL_LABELS.get(r['divergence_type'], r['divergence_type'])}</span>
  <span class="div-tf">{r['timeframe'].upper()}</span>
  {cls_badge}
  <span class="div-meta">bar <b>{str(r['bar_datetime'])[:16]}</b> · pivot {str(r['curr_pivot_datetime'])[:16]} @ {r['curr_pivot_price']:.5f}</span>
</div>
""", unsafe_allow_html=True)

# ── Model coverage ────────────────────────────────────────────────────────────

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

# ── MTF Alignment Divergence note ────────────────────────────────────────────
# Moved to the bottom of the page (2026-08) -- was sitting right under the
# hero bar, cluttering the view every visitor sees first. Kept on the page
# at all (not removed outright) per the user's earlier explicit request to
# surface this negative finding in-dashboard, not just in code comments --
# bottom + collapsed expander satisfies both asks: out of the way, still
# one click from anyone who scrolls down.

st.markdown("")
with st.expander("⚠ MTF Alignment Divergence — deferred (click for the negative empirical finding)"):
    st.markdown("""
<div class="mtf-note">
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
