"""
Chart -- TradingView-style candlestick chart (lightweight-charts, same
engine and dark styling as the original SMC/CRT chart in this file's git
history, commit before f930f89), with the OU-family model's live-computed
mean line + k*sigma bands overlaid as line series and long/short/exit
markers on the candles, instead of the old SMC zone/CRT/liquidity-sweep
overlays.

The old overlays read curated_gold/curated_eurusd.smc_signals/
crt_signals/nested_zone_chains, tables that belong to a different
production system and don't exist in this repo's database anymore (see
README.md's data-architecture note -- this project only has the raw_*
layer now). Rebuilding SMC/CRT detection from scratch was out of scope;
this page keeps the exact same chart engine/visual language and swaps
only the data layer for the mean-reversion research this repo is
actually about.

No edge has been validated for any of these configs yet (see the Results
page / README.md's summary) -- this is a research/visualization tool,
not a signal to trade on.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.research.kalman_walkforward import DB, RAW_DB, HMM_CALIB_BARS  # noqa: E402
from analysis.strategies.garch_ou_mean_reversion import run_garch_mean_reversion  # noqa: E402
from analysis.strategies.cir_mean_reversion import run_cir_mean_reversion  # noqa: E402
import pymysql  # noqa: E402


def load_recent(symbol, table, n_rows):
    """Only the most recent n_rows bars, not the full history -- running
    GARCH-OU's MLE recalibration over 100k+ bars took 30-60s per page
    load, which read as a hang. HMM_CALIB_BARS still needs its own bars
    ahead of the displayed window as warm-up, hence the + HMM_CALIB_BARS
    padding (this is a visualization tool, not the validated backtest --
    see README.md's summary -- so calibrating HMM on this recent slice
    instead of the model's original full-history calibration window is an
    acceptable trade-off for responsiveness)."""
    conn = pymysql.connect(**DB, database=RAW_DB[symbol])
    cur = conn.cursor()
    cur.execute(
        f"SELECT price_datetime, open_price, high_price, low_price, close_price, volume "
        f"FROM {table} ORDER BY price_datetime DESC LIMIT {n_rows}"
    )
    rows = cur.fetchall()
    conn.close()
    df = pd.DataFrame(rows).sort_values("price_datetime").reset_index(drop=True)
    df["price_datetime"] = pd.to_datetime(df["price_datetime"])
    for c in ("open_price", "high_price", "low_price", "close_price", "volume"):
        df[c] = df[c].astype(float)
    return df

st.set_page_config(page_title="Chart", page_icon="C", layout="wide", initial_sidebar_state="expanded")

# ── CSS (same dark TradingView-style theme as the original chart) ──────────────

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
  .stApp { background:#000; font-family:'Inter',sans-serif; }
  header[data-testid="stHeader"] { background:#000; }
  .block-container { padding:2.6rem 1rem 0 1rem; max-width:100%; }
  section[data-testid="stSidebar"] {
    background:#0d0d14; border-right:1px solid #1e1e2e; width:240px !important;
  }
  section[data-testid="stSidebar"] label { color:#787b86 !important; font-size:12px; }
  .ohlc-bar {
    display:flex; align-items:center; gap:14px; padding:7px 14px;
    background:#0d0d14; border:1px solid #1e1e2e; border-radius:4px;
    margin-bottom:4px; font-size:13px; font-variant-numeric:tabular-nums;
  }
  .ohlc-bar .lbl { color:#555; font-size:11px; }
  .ohlc-bar .up  { color:#26a69a; font-weight:600; }
  .ohlc-bar .dn  { color:#ef5350; font-weight:600; }
  .ohlc-bar .sep { width:1px; height:20px; background:#1e1e2e; }
  footer { visibility:hidden; } #MainMenu { visibility:hidden; }
</style>
""", unsafe_allow_html=True)

# ── Config ───────────────────────────────────────────────────────────────────

