"""
Stats — Signal performance dashboard: winrate, equity curve, history log.
"""

import os, sys, json
import pymysql, pymysql.cursors
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from dotenv import load_dotenv

DASH = Path(__file__).parent.parent          # dashboard/
if str(DASH) not in sys.path:
    sys.path.insert(0, str(DASH))
if str(DASH.parent) not in sys.path:
    sys.path.insert(0, str(DASH.parent))    # project root
load_dotenv(DASH.parent / ".env")

from signal_store import load_signals, evaluate_pending_from_db

st.set_page_config(
    page_title="stats",
    page_icon="S",
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
    padding:14px 16px; text-align:center;
  }
  .metric-label { font-size:11px; color:#555; margin-bottom:4px; }
  .metric-value { font-size:26px; font-weight:700; color:#d1d4dc; }
  .metric-sub   { font-size:11px; color:#787b86; margin-top:2px; }

  .panel-title {
    font-size:11px; font-weight:600; letter-spacing:0.08em;
    color:#787b86; text-transform:uppercase; margin-bottom:12px;
    border-bottom:1px solid #1e1e2e; padding-bottom:6px;
  }

  .cond-row {
    display:flex; justify-content:space-between; align-items:center;
    padding:6px 0; border-bottom:1px solid #0d0d14;
    font-size:12px; color:#d1d4dc;
  }
  .cond-bar-wrap { flex:1; margin:0 12px; background:#1a1a2e; border-radius:3px; height:5px; }
  .cond-bar      { height:5px; border-radius:3px; }

  .status-win     { color:#26a69a; font-weight:600; }
  .status-loss    { color:#ef5350; font-weight:600; }
  .status-pending { color:#d4b16a; font-weight:600; }
  footer { visibility:hidden; } #MainMenu { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

DB = {
    "host":    os.getenv("DB_HOST", "localhost"),
    "port":    int(os.getenv("DB_PORT", 3306)),
    "user":    os.getenv("DB_USER", "root"),
    "password":os.getenv("DB_PASSWORD", ""),
    "charset": "utf8mb4",
}
ASSETS_DB = {
    "XAUUSD": {"db": "gold",   "dec": 2},
    "EURUSD": {"db": "eurusd", "dec": 5},
}
TF_MAP = {"5m": "m5", "15m": "m15", "1h": "h1", "4h": "h4", "1D": "d1"}


@st.cache_data(ttl=60)
def load_ohlcv(db_name, table, limit=500):
    try:
        conn = pymysql.connect(**DB, database=db_name, cursorclass=pymysql.cursors.DictCursor)
        cur  = conn.cursor()
        cur.execute(
            f"SELECT price_datetime,high_price,low_price FROM `{table}` "
            f"ORDER BY price_datetime DESC LIMIT {limit}"
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        df = pd.DataFrame(rows)
        if df.empty: return df
        df["price_datetime"] = pd.to_datetime(df["price_datetime"])
        df["high_price"] = df["high_price"].astype(float)
        df["low_price"]  = df["low_price"].astype(float)
        return df.sort_values("price_datetime").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def render_equity_curve(signals: list):
    closed = [s for s in signals if s["status"] in ("WIN", "LOSS") and s.get("pnl_pts") is not None]
    if not closed:
        st.info("No closed signals yet — equity curve will appear here.")
        return

    sorted_sigs = sorted(closed, key=lambda x: x.get("closed_at", ""))
    cumulative  = 0.0
    eq_data     = []

    for s in sorted_sigs:
        cumulative += float(s["pnl_pts"] or 0)
        closed_at = s.get("closed_at") or s.get("formed_at", "")
        eq_data.append({
            "time": closed_at[:10] if closed_at else "2000-01-01",
            "value": round(cumulative, 4),
        })

    # Deduplicate dates (use last value per date for daily chart)
    by_date = {}
    for p in eq_data:
        by_date[p["time"]] = p["value"]

    eq_points = [{"time": k, "value": v} for k, v in sorted(by_date.items())]
    color = "#26a69a" if cumulative >= 0 else "#ef5350"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    body {{ margin:0; padding:0; background:#000; overflow:hidden; }}
    #chart {{ width:100%; height:100vh; }}
  </style>
</head>
<body>
<div id="chart"></div>
<script>
const container = document.getElementById('chart');
const chart = LightweightCharts.createChart(container, {{
  width: container.offsetWidth, height: container.offsetHeight,
  layout: {{
    background:{{type:'solid',color:'#000'}},
    textColor:'#787b86', fontFamily:'Inter,sans-serif', fontSize:11,
  }},
  grid: {{ vertLines:{{color:'#111'}}, horzLines:{{color:'#111'}} }},
  rightPriceScale: {{ borderColor:'#1e1e2e' }},
  timeScale: {{ borderColor:'#1e1e2e', timeVisible:true }},
  crosshair: {{ vertLine:{{color:'#333',style:2}}, horzLine:{{color:'#333',style:2}} }},
}});

chart.addAreaSeries({{
  lineColor: '{color}',
  topColor:  '{color.replace(")", ",0.2)").replace("rgb", "rgba") if "rgb" in color else color + "33"}',
  bottomColor:'transparent',
  lineWidth:2,
  lastValueVisible:true,
  priceLineVisible:false,
  priceLineColor:'{color}',
}}).setData({json.dumps(eq_points)});

chart.timeScale().fitContent();
window.addEventListener('resize', () => {{
  chart.applyOptions({{width: container.offsetWidth, height: container.offsetHeight}});
}});
</script>
</body>
</html>"""
    components.html(html, height=220, scrolling=False)


# ── Main ──────────────────────────────────────────────────────────────────────

# Auto-evaluate pending signals against MySQL price data
evaluate_pending_from_db()

# Load all signals from MySQL
all_sigs = load_signals()

closed  = [s for s in all_sigs if s["status"] in ("WIN", "LOSS")]
wins    = [s for s in closed  if s["status"] == "WIN"]
losses  = [s for s in closed  if s["status"] == "LOSS"]
pend    = [s for s in all_sigs if s["status"] == "PENDING"]

total   = len(all_sigs)
winrate = (len(wins) / len(closed) * 100) if closed else 0.0
pnl_sum = sum(float(s.get("pnl_pts") or 0) for s in closed)

pnl_win  = sum(float(s.get("pnl_pts") or 0) for s in wins)
pnl_loss = abs(sum(float(s.get("pnl_pts") or 0) for s in losses))
pf       = (pnl_win / pnl_loss) if pnl_loss > 0 else float("inf")

avg_rr = 0.0
rr_vals = []
for s in closed:
    risk = abs(s["entry"] - s["stop_loss"])
    rewd = abs(s["entry"] - s["take_profit"])
    if risk > 0:
        rr_vals.append(rewd / risk)
if rr_vals:
    avg_rr = sum(rr_vals) / len(rr_vals)

# Refresh button
if st.button("Refresh & Re-evaluate", use_container_width=False):
    st.cache_data.clear()
    st.rerun()

st.markdown("")

# Header metrics
m1, m2, m3, m4, m5 = st.columns(5)
for col, label, value, sub in [
    (m1, "Total Signals",  str(total),            f"Win {len(wins)} / Loss {len(losses)} / Pending {len(pend)}"),
    (m2, "Win Rate",       f"{winrate:.1f}%",      f"{len(wins)} wins from {len(closed)} closed"),
    (m3, "Cumulative PnL", f"{pnl_sum:+.2f} pts",  "all closed signals"),
    (m4, "Profit Factor",  f"{min(pf, 99.9):.2f}", "gross win / gross loss"),
    (m5, "Avg Risk:Reward",f"1:{avg_rr:.2f}",      "across closed signals"),
]:
    with col:
        color = "#26a69a" if "PnL" in label and pnl_sum >= 0 else "#ef5350" if "PnL" in label else "#d1d4dc"
        st.markdown(f"""
<div class="metric-card">
  <div class="metric-label">{label}</div>
  <div class="metric-value" style="color:{color}">{value}</div>
  <div class="metric-sub">{sub}</div>
</div>""", unsafe_allow_html=True)

st.markdown("")

# Equity Curve + Condition Winrate
ec_col, wr_col = st.columns([2, 1])

with ec_col:
    st.markdown('<div class="panel-title">Equity Curve (Cumulative PnL pts)</div>', unsafe_allow_html=True)
    render_equity_curve(all_sigs)

with wr_col:
    st.markdown('<div class="panel-title">Win Rate by Condition</div>', unsafe_allow_html=True)

    cond_stats: dict = {}
    for s in closed:
        for c in s.get("conditions", []):
            if c not in cond_stats:
                cond_stats[c] = {"win": 0, "total": 0}
            cond_stats[c]["total"] += 1
            if s["status"] == "WIN":
                cond_stats[c]["win"] += 1

    if cond_stats:
        for cond, stat in sorted(cond_stats.items(), key=lambda x: -x[1]["win"]/max(x[1]["total"],1)):
            wr = stat["win"] / stat["total"] * 100
            bar_color = "#26a69a" if wr >= 50 else "#ef5350"
            st.markdown(f"""
<div class="cond-row">
  <span style="min-width:90px;">{cond}</span>
  <div class="cond-bar-wrap">
    <div class="cond-bar" style="width:{wr:.0f}%;background:{bar_color};"></div>
  </div>
  <span style="color:{bar_color};font-weight:600;min-width:40px;text-align:right;">{wr:.0f}%</span>
  <span style="color:#555;margin-left:6px;font-size:10px;">({stat['total']})</span>
</div>""", unsafe_allow_html=True)
    else:
        st.info("No closed signals to analyze yet.")

st.markdown("---")

# Signal History Table
st.markdown('<div class="panel-title">Signal History Log</div>', unsafe_allow_html=True)

if all_sigs:
    rows = []
    for s in sorted(all_sigs, key=lambda x: x.get("formed_at",""), reverse=True):
        status = s.get("status", "PENDING")
        dec    = 2
        pnl    = s.get("pnl_pts")
        rows.append({
            "Formed":    s.get("formed_at","")[:16],
            "Symbol":   s.get("symbol",""),
            "TF":       s.get("timeframe",""),
            "Direction":s.get("direction","").upper(),
            "Entry":    s.get("entry",""),
            "SL":       s.get("stop_loss",""),
            "TP":       s.get("take_profit",""),
            "Score":    f"{s.get('score',0)}/7",
            "Conf":     f"{int(s.get('confidence',0)*100)}%",
            "Conditions":", ".join(s.get("conditions",[])),
            "Status":   status,
            "PnL pts":  f"{pnl:+.2f}" if pnl is not None else "—",
            "Closed":   s.get("closed_at","")[:16] if s.get("closed_at") else "—",
        })

    df_table = pd.DataFrame(rows)
    st.dataframe(df_table, use_container_width=True, hide_index=True, height=350)
else:
    st.info("No signals recorded yet. Run AnaDashboard with data loaded to generate signals.")
