"""
AnaDashboard — Main quantitative chart with zones overlay and confluence signals.
"""

import os, sys, json, io
import pymysql, pymysql.cursors
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from analysis.smc_crt.scoring             import SMCScoringEngine
from analysis.divergence.signal_generator  import DivergenceSignalGenerator
from analysis.volume_profile.calculator    import VolumeProfileCalculator
from analysis.technical_analysis           import calc_rsi, calc_atr, detect_sr_zones
from dashboard.signal_store                import append_new_signals

st.set_page_config(
    page_title="AnaDashboard",
    page_icon="A",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────

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

# ── Config ────────────────────────────────────────────────────────────────────

ASSETS = {
    "XAUUSD": {"db": "raw_gold",   "dec": 2},
    "EURUSD": {"db": "raw_eurusd", "dec": 5},
    "DXY":    {"db": "raw_dxy",    "dec": 3},
    "US10Y":  {"db": "raw_us10y",  "dec": 3},
    "VIX":    {"db": "raw_vix",    "dec": 2},
    "GDX":    {"db": "raw_gdx",    "dec": 2},
}
TF_MAP = {"5m": "m5", "15m": "m15", "1h": "h1", "4h": "h4", "1D": "d1"}

DB = {
    "host":    os.getenv("DB_HOST", "localhost"),
    "port":    int(os.getenv("DB_PORT", 3306)),
    "user":    os.getenv("DB_USER", "root"),
    "password":os.getenv("DB_PASSWORD", ""),
    "charset": "utf8mb4",
}

ZONE_STYLE = {
    "BULLISH_FVG": ("#26a69a", "rgba(38,166,154,0.18)", "FVG Bullish"),
    "BEARISH_FVG": ("#ce93d8", "rgba(206,147,216,0.18)", "FVG Bearish"),
    "BULLISH_OB":  ("#9e9e9e", "rgba(158,158,158,0.15)", "Order Block"),
    "BEARISH_OB":  ("#9e9e9e", "rgba(158,158,158,0.15)", "Order Block"),
    "SSL_SWEEP":   ("#26c6da", "rgba(38,198,218,0.12)", "SSL Sweep"),
    "BSL_SWEEP":   ("#ab47bc", "rgba(171,71,188,0.12)", "BSL Sweep"),
    "SUPPORT":     ("#66bb6a", "rgba(0,80,0,0.25)",     "Support"),
    "RESISTANCE":  ("#ef9a9a", "rgba(139,0,0,0.28)",    "Resistance"),
    "VPOC":        ("#8ca9c5", "rgba(65,90,119,0.20)",  "VPOC"),
}

# ── Data ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_ohlcv(db_name: str, table: str, limit: int = 600, silent: bool = False) -> pd.DataFrame:
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
        if not silent:
            st.error(f"MySQL [{db_name}.{table}]: {e}")
        return pd.DataFrame()


def has_table(db_name: str, table: str) -> bool:
    try:
        conn = pymysql.connect(**DB, database=db_name)
        cur  = conn.cursor()
        cur.execute(f"SELECT 1 FROM `{table}` LIMIT 1")
        cur.close(); conn.close()
        return True
    except Exception:
        return False


# ── Analysis Pipeline ─────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def run_analysis(df_json: str, dxy_json: str, vix_json: str):
    """Run SMC + Divergence engines. Args as JSON strings for caching."""
    df  = pd.read_json(io.StringIO(df_json))
    df["price_datetime"] = pd.to_datetime(df["price_datetime"])

    drivers = {}
    if dxy_json:
        d = pd.read_json(io.StringIO(dxy_json))
        d["price_datetime"] = pd.to_datetime(d["price_datetime"])
        drivers["dxy"] = d
    if vix_json:
        v = pd.read_json(io.StringIO(vix_json))
        v["price_datetime"] = pd.to_datetime(v["price_datetime"])
        drivers["vix"] = v

    smc_df = SMCScoringEngine(pivot_window=3).generate_strategy_blueprint(df, drivers)

    df2 = df.copy()
    df2["rsi_14"] = calc_rsi(df["close_price"], 14)
    df2["atr_14"] = calc_atr(df, 14)
    div_df = DivergenceSignalGenerator(pivot_window=3).generate_composite_signals(df2, drivers)

    return smc_df.to_json(), div_df.to_json()


# ── Zone Extractor ────────────────────────────────────────────────────────────

def extract_zones(df: pd.DataFrame, smc_df: pd.DataFrame, dec: int) -> list:
    zones = []
    close = float(df["close_price"].iloc[-1])

    # FVG zones (unmitigated)
    for _, row in smc_df[smc_df["smc_fvg_type"].notna() & ~smc_df["smc_fvg_mitigated"]].tail(10).iterrows():
        zt = row["smc_fvg_type"]
        zones.append({"type": zt,
                      "high": round(float(row["smc_fvg_top"]),    dec),
                      "low":  round(float(row["smc_fvg_bottom"]), dec)})

    # OB zones (unmitigated)
    for _, row in smc_df[smc_df["smc_ob_type"].notna() & ~smc_df["smc_ob_mitigated"]].tail(8).iterrows():
        zones.append({"type": row["smc_ob_type"],
                      "high": round(float(row["smc_ob_top"]),    dec),
                      "low":  round(float(row["smc_ob_bottom"]), dec)})

    # S/R zones
    for z in detect_sr_zones(df, window=10, tolerance_pct=0.002)[:6]:
        band = max(z["price"] * 0.001, 0.5)
        zones.append({"type": z["type"],
                      "high": round(z["price"] + band, dec),
                      "low":  round(z["price"] - band, dec)})

    # VPOC
    vp = VolumeProfileCalculator(num_bins=40).compute_profile(df)
    if vp["poc"] and not np.isnan(vp["poc"]):
        poc  = vp["poc"]
        band = poc * 0.001
        zones.append({"type": "VPOC",
                      "high": round(poc + band, dec),
                      "low":  round(poc - band, dec)})

    return zones


# ── Confluence Signal ─────────────────────────────────────────────────────────

def build_confluence_signals(
    smc_df: pd.DataFrame,
    div_df: pd.DataFrame,
    df: pd.DataFrame,
    dec: int,
    min_conf: int,
    symbol: str,
    tf: str,
) -> list:
    atr  = calc_atr(df, 14).values
    close = df["close_price"].values
    n = min(len(smc_df), len(div_df), len(df))
    signals = []

    for i in range(50, n):
        score    = 0
        dir_bull = 0
        dir_bear = 0
        conds    = []

        def _str(val) -> str | None:
            """Return string value or None — guards against float NaN from read_json."""
            if val is None:
                return None
            try:
                if isinstance(val, float) and np.isnan(val):
                    return None
            except Exception:
                pass
            return str(val) if val else None

        def _check(col, df_=smc_df):
            v = df_.iloc[i].get(col) if i < len(df_) else None
            return v

        # [1] FVG nearby (within 0.5% of close)
        fvg = _str(_check("smc_fvg_type"))
        fvg_top = _check("smc_fvg_top")
        fvg_bot = _check("smc_fvg_bottom")
        fvg_mit = bool(_check("smc_fvg_mitigated"))
        if fvg and not fvg_mit and fvg_top and fvg_bot:
            try:
                mid = (float(fvg_top) + float(fvg_bot)) / 2
                if abs(close[i] - mid) / close[i] < 0.005:
                    score += 1
                    conds.append("FVG")
                    if "BULLISH" in fvg: dir_bull += 1
                    else:                dir_bear += 1
            except Exception:
                pass

        # [2] OB nearby
        ob = _str(_check("smc_ob_type"))
        ob_top = _check("smc_ob_top")
        ob_bot = _check("smc_ob_bottom")
        ob_mit = bool(_check("smc_ob_mitigated"))
        if ob and not ob_mit and ob_top and ob_bot:
            try:
                mid = (float(ob_top) + float(ob_bot)) / 2
                if abs(close[i] - mid) / close[i] < 0.005:
                    score += 1
                    conds.append("OB")
                    if "BULLISH" in ob: dir_bull += 1
                    else:               dir_bear += 1
            except Exception:
                pass

        # [3] Liquidity Sweep
        sweep = _str(_check("smc_liquidity_sweep"))
        if sweep:
            score += 1
            conds.append("SWEEP")
            if "SSL" in sweep: dir_bull += 1
            else:              dir_bear += 1

        # [4] RSI Divergence
        rsi_div = _str(div_df.iloc[i].get("div_rsi_14_signal") if i < len(div_df) else None)
        if rsi_div and rsi_div not in ("NONE", "None"):
            score += 1
            conds.append(rsi_div[:10])
            if "BULLISH" in rsi_div: dir_bull += 1
            else:                    dir_bear += 1

        # [5] CHoCH / BOS
        struct = _str(_check("smc_structure_signal"))
        if struct:
            score += 1
            conds.append(struct.replace("_", " ")[:10])
            if "BULLISH" in struct: dir_bull += 1
            else:                   dir_bear += 1

        # [6] Premium / Discount
        zone = _str(_check("smc_zone")) or "NEUTRAL"
        if zone == "DISCOUNT":
            score += 1; dir_bull += 1; conds.append("DISCOUNT")
        elif zone == "PREMIUM":
            score += 1; dir_bear += 1; conds.append("PREMIUM")

        # [7] VIX Macro OK
        vol_ok = bool(div_df.iloc[i].get("volatility_stable", True)) if i < len(div_df) else True
        if vol_ok:
            score += 1; conds.append("VIX_OK")

        if score < min_conf:
            continue

        direction = "bullish" if dir_bull > dir_bear else ("bearish" if dir_bear > dir_bull else None)
        if not direction:
            continue

        atr_v  = atr[i] if not np.isnan(atr[i]) else close[i] * 0.005
        entry  = close[i]
        if direction == "bullish":
            sl = entry - 1.5 * atr_v
            tp = entry + 1.5 * 2.0 * atr_v
        else:
            sl = entry + 1.5 * atr_v
            tp = entry - 1.5 * 2.0 * atr_v

        formed_at = str(df["price_datetime"].iloc[i])[:16]

        import uuid as _uuid
        signals.append({
            "id":          str(_uuid.uuid4())[:8],
            "symbol":      symbol,
            "timeframe":   tf,
            "tf_exec":     tf,
            "time":        int(df["price_datetime"].iloc[i].timestamp()),
            "direction":   direction,
            "entry":       round(entry, dec),
            "stop_loss":   round(sl,    dec),
            "take_profit": round(tp,    dec),
            "atr_14":      round(float(atr_v), dec),
            "score":       score,
            "confluence_score": score,
            "confidence":  round(score / 7, 2),
            "conditions":  conds,
            "formed_at":   formed_at,
        })

    return signals


# ── Chart HTML ────────────────────────────────────────────────────────────────

def render_chart(df, zones, signals, dec, show_vol, show_grid,
                 show_e20, show_e50, show_e100):
    candles = []
    for _, r in df.iterrows():
        candles.append({
            "time":  int(r["price_datetime"].timestamp()),
            "open":  round(float(r["open_price"]),  dec),
            "high":  round(float(r["high_price"]),  dec),
            "low":   round(float(r["low_price"]),   dec),
            "close": round(float(r["close_price"]), dec),
        })

    vol_data = []
    for _, r in df.iterrows():
        is_up = float(r["close_price"]) >= float(r["open_price"])
        vol_data.append({
            "time":  int(r["price_datetime"].timestamp()),
            "value": float(r["volume"]),
            "color": "rgba(38,166,154,0.3)" if is_up else "rgba(239,83,80,0.3)",
        })

    close = df["close_price"]
    e20  = close.ewm(span=20,  adjust=False).mean()
    e50  = close.ewm(span=50,  adjust=False).mean()
    e100 = close.ewm(span=100, adjust=False).mean()

    def _line(series):
        return [{"time": int(df["price_datetime"].iloc[i].timestamp()),
                 "value": round(float(v), dec)}
                for i, v in enumerate(series) if not np.isnan(v)]

    # Build zone JSON for JS
    chart_zones = []
    for z in zones:
        style = ZONE_STYLE.get(z["type"], ("#787b86", "rgba(120,123,134,0.1)", z["type"]))
        chart_zones.append({
            "high":  z["high"],
            "low":   z["low"],
            "color_line": style[0],
            "color_fill": style[1],
            "label":      style[2],
        })

    # Build signal markers
    markers = []
    for s in signals:
        markers.append({
            "time":      s["time"],
            "position":  "belowBar" if s["direction"] == "bullish" else "aboveBar",
            "color":     "#26a69a"  if s["direction"] == "bullish" else "#ef5350",
            "shape":     "arrowUp"  if s["direction"] == "bullish" else "arrowDown",
            "text":      f"{s['score']}/7",
        })

    grid_color = "#1a1a1a" if show_grid else "transparent"
    vol_margin = "0.28"    if show_vol  else "0.02"

    ema_js = ""
    if show_e20:
        ema_js += f"addEma({json.dumps(_line(e20))}, '#888888', 'EMA 20');"
    if show_e50:
        ema_js += f"addEma({json.dumps(_line(e50))}, '#d4b16a', 'EMA 50');"
    if show_e100:
        ema_js += f"addEma({json.dumps(_line(e100))}, '#415a77', 'EMA 100');"

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
    #chart   {{ width:100%; height:100%; }}
    #zone-overlay {{
      position:absolute; top:0; left:0; right:52px; bottom:28px;
      pointer-events:none; overflow:hidden;
    }}
  </style>