# each symbol's fixed config, tuned at ONE timeframe (RESULTS.md exp
# 28/30/31/32) -- the single, already-deployable config, not re-optimized.
ASSETS = {
    "XAUUSD": dict(dec=2, run=run_garch_mean_reversion, tuned_tf="m5",
                   kw=dict(calib_window=60, recalib_every=20, k=2.2, z_stop=3.2, q_mult=1.0, obs_noise_scale=1.0,
                            tau_threshold=60, half_life_mult=2.0, friction_hurdle_mult=2.5,
                            hmm_calib_bars=HMM_CALIB_BARS, hmm_block_states=(2,))),
    "EURUSD": dict(dec=4, run=run_cir_mean_reversion, tuned_tf="m5",
                   kw=dict(calib_window=60, recalib_every=5, obs_noise_scale=1.0, q_mult=1.0, k=1.8,
                            z_stop=2.8, half_life_mult=2.0, hmm_calib_bars=HMM_CALIB_BARS,
                            hmm_block_states=(2,), tau_threshold=60, friction_hurdle_mult=2.5)),
    "NDX100": dict(dec=1, run=run_cir_mean_reversion, tuned_tf="m15",
                   kw=dict(calib_window=40, recalib_every=5, obs_noise_scale=1.0, q_mult=1.0, k=1.8,
                            z_stop=2.8, half_life_mult=2.0, hmm_calib_bars=HMM_CALIB_BARS,
                            hmm_block_states=(2,), tau_threshold=40, friction_hurdle_mult=2.5)),
}
TF_MAP = {
    "XAUUSD": {"5m": "m5", "15m": "m15", "1h": "h1", "4h": "h4", "1D": "d1"},
    "EURUSD": {"5m": "m5", "15m": "m15", "1h": "h1", "4h": "h4", "1D": "d1"},
    "NDX100": {"5m": "m5", "15m": "m15", "1h": "h1"},
}
BAR_LIMIT = 2000

# ── Data ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Computing model (first load can take up to ~30s)...")
def load_and_run(symbol, table):
    n_rows = BAR_LIMIT + HMM_CALIB_BARS + 500  # + warm-up padding for calib_window/HMM
    df = load_recent(symbol, table, n_rows)
    asset = ASSETS[symbol]
    res = asset["run"](df["price_datetime"], df["close_price"], df["high_price"], df["low_price"], **asset["kw"])
    res["open"] = df["open_price"].to_numpy()
    res["high"] = df["high_price"].to_numpy()
    res["low"] = df["low_price"].to_numpy()
    res["volume"] = df["volume"].to_numpy()
    return res.tail(BAR_LIMIT).reset_index(drop=True)


# ── Chart HTML (TradingView lightweight-charts, same engine as the original) ───

