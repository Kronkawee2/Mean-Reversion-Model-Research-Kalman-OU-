"""
Signal — All detected confluence signals with mini chart preview.
"""

import os, sys, json
import pymysql, pymysql.cursors
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from dotenv import load_dotenv

DASH = Path(__file__).parent.parent
if str(DASH) not in sys.path:
    sys.path.insert(0, str(DASH))
if str(DASH.parent) not in sys.path:
    sys.path.insert(0, str(DASH.parent))
load_dotenv(DASH.parent / ".env")

from signal_store import load_signals

st.set_page_config(
    page_title="signal",
    page_icon="S",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
  
  /* Lock background to solid black #000000 across all layers to prevent background color flash */
  html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], section[data-testid="stMain"], .main {
    background-color: #000000 !important;
    background: #000000 !important;
  }
  .block-container { padding:2.6rem 0.8rem 0 0.8rem; max-width:100%; }

  /* Hide Streamlit top-right running spinner and status widget to eliminate reload distraction */
  div[data-testid="stStatusWidget"], #MainMenu, footer {
    display: none !important;
    visibility: hidden !important;
  }

  .sig-card-container {
    position: relative;
    width: 100%;
    margin-bottom: 12px;
  }

  .sig-card {
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:6px;
    padding:12px 14px; cursor:pointer;
    height: auto !important;
    min-height: 105px;
    box-sizing: border-box;
    transition:border-color 0.2s ease, background-color 0.2s ease, transform 0.1s ease;
    user-select:none;
  }
  .sig-card-container:hover .sig-card,
  .sig-card:hover {
    border-color:#d4b16a;
    background:#141422;
    transform: translateY(-1px);
  }
  .sig-card.selected {
    border-color:#d4b16a !important;
    background:#181828;
    box-shadow: 0 0 12px rgba(212, 177, 106, 0.2);
  }

  .sig-dir-bull { color:#26a69a; font-size:16px; font-weight:700; }
  .sig-dir-bear { color:#ef5350; font-size:16px; font-weight:700; }
  .sig-lbl { color:#555; font-size:10px; }
  .sig-val { color:#d1d4dc; font-size:13px; font-weight:600; }
  .sig-val-sl  { color:#ef5350; font-size:13px; font-weight:600; }
  .sig-val-tp  { color:#26a69a; font-size:13px; font-weight:600; }

  .badge {
    display:inline-block; font-size:9px; font-weight:700;
    padding:2px 6px; border-radius:3px; margin:1px;
    background:#1a1a2e; color:#787b86; border:1px solid #222;
  }

  .status-pending { color:#d4b16a; font-size:10px; font-weight:600; }
  .status-win     { color:#26a69a; font-size:10px; font-weight:600; }
  .status-loss    { color:#ef5350; font-size:10px; font-weight:600; }

  .panel-title {
    font-size:11px; font-weight:600; letter-spacing:0.08em;
    color:#787b86; text-transform:uppercase; margin-bottom:10px;
    border-bottom:1px solid #1e1e2e; padding-bottom:6px;
  }

  .sig-card-container {
    position: relative;
    width: 100%;
    margin-bottom: 12px;
  }

  .sig-card {
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:6px;
    padding:12px 14px; cursor:pointer;
    height: auto !important;
    min-height: 105px;
    box-sizing: border-box;
    transition:border-color 0.2s ease, background-color 0.2s ease, transform 0.1s ease;
    user-select:none;
  }
  .sig-card-container:hover .sig-card,
  .sig-card:hover {
    border-color:#d4b16a;
    background:#141422;
    transform: translateY(-1px);
  }
  .sig-card.selected {
    border-color:#d4b16a !important;
    background:#181828;
    box-shadow: 0 0 12px rgba(212, 177, 106, 0.2);
  }
</style>



""", unsafe_allow_html=True)

DB = {
    "host":    os.getenv("DB_HOST", "localhost"),
    "port":    int(os.getenv("DB_PORT", 3306)),
    "user":    os.getenv("DB_USER", "gold_user"),
    "password":os.getenv("DB_PASSWORD", "1234"),
    "charset": "utf8mb4",
}

ASSETS_DB = {
    "XAUUSD": {"db": "raw_gold",   "dec": 2},
    "EURUSD": {"db": "raw_eurusd", "dec": 5},
    "DXY":    {"db": "raw_dxy",    "dec": 3},
    "US10Y":  {"db": "raw_us10y",  "dec": 3},
    "VIX":    {"db": "raw_vix",    "dec": 2},
    "GDX":    {"db": "raw_gdx",    "dec": 2},
}
TF_MAP = {"5m": "m5", "15m": "m15", "1h": "h1", "4h": "h4", "1d": "d1"}


@st.cache_data(ttl=30)
def cached_load_signals():
    return load_signals()


@st.cache_data(ttl=30)
def load_ohlcv(db_name, table, limit=200):
    try:
        conn = pymysql.connect(**DB, database=db_name, cursorclass=pymysql.cursors.DictCursor)
        cur  = conn.cursor()
        cur.execute(
            f"SELECT price_datetime,open_price,high_price,low_price,close_price,volume "
            f"FROM `{table}` ORDER BY price_datetime DESC LIMIT {limit}"
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        df = pd.DataFrame(rows)
        if df.empty: return df
        df["price_datetime"] = pd.to_datetime(df["price_datetime"])
        for c in ["open_price","high_price","low_price","close_price","volume"]:
            df[c] = df[c].astype(float)
        return df.sort_values("price_datetime").reset_index(drop=True)
    except Exception as e:
        st.error(f"DB load error: {db_name}.{table} — {e}")
        return pd.DataFrame()


def render_mini_chart(df_window: pd.DataFrame, signal: dict, dec: int):
    """80-candle mini chart centered on signal with Entry/SL/TP lines."""
    candles = []
    for _, r in df_window.iterrows():
        candles.append({
            "time":  int(r["price_datetime"].timestamp()),
            "open":  round(float(r["open_price"]),  dec),
            "high":  round(float(r["high_price"]),  dec),
            "low":   round(float(r["low_price"]),   dec),
            "close": round(float(r["close_price"]), dec),
        })

    sig_time = signal.get("time", 0)
    direction = signal.get("direction", "bullish")
    score = signal.get("score", 0)

    html = f"""<!DOCTYPE html>
<html>
<head>
  <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    * {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{ background:#000; overflow:hidden; }}
    #chart {{ width:100%; height:400px; }}
  </style>
</head>
<body>
<div id="chart"></div>
<script>
try {{
  const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
    autoSize: true,
    layout: {{
      background:{{type:'solid',color:'#000'}},
      textColor:'#787b86', fontFamily:'Inter,sans-serif', fontSize:10,
    }},
    grid: {{ vertLines:{{color:'#111'}}, horzLines:{{color:'#111'}} }},
    rightPriceScale: {{ borderColor:'#1e1e2e' }},
    timeScale: {{ borderColor:'#1e1e2e', timeVisible:true, secondsVisible:false }},
    crosshair: {{ vertLine:{{color:'#333',style:2}}, horzLine:{{color:'#333',style:2}} }},
  }});

  const series = chart.addCandlestickSeries({{
    upColor:'#d1d4dc', downColor:'#555',
    borderUpColor:'#d1d4dc', borderDownColor:'#555',
    wickUpColor:'#d1d4dc', wickDownColor:'#555',
    lastValueVisible:false, priceLineVisible:false,
  }});
  series.setData({json.dumps(candles)});

  series.createPriceLine({{ price:{signal['entry']}, color:'#d4b16a', lineWidth:1, lineStyle:0, title:'Entry', axisLabelVisible:true }});
  series.createPriceLine({{ price:{signal['stop_loss']}, color:'#ef5350', lineWidth:1, lineStyle:2, title:'SL', axisLabelVisible:true }});
  series.createPriceLine({{ price:{signal['take_profit']}, color:'#26a69a', lineWidth:1, lineStyle:2, title:'TP', axisLabelVisible:true }});

  if ({sig_time} > 0) {{
    series.setMarkers([{{
      time:     {sig_time},
      position: '{'belowBar' if direction == 'bullish' else 'aboveBar'}',
      color:    '{'#26a69a' if direction == 'bullish' else '#ef5350'}',
      shape:    '{'arrowUp' if direction == 'bullish' else 'arrowDown'}',
      text:     '{score}/7',
    }}]);
  }}
  chart.timeScale().fitContent();
}} catch(e) {{
  document.body.innerHTML = '<div style="color:#ef5350;padding:20px;font-family:monospace;font-size:12px;">Chart error: '+e.message+'</div>';
}}
</script>
</body>
</html>"""
    components.html(html, height=400, scrolling=False)


# ── Fragment for Signal Cards + Chart Workspace (Zero Browser Refresh Flicker) ──

@st.fragment
def render_signal_workspace(filtered_list):
    if "sel" in st.query_params:
        try:
            st.session_state.selected_sig_idx = int(st.query_params["sel"])
        except (ValueError, TypeError):
            pass

    if "selected_sig_idx" not in st.session_state:
        st.session_state.selected_sig_idx = 0


    sel_idx = min(st.session_state.selected_sig_idx, max(0, len(filtered_list) - 1))

    left_col, right_col = st.columns([1, 1.6])

    with left_col:
        st.markdown('<div class="panel-title">Signal Cards</div>', unsafe_allow_html=True)
        
        # Native Streamlit scrollable container (eliminates unclosed HTML div bugs)
        with st.container(height=560, border=False):
            for i, s in enumerate(filtered_list[:30]):
                dir_class = "sig-dir-bull" if s["direction"] == "bullish" else "sig-dir-bear"
                dir_arrow = "▲ LONG" if s["direction"] == "bullish" else "▼ SHORT"
                conf_pct  = int(s.get("confidence", 0) * 100)
                status    = s.get("status", "PENDING")
                st_class  = f"status-{status.lower()}"
                dec       = ASSETS_DB.get(s["symbol"], {}).get("dec", 2)
                badge_html = "".join(f'<span class="badge">{c}</span>' for c in s.get("conditions", []))
                selected  = "selected" if i == sel_idx else ""

                st.markdown(f"""
<a href="?sel={i}" target="_self" style="text-decoration:none; color:inherit; display:block; margin-bottom:12px;">
  <div class="sig-card {selected}" id="sig-{i}">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <span class="{dir_class}">{dir_arrow}</span>
      <span class="{st_class}">{status}</span>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-top:8px;">
      <div><div class="sig-lbl">Entry</div><div class="sig-val">{s['entry']:.{dec}f}</div></div>
      <div><div class="sig-lbl">SL</div><div class="sig-val-sl">{s['stop_loss']:.{dec}f}</div></div>
      <div><div class="sig-lbl">TP</div><div class="sig-val-tp">{s['take_profit']:.{dec}f}</div></div>
    </div>
    <div style="margin-top:6px;">{badge_html}</div>
    <div style="display:flex;justify-content:space-between;margin-top:6px;">
      <span style="font-size:10px;color:#555;">{s['symbol']} {s['timeframe']} · {s.get('formed_at','')[:16]}</span>
      <span style="font-size:10px;color:#787b86;">conf {conf_pct}%</span>
    </div>
  </div>
</a>
""", unsafe_allow_html=True)














    with right_col:
        st.markdown('<div class="panel-title">Signal Chart Preview</div>', unsafe_allow_html=True)

        if filtered_list:
            sel = filtered_list[sel_idx]
            sym = sel["symbol"]
            tf  = sel["timeframe"]
            dec = ASSETS_DB.get(sym, {}).get("dec", 2)
            db_name = ASSETS_DB.get(sym, {}).get("db", "raw_gold")
            table   = TF_MAP.get(tf, "m5")

            df = load_ohlcv(db_name, table, limit=200)
            if not df.empty:
                sig_dt = pd.to_datetime(sel.get("formed_at", ""))
                idx = df["price_datetime"].searchsorted(sig_dt)
                start = max(0, idx - 40)
                end   = min(len(df), idx + 40)
                df_window = df.iloc[start:end]
                render_mini_chart(df_window, sel, dec)
            else:
                st.info("No chart data available for this symbol/timeframe.")

            st.markdown("---")
            link_label = f"Open {sym} {tf} in AnaDashboard"
            if st.button(link_label, use_container_width=True):
                st.session_state["jump_symbol"]   = sym
                st.session_state["jump_timeframe"] = tf
                st.switch_page("app.py")


# ── Main Page Execution ───────────────────────────────────────────────────────

signals = cached_load_signals()

# Filters (Top row)
top_c1, top_c2, top_c3, top_c4 = st.columns([1.5, 1.5, 1.5, 5.5])
with top_c1:
    f_dir = st.selectbox("Direction", ["All", "Bullish", "Bearish"])
with top_c2:
    f_sym = st.selectbox("Symbol", ["All"] + list(ASSETS_DB.keys()))
with top_c3:
    f_status = st.selectbox("Status", ["All", "PENDING", "WIN", "LOSS"])

filtered = signals
if f_dir != "All":
    filtered = [s for s in filtered if s["direction"] == f_dir.lower()]
if f_sym != "All":
    filtered = [s for s in filtered if s["symbol"] == f_sym]
if f_status != "All":
    filtered = [s for s in filtered if s["status"] == f_status]

filtered = sorted(filtered, key=lambda x: x.get("formed_at", ""), reverse=True)

if not filtered:
    st.markdown(
        '<div style="text-align:center;color:#333;padding:60px 0;font-size:14px;">'
        'No signals found.<br>'
        '<span style="font-size:12px;color:#222;">Run AnaDashboard to generate signals.</span>'
        '</div>',
        unsafe_allow_html=True
    )
    st.stop()

# Render Workspace inside Fragment (Zero browser URL refresh flicker)
render_signal_workspace(filtered)