</head>
<body>
<div id="wrapper">
  <div id="chart"></div>
  <div id="zone-overlay"></div>
</div>
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
}});
candleSeries.setData({json.dumps(candles)});

function addEma(data, color, title) {{
  const s = chart.addLineSeries({{
    color:color, lineWidth:1, title:title,
    lastValueVisible:false, priceLineVisible:false,
  }});
  s.setData(data);
}}
{ema_js}
{vol_js}

// Signal arrows
const markers = {json.dumps(markers)};
if (markers.length) candleSeries.setMarkers(markers);

chart.timeScale().fitContent();

// Zone overlay drawing
const overlay = document.getElementById('zone-overlay');
const zones   = {json.dumps(chart_zones)};

function drawZones() {{
  overlay.innerHTML = '';
  zones.forEach(z => {{
    const yTop = candleSeries.priceToCoordinate(z.high);
    const yBot = candleSeries.priceToCoordinate(z.low);
    if (yTop === null || yBot === null) return;

    const top    = Math.min(yTop, yBot);
    const height = Math.max(Math.abs(yBot - yTop), 3);

    const div = document.createElement('div');
    div.style.cssText = [
      'position:absolute', 'left:0', 'right:0',
      'top:' + top + 'px',
      'height:' + height + 'px',
      'background:' + z.color_fill,
      'border-top:1px solid ' + z.color_line,
      'border-bottom:1px solid ' + z.color_line,
    ].join(';');

    const lbl = document.createElement('div');
    lbl.textContent = z.label;
    lbl.style.cssText = [
      'position:absolute', 'left:10px', 'top:2px',
      'font-size:11px', 'font-weight:500',
      'color:' + z.color_line,
      'font-family:Inter,sans-serif',
      'white-space:nowrap',
    ].join(';');

    div.appendChild(lbl);
    overlay.appendChild(div);
  }});
}}

