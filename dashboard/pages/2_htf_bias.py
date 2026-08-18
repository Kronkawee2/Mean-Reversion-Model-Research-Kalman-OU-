"""
HTF Bias — current confluence score and full component breakdown for the
selected symbol, read directly from curated_<symbol>.htf_bias (h1, the
project's established primary/authoritative HTF timeframe). New page,
not a rebuild of anything -- the old dashboard never had an HTF Bias view
since htf_bias_engine.py didn't exist yet when app.py was first written.
"""

import os, sys, json
import pymysql, pymysql.cursors
import pandas as pd
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

DASH = Path(__file__).parent.parent
if str(DASH) not in sys.path:
    sys.path.insert(0, str(DASH))
if str(DASH.parent) not in sys.path:
    sys.path.insert(0, str(DASH.parent))
load_dotenv(DASH.parent / ".env")

st.set_page_config(
    page_title="HTF Bias",
    page_icon="B",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
  .stApp { background:#000; font-family:'Inter',sans-serif; }
  header[data-testid="stHeader"] { background:#000; }
  .block-container { padding:2.6rem 1rem 0 1rem; max-width:100%; }

  .bias-hero {
    display:flex; align-items:baseline; gap:18px;
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:8px;
    padding:22px 26px; margin-bottom:16px;
  }
  .bias-badge {
    font-size:15px; font-weight:700; padding:6px 16px; border-radius:5px;
    text-transform:uppercase; letter-spacing:0.05em;
  }
  .bias-bullish { background:rgba(38,166,154,0.18); color:#26a69a; }
  .bias-bearish { background:rgba(239,83,80,0.18);  color:#ef5350; }
  .bias-neutral { background:rgba(120,123,134,0.18); color:#787b86; }
  .bias-score { font-size:34px; font-weight:700; color:#d1d4dc; font-variant-numeric:tabular-nums; }
  .bias-meta   { font-size:12px; color:#555; margin-left:auto; text-align:right; line-height:1.6; }

  .metric-card {
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:6px;
    padding:14px 16px; text-align:center; height:100%;
  }
  .metric-label { font-size:11px; color:#555; margin-bottom:4px; }
  .metric-value { font-size:22px; font-weight:700; color:#d1d4dc; }
  .metric-sub   { font-size:11px; color:#787b86; margin-top:2px; }

  .panel-title {
    font-size:11px; font-weight:600; letter-spacing:0.08em;
    color:#787b86; text-transform:uppercase; margin-bottom:10px;
    border-bottom:1px solid #1e1e2e; padding-bottom:6px;
  }
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


def _conn(db_name):
    return pymysql.connect(**DB, database=db_name, cursorclass=pymysql.cursors.DictCursor)


@st.cache_data(ttl=30)
def load_latest_bias(db_name: str, symbol: str) -> dict:
    conn = _conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM htf_bias WHERE symbol=%s AND timeframe='h1' "
                "ORDER BY bar_datetime DESC LIMIT 1",
                (symbol,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return row


@st.cache_data(ttl=30)
def load_bias_history(db_name: str, symbol: str, n: int = 200) -> pd.DataFrame:
    conn = _conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bar_datetime, confluence_score, bias FROM htf_bias "
                "WHERE symbol=%s AND timeframe='h1' ORDER BY bar_datetime DESC LIMIT %s",
                (symbol, n),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["bar_datetime"] = pd.to_datetime(df["bar_datetime"])
    return df.sort_values("bar_datetime").reset_index(drop=True)


def render_score_history(df: pd.DataFrame):
    points = [{"time": int(r["bar_datetime"].timestamp()), "value": float(r["confluence_score"])}
              for _, r in df.iterrows()]
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
const zeroLine = chart.addLineSeries({{color:'#333', lineWidth:1, lastValueVisible:false, priceLineVisible:false}});
zeroLine.setData([{{time:{points[0]['time'] if points else 0}, value:0}}, {{time:{points[-1]['time'] if points else 0}, value:0}}]);
const series = chart.addAreaSeries({{
  lineColor:'#d4b16a', topColor:'rgba(212,177,106,0.25)', bottomColor:'transparent',
  lineWidth:2, lastValueVisible:true, priceLineVisible:false,
}});
series.setData({json.dumps(points)});
chart.timeScale().fitContent();
window.addEventListener('resize', () => chart.applyOptions({{width:container.offsetWidth, height:container.offsetHeight}}));
</script>
</body></html>"""
    st.components.v1.html(html, height=220, scrolling=False)


# ── Main ──────────────────────────────────────────────────────────────────────

c1, c2 = st.columns([1.2, 8.8])
with c1:
    symbol = st.selectbox("Symbol", list(ASSETS.keys()), label_visibility="collapsed")
db_name = ASSETS[symbol]

row = load_latest_bias(db_name, symbol)
if not row:
    st.warning(f"No htf_bias rows for {symbol} yet — run the detection pipeline first.")
    st.stop()

bias = row["bias"]
score = float(row["confluence_score"])
badge_class = {"bullish": "bias-bullish", "bearish": "bias-bearish", "neutral": "bias-neutral"}[bias]

st.markdown(f"""
<div class="bias-hero">
  <span class="bias-badge {badge_class}">{bias}</span>
  <span class="bias-score">{score:+.2f}</span>
  <span class="bias-meta">
    h1 bar: {row['bar_datetime']}<br>
    session: {row['session']} (×{float(row['session_multiplier']):.2f})
  </span>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="panel-title">Confluence Score History (last 200 h1 bars)</div>', unsafe_allow_html=True)
hist = load_bias_history(db_name, symbol)
if not hist.empty:
    render_score_history(hist)
else:
    st.info("Not enough history yet.")

st.markdown("")
st.markdown('<div class="panel-title">Component Breakdown</div>', unsafe_allow_html=True)

m1, m2, m3, m4, m5, m6 = st.columns(6)
components = [
    (m1, "SMC", row["smc_contribution"],
     f"{row['smc_active_bullish_zones']} bull / {row['smc_active_bearish_zones']} bear zones"),
    (m2, "CRT", row["crt_contribution"],
     row["crt_equilibrium_bias"] or "—"),
    (m3, "Indicator", row["indicator_contribution"], "trend"),
    (m4, "Volume Profile", row["volume_profile_contribution"], "—"),
    (m5, "Hidden Divergence", row["hidden_divergence_contribution"],
     f"{row['hidden_divergence_count']} signal(s)"),
    (m6, "Liquidity Sweep", row["liquidity_sweep_contribution"],
     row["liquidity_sweep_direction"] or "none in window"),
]
for col, label, value, sub in components:
    v = float(value)
    color = "#26a69a" if v > 0 else "#ef5350" if v < 0 else "#787b86"
    with col:
        st.markdown(f"""
<div class="metric-card">
  <div class="metric-label">{label}</div>
  <div class="metric-value" style="color:{color}">{v:+.2f}</div>
  <div class="metric-sub">{sub}</div>
</div>""", unsafe_allow_html=True)

st.markdown("")
r1, r2, r3 = st.columns(3)
with r1:
    st.markdown(f"""
<div class="metric-card">
  <div class="metric-label">Raw Score (before caution)</div>
  <div class="metric-value">{float(row['raw_score_before_caution']):+.2f}</div>
  <div class="metric-sub">clipped to ±100 for final score</div>
</div>""", unsafe_allow_html=True)
with r2:
    st.markdown(f"""
<div class="metric-card">
  <div class="metric-label">Regular Divergence Caution</div>
  <div class="metric-value">×{float(row['regular_divergence_caution_factor']):.3f}</div>
  <div class="metric-sub">{row['regular_divergence_count']} regular divergence signal(s) in window</div>
</div>""", unsafe_allow_html=True)
with r3:
    st.markdown(f"""
<div class="metric-card">
  <div class="metric-label">Session Multiplier</div>
  <div class="metric-value">×{float(row['session_multiplier']):.2f}</div>
  <div class="metric-sub">applied to CRT + liquidity sweep only</div>
</div>""", unsafe_allow_html=True)