def render_chart(df, dec, show_vol, show_grid, show_e20, show_e50, show_e100,
                  show_mean, show_bands, show_signals):
    candles = []
    for _, r in df.iterrows():
        candles.append({
            "time":  int(pd.Timestamp(r["bar_datetime"]).timestamp()),
            "open":  round(float(r["open"]),  dec),
            "high":  round(float(r["high"]),  dec),
            "low":   round(float(r["low"]),   dec),
            "close": round(float(r["close"]), dec),
        })

    vol_data = []
    for _, r in df.iterrows():
        is_up = float(r["close"]) >= float(r["open"])
        vol_data.append({
            "time":  int(pd.Timestamp(r["bar_datetime"]).timestamp()),
            "value": float(r["volume"]),
            "color": "rgba(38,166,154,0.3)" if is_up else "rgba(239,83,80,0.3)",
        })

    close = df["close"]
    e20  = close.ewm(span=20,  adjust=False).mean()
    e50  = close.ewm(span=50,  adjust=False).mean()
    e100 = close.ewm(span=100, adjust=False).mean()

    def _line(series):
        return [{"time": int(pd.Timestamp(df["bar_datetime"].iloc[i]).timestamp()),
                 "value": round(float(v), dec)}
                for i, v in enumerate(series) if not np.isnan(v)]

    ema_js = ""
    if show_e20:
        ema_js += f"addLine({json.dumps(_line(e20))}, '#888888', 1, 'EMA 20');"
    if show_e50:
        ema_js += f"addLine({json.dumps(_line(e50))}, '#d4b16a', 1, 'EMA 50');"
    if show_e100:
        ema_js += f"addLine({json.dumps(_line(e100))}, '#415a77', 1, 'EMA 100');"
    if show_mean:
        ema_js += f"addLine({json.dumps(_line(df['mean_level']))}, '#42a5f5', 2, 'Model mean');"
    if show_bands:
        ema_js += f"addLine({json.dumps(_line(df['upper_band']))}, '#ef9a9a', 1, 'Short entry');"
        ema_js += f"addLine({json.dumps(_line(df['lower_band']))}, '#26a69a', 1, 'Long entry');"

    markers = []
    if show_signals:
        for i, sig in enumerate(df["signal"]):
            t = int(pd.Timestamp(df["bar_datetime"].iloc[i]).timestamp())
            if sig == "short":
                markers.append({"time": t, "position": "aboveBar", "color": "#ef5350",
                                 "shape": "arrowDown", "text": "SHORT"})
            elif sig == "long":
                markers.append({"time": t, "position": "belowBar", "color": "#26a69a",
                                 "shape": "arrowUp", "text": "LONG"})
            elif sig is not None:
                markers.append({"time": t, "position": "inBar", "color": "#787b86",
                                 "shape": "circle", "text": "exit"})
    markers.sort(key=lambda m: m["time"])

    grid_color = "#1a1a1a" if show_grid else "transparent"
    vol_margin = "0.28" if show_vol else "0.02"
    min_move = round(10 ** (-dec), dec)

    vol_js = ""
    if show_vol:
        vol_js = f"""
        const volSeries = chart.addHistogramSeries({{
            priceFormat:{{type:'volume'}}, priceScaleId:'vol',
            lastValueVisible:false, priceLineVisible:false,
        }});
        volSeries.priceScale().applyOptions({{scaleMargins:{{top:0.82,bottom:0}}}});
        volSeries.setData({json.dumps(vol_data)});
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
  <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    body {{ margin:0; padding:0; background:#000; overflow:hidden; }}
    #wrapper {{ position:relative; width:100%; height:100vh; }}
    #chart   {{ width:100%; height:100%; position:relative; z-index:2; }}
  </style>
</head>
<body>
<div id="wrapper"><div id="chart"></div></div>
<script>
const container = document.getElementById('chart');

const chart = LightweightCharts.createChart(container, {{
  width: container.offsetWidth, height: container.offsetHeight,
  layout: {{
    background:{{type:'solid',color:'#000'}}, textColor:'#787b86',
    fontFamily:'Inter,sans-serif', fontSize:11,
  }},
  grid: {{
    vertLines:{{color:'{grid_color}'}}, horzLines:{{color:'{grid_color}'}},
  }},
  crosshair: {{
    vertLine:{{color:'#555',width:1,style:2,labelBackgroundColor:'#222'}},
    horzLine:{{color:'#555',width:1,style:2,labelBackgroundColor:'#222'}},
  }},
  rightPriceScale: {{
    borderColor:'#1e1e2e',
    scaleMargins:{{top:0.05, bottom:{vol_margin}}},
  }},
  timeScale: {{
    borderColor:'#1e1e2e', timeVisible:true, secondsVisible:false, rightOffset:8,
  }},
}});

const candleSeries = chart.addCandlestickSeries({{
  upColor:'#d1d4dc', downColor:'#555555',
  borderUpColor:'#d1d4dc', borderDownColor:'#555555',
  wickUpColor:'#d1d4dc', wickDownColor:'#555555',
  lastValueVisible:false, priceLineVisible:false,
  priceFormat:{{type:'price', precision:{dec}, minMove:{min_move}}},
}});
candleSeries.setData({json.dumps(candles)});

function addLine(data, color, width, title) {{
  const s = chart.addLineSeries({{
    color:color, lineWidth:width, title:title,
    lastValueVisible:false, priceLineVisible:false,
  }});
  s.setData(data);
}}
{ema_js}
{vol_js}

const markers = {json.dumps(markers)};
if (markers.length) candleSeries.setMarkers(markers);

chart.timeScale().fitContent();

window.addEventListener('resize', () => {{
  chart.applyOptions({{width: container.offsetWidth, height: container.offsetHeight}});
}});

function fitFrame() {{
  const frame = window.frameElement;
  if (!frame) return;
  const top = frame.getBoundingClientRect().top;
  const vh  = window.parent.innerHeight || document.documentElement.clientHeight;
  const h   = Math.max(400, vh - top - 16);
  frame.style.height = h + 'px';
  requestAnimationFrame(() => chart.applyOptions({{width: container.offsetWidth, height: container.offsetHeight}}));
}}
setTimeout(fitFrame, 50);
window.parent.addEventListener('resize', fitFrame);
</script>
</body>
</html>"""
    st.components.v1.html(html, height=700, scrolling=False)


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar.expander("Chart Settings", expanded=True):
    show_vol  = st.checkbox("Volume",  value=False)
    show_grid = st.checkbox("Grid",    value=True)
    show_e20  = st.checkbox("EMA 20",  value=False)
    show_e50  = st.checkbox("EMA 50",  value=False)
    show_e100 = st.checkbox("EMA 100", value=False)