chart.subscribeCrosshairMove(drawZones);
chart.timeScale().subscribeVisibleLogicalRangeChange(drawZones);
window.addEventListener('resize', () => {{
  chart.applyOptions({{
    width:  container.offsetWidth,
    height: container.offsetHeight,
  }});
  drawZones();
}});
setTimeout(drawZones, 200);
</script>
</body>
</html>"""
    components.html(html, height=520, scrolling=False)


# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.markdown("### Chart Settings")
show_vol  = st.sidebar.checkbox("Volume",  value=False)
show_grid = st.sidebar.checkbox("Grid",    value=True)
show_e20  = st.sidebar.checkbox("EMA 20",  value=False)
show_e50  = st.sidebar.checkbox("EMA 50",  value=False)
show_e100 = st.sidebar.checkbox("EMA 100", value=False)
st.sidebar.markdown("---")
st.sidebar.markdown("### Confluence Signal")
min_conf  = st.sidebar.slider("Min Confirmations", 3, 7, 4)
st.sidebar.markdown("---")
if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()

# ── Top Selectors ─────────────────────────────────────────────────────────────

c1, c2, c3, c4 = st.columns([1.2, 1.0, 1.4, 6.4])

with c1:
    symbol = st.selectbox("A", list(ASSETS.keys()), label_visibility="collapsed")

dec     = ASSETS[symbol]["dec"]
db_name = ASSETS[symbol]["db"]

avail_tfs = [tf for tf, tbl in TF_MAP.items() if has_table(db_name, tbl)]
if not avail_tfs:
    st.error(f"No data for {symbol}"); st.stop()

tf_default = avail_tfs.index("5m") if "5m" in avail_tfs else 0
with c2:
    tf = st.selectbox("T", avail_tfs, index=tf_default, label_visibility="collapsed")

with c3:
    style = st.selectbox("C", ["White/Black", "Green/Red", "Cyan/Red"], label_visibility="collapsed")

table = TF_MAP[tf]

# ── Load Data ─────────────────────────────────────────────────────────────────

df = load_ohlcv(db_name, table)
if df.empty:
    st.warning("No data."); st.stop()

df_dxy = load_ohlcv("raw_dxy", table, silent=True); dxy_json = df_dxy.to_json() if not df_dxy.empty else ""
df_vix = load_ohlcv("raw_vix", table, silent=True); vix_json = df_vix.to_json() if not df_vix.empty else ""

# ── Run Analysis ──────────────────────────────────────────────────────────────

smc_json_str, div_json_str = run_analysis(df.to_json(), dxy_json, vix_json)
smc_df = pd.read_json(io.StringIO(smc_json_str))
div_df = pd.read_json(io.StringIO(div_json_str))
smc_df["price_datetime"] = pd.to_datetime(smc_df["price_datetime"])
div_df["price_datetime"] = pd.to_datetime(div_df["price_datetime"])

zones   = extract_zones(df, smc_df, dec)
signals = build_confluence_signals(smc_df, div_df, df, dec, min_conf, symbol, tf)

# Save new signals to history (non-blocking)
try:
    added = append_new_signals(signals)
except Exception:
    added = 0

# ── OHLC Info Bar ─────────────────────────────────────────────────────────────

latest = df.iloc[-1]
prev   = df.iloc[-2] if len(df) > 1 else latest
chg    = float(latest["close_price"]) - float(prev["close_price"])
pct    = (chg / float(prev["close_price"])) * 100 if float(prev["close_price"]) else 0
cls    = "up" if chg >= 0 else "dn"
sgn    = "+" if chg >= 0 else ""

sig_info = f"<span class='sep'></span><span class='lbl'>Signals</span>&nbsp;<b style='color:#d4b16a'>{len(signals)}</b>"

st.markdown(f"""
<div class="ohlc-bar">
  <span><span class="lbl">O</span>&nbsp;{latest['open_price']:.{dec}f}</span>
  <span><span class="lbl">H</span>&nbsp;{latest['high_price']:.{dec}f}</span>
  <span><span class="lbl">L</span>&nbsp;{latest['low_price']:.{dec}f}</span>
  <span><span class="lbl">C</span>&nbsp;<b class="{cls}">{latest['close_price']:.{dec}f}</b></span>
  <span class="sep"></span>
  <span class="{cls}">{sgn}{chg:.{dec}f} ({sgn}{pct:.2f}%)</span>
  <span class="sep"></span>
  <span><span class="lbl">Vol</span>&nbsp;{int(latest['volume']):,}</span>
  <span class="sep"></span>
  <span><span class="lbl">Zones</span>&nbsp;<b style="color:#8ca9c5">{len(zones)}</b></span>
  {sig_info}
</div>
""", unsafe_allow_html=True)

# ── Render Chart ──────────────────────────────────────────────────────────────

render_chart(df, zones, signals, dec, show_vol, show_grid,
             show_e20, show_e50, show_e100)