with st.sidebar.expander("Model", expanded=True):
    show_mean    = st.checkbox("Model mean", value=True)
    show_bands   = st.checkbox("Entry bands", value=True)
    show_signals = st.checkbox("Signal markers", value=True)

with st.sidebar.expander("Legend", expanded=False):
    st.markdown(
        "**Model mean** — the OU-family model's live-computed equilibrium "
        "(recalculated every bar from a rolling window, not a fixed value).\n\n"
        "**Entry bands** — k*sigma distance from the mean; price crossing "
        "the red band signals Short, the green band signals Long.\n\n"
        "**Signal markers** — arrows mark where the fixed config actually "
        "entered/exited a trade, not just where price touched a band."
    )

st.sidebar.markdown("---")
if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()

# ── Top Selectors ────────────────────────────────────────────────────────────

c1, c2, c3 = st.columns([1.2, 1.0, 7.8])
with c1:
    symbol = st.selectbox("Symbol", list(ASSETS.keys()), label_visibility="collapsed")
with c2:
    tf_label = st.selectbox("Timeframe", list(TF_MAP[symbol].keys()),
                             index=list(TF_MAP[symbol].keys()).index(
                                 next(k for k, v in TF_MAP[symbol].items() if v == ASSETS[symbol]["tuned_tf"])),
                             label_visibility="collapsed")

table = TF_MAP[symbol][tf_label]
asset = ASSETS[symbol]
if table != asset["tuned_tf"]:
    st.warning(f"This config was tuned for {symbol} {asset['tuned_tf'].upper()} only -- "
               f"viewing {tf_label} is exploratory, not statistically validated.")

# ── Load + Render ────────────────────────────────────────────────────────────

df = load_and_run(symbol, table)
if df.empty:
    st.warning("No data."); st.stop()

latest = df.iloc[-1]
prev   = df.iloc[-2] if len(df) > 1 else latest
dec    = asset["dec"]
chg    = float(latest["close"]) - float(prev["close"])
pct    = (chg / float(prev["close"])) * 100 if float(prev["close"]) else 0
cls    = "up" if chg >= 0 else "dn"
sgn    = "+" if chg >= 0 else ""
n_trades = int(df["signal"].isin(["long", "short"]).sum())

st.markdown(f"""
<div class="ohlc-bar">
  <span><span class="lbl">O</span>&nbsp;{latest['open']:.{dec}f}</span>
  <span><span class="lbl">H</span>&nbsp;{latest['high']:.{dec}f}</span>
  <span><span class="lbl">L</span>&nbsp;{latest['low']:.{dec}f}</span>
  <span><span class="lbl">C</span>&nbsp;<b class="{cls}">{latest['close']:.{dec}f}</b></span>
  <span class="sep"></span>
  <span class="{cls}">{sgn}{chg:.{dec}f} ({sgn}{pct:.2f}%)</span>
  <span class="sep"></span>
  <span><span class="lbl">Vol</span>&nbsp;{int(latest['volume']):,}</span>
  <span class="sep"></span>
  <span><span class="lbl">Trades shown</span>&nbsp;<b style="color:#d4b16a">{n_trades}</b></span>
</div>
""", unsafe_allow_html=True)

render_chart(df, dec, show_vol, show_grid, show_e20, show_e50, show_e100,
             show_mean, show_bands, show_signals)
