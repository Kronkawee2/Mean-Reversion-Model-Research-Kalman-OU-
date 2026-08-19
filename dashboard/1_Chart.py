"""
Chart — price chart with SMC zone overlay, CRT levels, and liquidity
sweep markers, read from the real curated pipeline (curated_gold/
curated_eurusd), not recomputed live.

Rebuilt (2026-08) from the original AnaDashboard, which computed SMC
zones/divergence live per page load using an older, separate analysis
layer (SMCScoringEngine, DivergenceSignalGenerator -- both still present
in analysis/ but superseded by SMCZoneStateEngine/TechnicalDivergenceEngine
and the curated_<symbol> tables they populate). This version is a pure
read layer: it queries curated_<symbol>.smc_signals/crt_signals/
liquidity_sweeps directly, same data the rest of this project's engines
and the backtester were validated against, instead of a parallel
in-session computation that could silently disagree with it.

The old confluence-signal scorer (7-condition ad-hoc scoring, persisted to
mart.trade_signals) is removed entirely -- that concept is superseded by
the real HTF Bias confluence score (page 2) and LTF Trigger signals
(page 3, Pass 2). This page no longer writes to mart.trade_signals at all.

Zone/CRT/sweep overlays are always sourced from h1 (this project's
established primary/authoritative HTF -- see htf_bias_engine.py,
crt_engine.py) regardless of which timeframe the candlestick chart itself
is displaying -- viewing an m5/m15/h4/d1 chart with h1-derived zones
overlaid is intentional (same relationship the LTF Trigger engine uses
between htf_zone and the LTF confirmation chart), not a bug. Only
XAUUSD/EURUSD are offered here (not DXY/US10Y/VIX/GDX, which the old
version listed as chartable symbols) since zones/CRT/bias only exist for
the two symbols this project's curated pipeline actually covers.
"""

import os, sys, json
import pymysql, pymysql.cursors
import pandas as pd
import numpy as np
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from analysis.features.indicator_features import resample_ohlc
from analysis.rolling_window import rolling_window_start

st.set_page_config(
    page_title="Chart",
    page_icon="C",
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
    "XAUUSD": {"raw_db": "raw_gold",   "curated_db": "curated_gold",   "dec": 2},
    "EURUSD": {"raw_db": "raw_eurusd", "curated_db": "curated_eurusd", "dec": 4},
}
TF_MAP     = {"5m": "m5", "15m": "m15", "1h": "h1", "4h": "h4", "6h": "h6", "1D": "d1"}
# m5/m15 tables grow fast and a full year of 5-minute bars isn't useful to
# look at anyway, so those stay capped to a recent row-count window. h1/h4/
# h6/d1 have no row cap (None = no LIMIT) -- instead they're bounded by the
# shared 2-year rolling-window date filter (analysis/rolling_window.py, see
# docs/DECISIONS.md) applied in load_ohlcv() below, same default used for
# divergence models and backtest runs. This is a default-VIEW change only --
# full history stays in the DB untouched, and the window is a WHERE-clause
# filter that's trivial to widen or remove later.
TF_ROW_LIMIT = {"5m": 5000, "15m": 5000, "1h": None, "4h": None, "6h": None, "1D": None}
ROLLING_WINDOW_TF = {"1h", "4h", "6h", "1D"}

DB = {
    "host":    os.getenv("DB_HOST", "localhost"),
    "port":    int(os.getenv("DB_PORT", "3308")),
    "user":    os.getenv("DB_USER", "quant_user"),
    "password":os.getenv("DB_PASSWORD", ""),
    "charset": "utf8mb4",
}

ZONE_STYLE = {
    "fvg_bullish":          ("#26a69a", "rgba(38,166,154,0.18)",  "FVG Bullish"),
    "fvg_bearish":          ("#ce93d8", "rgba(206,147,216,0.18)", "FVG Bearish"),
    "order_block_bullish":  ("#26a69a", "rgba(38,166,154,0.12)",  "OB Bullish"),
    "order_block_bearish":  ("#ce93d8", "rgba(206,147,216,0.12)", "OB Bearish"),
    "swing_support":        ("#66bb6a", "rgba(0,80,0,0.20)",      "Swing Support"),
    "swing_resistance":     ("#ef9a9a", "rgba(139,0,0,0.22)",     "Swing Resistance"),
}
# Visual weight per timeframe -- same D1>H6>H4>H1 priority the Composite
# Confluence Engine's ZONE_TIMEFRAME_WEIGHT uses for scoring (see
# analysis/strategies/composite_confluence_engine.py), applied here as
# border thickness + fill opacity instead of a score, so a glance at the
# chart tells you which zones matter most without reading labels first.
ZONE_TF_VISUAL = {
    "d1": {"border_width": 2, "opacity": 1.0},
    "h6": {"border_width": 2, "opacity": 0.82},
    "h4": {"border_width": 1, "opacity": 0.62},
    "h1": {"border_width": 1, "opacity": 0.42},
}
CRT_LINE_STYLE = {
    "equilibrium": "#8ca9c5",
}
CRT_ZONE_STYLE = {
    "asian_range": ("#d4b16a", "rgba(212,177,106,0.15)"),
    "equilibrium": ("#8ca9c5", "rgba(140,169,197,0.12)"),
}

# ── Data ─────────────────────────────────────────────────────────────────────

def _conn(db_name: str):
    return pymysql.connect(**DB, database=db_name, cursorclass=pymysql.cursors.DictCursor)


@st.cache_data(ttl=30)
def load_ohlcv(db_name: str, table: str, limit: int | None = None, use_rolling_window: bool = False) -> pd.DataFrame:
    try:
        conn = _conn(db_name)
        cur = conn.cursor()
        limit_sql = f"LIMIT {limit}" if limit else ""
        where_sql = "WHERE price_datetime >= %s" if use_rolling_window else ""
        params = (rolling_window_start(),) if use_rolling_window else ()
        cur.execute(
            f"SELECT price_datetime,open_price,high_price,low_price,close_price,volume "
            f"FROM `{table}` {where_sql} ORDER BY price_datetime DESC {limit_sql}",
            params,
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        df = pd.DataFrame(rows)
        if df.empty: return df
        df["price_datetime"] = pd.to_datetime(df["price_datetime"])
        for c in ["open_price", "high_price", "low_price", "close_price", "volume"]:
            df[c] = df[c].astype(float)
        return df.sort_values("price_datetime").reset_index(drop=True)
    except Exception as e:
        st.error(f"MySQL [{db_name}.{table}]: {e}")
        return pd.DataFrame()


ZONE_TIMEFRAMES = ["h1", "h4", "h6", "d1"]
TF_LABEL = {"h1": "H1", "h4": "H4", "h6": "H6", "d1": "D1"}


@st.cache_data(ttl=30)
def load_active_zones(curated_db: str, symbol: str, dec: int, timeframes: tuple) -> list:
    """SMC zones from whichever of h1/h4/h6/d1 the caller asks for
    (independent per-timeframe toggles in the sidebar -- see item 1
    follow-up in docs/DECISIONS.md), not tied to whichever timeframe the
    candlestick chart itself happens to be showing -- an h4 zone is still
    relevant context on an m15 chart. Each row carries its own `timeframe`
    so render_chart can label it (e.g. "FVG Bullish [H4]").

    'active' OR 'mitigated' (not yet invalidated), not 'active' alone.
    Checked against real data: order_block_bullish/bearish and
    swing_support/swing_resistance currently have ZERO rows sitting in
    'active' state on any timeframe -- their wick-touch mitigation
    criterion (same one FVG uses) fires almost immediately given how tight
    an OB/swing zone's price range is relative to normal intrabar
    movement, so by the time this query runs nearly every zone has already
    progressed past 'active' into 'mitigated'. That's a real, fast state
    transition, not a rendering bug -- filtering to state='active' alone
    was silently hiding these two zone types from the chart almost all the
    time. 'mitigated' still means "not invalidated" (price wicked in
    without closing through), so it belongs on the chart too; render_chart
    marks it visually distinct (dashed border, lower opacity) rather than
    treating it identically to a fresh 'active' zone."""
    if not timeframes:
        return []
    conn = _conn(curated_db)
    try:
        with conn.cursor() as cur:
            placeholders = ",".join(["%s"] * len(timeframes))
            cur.execute(
                f"SELECT zone_type, timeframe, zone_top, zone_bottom, created_at_bar, state FROM smc_signals "
                f"WHERE symbol=%s AND timeframe IN ({placeholders}) AND state IN ('active','mitigated') "
                f"ORDER BY created_at_bar DESC",
                (symbol, *timeframes),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"type": r["zone_type"], "timeframe": r["timeframe"], "state": r["state"],
             "high": round(float(r["zone_top"]), dec),
             "low": round(float(r["zone_bottom"]), dec),
             "created_at_bar": r["created_at_bar"]} for r in rows]


@st.cache_data(ttl=30)
def load_latest_atr(curated_db: str, symbol: str) -> float | None:
    """h1 atr_14, same table/timeframe the Composite Confluence Engine reads
    for its own stop/target ATR bounds -- used here purely to size the
    zone-distance clutter filter, not for any trading decision."""
    conn = _conn(curated_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT atr_14 FROM features WHERE symbol=%s AND timeframe='h1' "
                "ORDER BY bar_datetime DESC LIMIT 1",
                (symbol,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return float(row["atr_14"]) if row and row["atr_14"] is not None else None


@st.cache_data(ttl=30)
def load_nested_chains(curated_db: str, symbol: str) -> list:
    """curated.nested_zone_chains -- the production entry mechanism for the
    Composite Confluence Engine (see docs/DECISIONS.md). No separate page
    or panel for this by design -- every level of every chain is rendered
    directly on this chart, layered with the existing H1/H4/H6/D1 zone
    overlays, using the exact same timeframe visual weighting
    (ZONE_TF_VISUAL) so a chain reads as part of the same picture instead
    of a disconnected second view."""
    conn = _conn(curated_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT direction, root_timeframe, terminal_timeframe, chain, "
                "zone_top, zone_bottom, created_at_bar FROM nested_zone_chains "
                "WHERE symbol=%s ORDER BY created_at_bar DESC",
                (symbol,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    chains = []
    for r in rows:
        levels = json.loads(r["chain"]) if isinstance(r["chain"], str) else r["chain"]
        chains.append({"direction": r["direction"], "root_timeframe": r["root_timeframe"],
                        "terminal_timeframe": r["terminal_timeframe"], "levels": levels})
    return chains


@st.cache_data(ttl=30)
def load_crt_levels(curated_db: str, symbol: str, dec: int) -> list:
    """Most recent Asian range (h1, still pending/unswept) and the latest
    Range Equilibrium (h4) level.

    Both are ranges, not single prices -- rendered as shaded zones (kind
    'zone', high/low bounds) rather than bare price lines wherever the
    underlying data has a real top/bottom. Asian range pairs the
    asian_range_high/asian_range_low rows for the same session_date; h4
    equilibrium uses the range_high/range_low of the candle that produced
    it (the actual 0%/100% of that 50% level), not an arbitrary symmetric
    band around the midpoint. Only equilibrium rows from older data with a
    NULL range_high/range_low fall back to a plain line (kind 'line')."""
    conn = _conn(curated_db)
    levels = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT session_date FROM crt_signals "
                "WHERE symbol=%s AND timeframe='h1' AND signal_type IN ('asian_range_high','asian_range_low') "
                "AND state='pending' ORDER BY session_date DESC LIMIT 1",
                (symbol,),
            )
            latest = cur.fetchone()
            if latest:
                cur.execute(
                    "SELECT signal_type, level_price FROM crt_signals "
                    "WHERE symbol=%s AND timeframe='h1' AND signal_type IN ('asian_range_high','asian_range_low') "
                    "AND session_date=%s",
                    (symbol, latest["session_date"]),
                )
                pair = {r["signal_type"]: r["level_price"] for r in cur.fetchall()}
                if "asian_range_high" in pair and "asian_range_low" in pair:
                    levels.append({
                        "kind": "zone", "type": "asian_range",
                        "high": round(float(pair["asian_range_high"]), dec),
                        "low":  round(float(pair["asian_range_low"]), dec),
                        "label": f"Asian Range ({latest['session_date']})",
                        "start": latest["session_date"],
                    })

            cur.execute(
                "SELECT equilibrium_price, range_high, range_low, zone_bias, bar_datetime FROM crt_signals "
                "WHERE symbol=%s AND timeframe='h4' AND signal_type='equilibrium' "
                "ORDER BY bar_datetime DESC LIMIT 1",
                (symbol,),
            )
            eq = cur.fetchone()
            if eq and eq["equilibrium_price"] is not None:
                label = f"Equilibrium h4 ({eq['zone_bias']})"
                if eq["range_high"] is not None and eq["range_low"] is not None:
                    levels.append({
                        "kind": "zone", "type": "equilibrium",
                        "high": round(float(eq["range_high"]), dec),
                        "low":  round(float(eq["range_low"]), dec),
                        "label": label,
                        "start": eq["bar_datetime"],
                    })
                else:
                    levels.append({
                        "kind": "line", "type": "equilibrium",
                        "price": round(float(eq["equilibrium_price"]), dec),
                        "label": label,
                    })
    finally:
        conn.close()
    return levels


@st.cache_data(ttl=30)
def load_recent_sweeps(curated_db: str, symbol: str, dec: int, n: int = 10) -> list:
    conn = _conn(curated_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sweep_type, direction, swept_level_price, bar_datetime FROM liquidity_sweeps "
                "WHERE symbol=%s AND timeframe='h1' ORDER BY bar_datetime DESC LIMIT %s",
                (symbol, n),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"sweep_type": r["sweep_type"], "direction": r["direction"],
              "price": round(float(r["swept_level_price"]), dec),
              "bar_datetime": r["bar_datetime"]} for r in rows]


# ── Chart HTML ────────────────────────────────────────────────────────────────

def render_chart(df, zones, crt_levels, sweep_markers, dec, show_vol, show_grid,
                 show_e20, show_e50, show_e100, show_sessions, nested_chains=None):
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

    chart_zones = []
    for z in zones:
        style = ZONE_STYLE.get(z["type"], ("#787b86", "rgba(120,123,134,0.1)", z["type"]))
        tf_label = TF_LABEL.get(z["timeframe"], z["timeframe"].upper())
        label = f"{style[2]} [{tf_label}]"
        mitigated = z.get("state") == "mitigated"
        if mitigated:
            label += " (touched)"
        visual = ZONE_TF_VISUAL.get(z["timeframe"], {"border_width": 1, "opacity": 0.5})
        chart_zones.append({"high": z["high"], "low": z["low"],
                              "color_line": style[0], "color_fill": style[1], "label": label,
                              "dashed": mitigated,
                              "border_width": visual["border_width"],
                              "opacity": visual["opacity"] * (0.6 if mitigated else 1.0),
                              "start": int(pd.Timestamp(z["created_at_bar"]).timestamp())})

    # Nested Zone Chains -- every level of every chain rendered as its own
    # zone box. Color is the only thing that varies by timeframe now (a
    # distinct color per D1/H6/H4/H1/M15/M5, not a shared gold with varying
    # opacity/width) -- always solid, always thin, always the same opacity,
    # per explicit user correction: varying opacity/dashing on top of
    # timeframe was harder to read, not easier. Label is the FULL
    # breadcrumb on every level (not just the terminal one) so hovering any
    # single box in the chain still tells you the whole path.
    CHAIN_TF_COLOR = {
        "d1":  "#ef5350",  # red
        "h6":  "#ffa726",  # orange
        "h4":  "#d4b16a",  # gold
        "h1":  "#26a69a",  # teal
        "m15": "#42a5f5",  # blue
        "m5":  "#ab47bc",  # purple
    }
    # Faint fill between the border lines, same color as the border --
    # intensity ordered smallest-timeframe-darkest to largest-timeframe-
    # faintest (M5 most opaque, D1 most transparent), per explicit request.
    CHAIN_TF_FILL_ALPHA = {
        "m5": 0.20, "m15": 0.16, "h1": 0.12, "h4": 0.09, "h6": 0.06, "d1": 0.04,
    }

    def _hex_to_rgba(hex_color, alpha):
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    CHAIN_BORDER_WIDTH = 1
    CHAIN_OPACITY = 0.8
    for chain in (nested_chains or []):
        breadcrumb = " → ".join(
            f"{TF_LABEL.get(lvl['timeframe'], lvl['timeframe'].upper())} {lvl['zone_type']}"
            for lvl in chain["levels"]
        ) + " → entry"
        for lvl in chain["levels"]:
            color = CHAIN_TF_COLOR.get(lvl["timeframe"], "#d4b16a")
            fill = _hex_to_rgba(color, CHAIN_TF_FILL_ALPHA.get(lvl["timeframe"], 0.08))
            chart_zones.append({
                "high": lvl["zone_top"], "low": lvl["zone_bottom"],
                "color_line": color, "color_fill": fill,
                "label": breadcrumb,
                "dashed": False,
                "border_width": CHAIN_BORDER_WIDTH,
                "opacity": CHAIN_OPACITY,
                "start": int(pd.Timestamp(lvl["created_at_bar"]).timestamp()),
            })

    for lvl in crt_levels:
        if lvl.get("kind") != "zone":
            continue
        line_color, fill_color = CRT_ZONE_STYLE.get(lvl["type"], ("#8ca9c5", "rgba(140,169,197,0.12)"))
        chart_zones.append({"high": lvl["high"], "low": lvl["low"],
                              "color_line": line_color, "color_fill": fill_color, "label": lvl["label"],
                              "border_width": 1, "opacity": 1.0,
                              "start": int(pd.Timestamp(lvl["start"]).timestamp())})

    # Signal markers for liquidity sweeps -- placed at the swept bar if it's
    # within the loaded candle range, otherwise skipped (sweep may be older
    # than the visible window).
    candle_times = {c["time"] for c in candles}
    markers = []
    for s in sweep_markers:
        t = int(pd.Timestamp(s["bar_datetime"]).timestamp())
        if t not in candle_times:
            continue
        bullish = s["direction"] == "bullish"
        markers.append({
            "time": t, "position": "belowBar" if bullish else "aboveBar",
            "color": "#26c6da" if s["sweep_type"] == "ssl" else "#ab47bc",
            "shape": "arrowUp" if bullish else "arrowDown",
            "text": s["sweep_type"].upper(),
        })
    markers.sort(key=lambda m: m["time"])

    grid_color = "#1a1a1a" if show_grid else "transparent"
    vol_margin = "0.28"    if show_vol  else "0.02"
    min_move   = round(10 ** (-dec), dec)
    sessions_js_flag = "true" if show_sessions else "false"

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

    crt_js = ""
    for lvl in crt_levels:
        if lvl.get("kind") == "zone":
            continue
        color = CRT_LINE_STYLE.get(lvl["type"], "#8ca9c5")
        crt_js += (f"candleSeries.createPriceLine({{price:{lvl['price']}, color:'{color}', "
                   f"lineWidth:1, lineStyle:0, title:'{lvl['label']}', axisLabelVisible:true}});")

    html = f"""<!DOCTYPE html>
<html>
<head>
  <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    body {{ margin:0; padding:0; background:#000; overflow:hidden; }}
    #wrapper {{ position:relative; width:100%; height:100vh; }}
    #chart   {{ width:100%; height:100%; position:relative; z-index:2; }}
    #session-overlay {{
      position:absolute; top:0; left:0; right:0; bottom:0;
      pointer-events:none; overflow:hidden; z-index:3;
    }}
    #zone-overlay {{
      position:absolute; top:0; left:0; right:0; bottom:0;
      pointer-events:none; overflow:hidden; z-index:5;
    }}
  </style>
</head>
<body>
<div id="wrapper">
  <div id="chart"></div>
  <div id="session-overlay"></div>
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
  priceFormat:{{type:'price', precision:{dec}, minMove:{min_move}}},
}});
const candleData = {json.dumps(candles)};
candleSeries.setData(candleData);
const candleTimes = candleData.map(c => c.time);

function addEma(data, color, title) {{
  const s = chart.addLineSeries({{
    color:color, lineWidth:1, title:title,
    lastValueVisible:false, priceLineVisible:false,
  }});
  s.setData(data);
}}
{ema_js}
{vol_js}
{crt_js}

const markers = {json.dumps(markers)};
if (markers.length) candleSeries.setMarkers(markers);

chart.timeScale().fitContent();

const overlay = document.getElementById('zone-overlay');
const zones   = {json.dumps(chart_zones)};

let _zoneDebugLogged = false;
function drawZones() {{
  overlay.style.right  = chart.priceScale('right').width() + 'px';
  overlay.style.bottom = chart.timeScale().height() + 'px';
  overlay.innerHTML = '';
  let drawn = 0, skippedNullCoord = 0;
  zones.forEach(z => {{
    const yTop = candleSeries.priceToCoordinate(z.high);
    const yBot = candleSeries.priceToCoordinate(z.low);
    if (yTop === null || yBot === null) {{ skippedNullCoord++; return; }}
    drawn++;

    const top    = Math.min(yTop, yBot);
    const height = Math.max(Math.abs(yBot - yTop), 3);

    // Draw from the zone's actual origin bar, not the chart's left edge --
    // it extends rightward (still active/unmitigated) to the overlay's edge.
    // xStartRaw can be negative (origin is off-screen to the left of the
    // current view, still within the loaded data) -- render it as-is and
    // let the overlay's overflow:hidden clip it; panning left then
    // correctly reveals the true origin. Only fall back to 0 when
    // coordForTime found no bar at all (origin outside the loaded range).
    const xStartRaw = coordForTime(z.start);
    const xStart = xStartRaw === null ? 0 : xStartRaw;

    const borderStyle = z.dashed ? 'dashed' : 'solid';
    const bw = z.border_width || 1;
    const div = document.createElement('div');
    div.style.cssText = [
      'position:absolute', 'left:' + xStart + 'px', 'right:0',
      'top:' + top + 'px',
      'height:' + height + 'px',
      'background:' + z.color_fill,
      'border-top:' + bw + 'px ' + borderStyle + ' ' + z.color_line,
      'border-bottom:' + bw + 'px ' + borderStyle + ' ' + z.color_line,
      'opacity:' + (z.opacity != null ? z.opacity : 1.0),
    ].join(';');
    div.title = z.label;

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
  if (!_zoneDebugLogged) {{
    _zoneDebugLogged = true;
    const overlayRect = overlay.getBoundingClientRect();
    const chartRect    = container.getBoundingClientRect();
    console.log('[chart-debug] zones received:', zones.length,
      '| drawn:', drawn, '| skipped (null coord):', skippedNullCoord);
    console.log('[chart-debug] overlay rect:', overlayRect,
      'z-index:', getComputedStyle(overlay).zIndex,
      '| chart rect:', chartRect);
    if (zones.length) console.log('[chart-debug] first zone:', zones[0]);
  }}
}}

// Session boundaries are fixed UTC hours-of-day: Asian open, London open,
// NY open, session close. Each session gets its own muted color for the
// band between it and the next boundary; the off-hours block (Close ->
// next day's Asian open) is left unfilled -- it's not a session.
const sessionOverlay = document.getElementById('session-overlay');
// lineAlpha is tuned per color so the dashed lines read with similar
// visual weight -- violet and grey have much lower perceived luminance
// than amber/blue at the same alpha, so they need more of it to match.
const SHOW_SESSIONS = {sessions_js_flag};
const SESSION_BOUNDARIES = [
  {{h: 0,  label: 'AS', rgb: '255,202,40', lineAlpha: 0.30}},  // amber - Asian
  {{h: 7,  label: 'LD', rgb: '41,182,246', lineAlpha: 0.38}},  // sky blue - London
  {{h: 12, label: 'NY', rgb: '126,87,194', lineAlpha: 0.55}},  // violet - NY
  {{h: 21, label: 'CL', rgb: '120,120,120', lineAlpha: 0.45}}, // neutral - Close, no fill after this
];

// timeToCoordinate(t) only resolves t if it exactly matches a real bar's
// own timestamp -- it does not interpolate between bars. Zone origins
// (h1-bar marks) and session boundaries (fixed UTC hour-of-day) almost
// never land exactly on a bar of whatever timeframe the chart itself is
// showing, so a direct call returns null even when a bar exists seconds
// away. Binary-search the chart's own loaded candle times (already
// available as candleTimes) for the nearest real bar and resolve that
// instead of guessing blind offsets.
function nearestCandleTime(t) {{
  const n = candleTimes.length;
  if (n === 0) return null;
  if (t <= candleTimes[0]) return candleTimes[0];
  if (t >= candleTimes[n - 1]) return candleTimes[n - 1];
  let lo = 0, hi = n - 1;
  while (lo < hi) {{
    const mid = (lo + hi) >> 1;
    if (candleTimes[mid] < t) lo = mid + 1; else hi = mid;
  }}
  const after  = candleTimes[lo];
  const before = lo > 0 ? candleTimes[lo - 1] : after;
  return (after - t) <= (t - before) ? after : before;
}}
function coordForTime(t) {{
  const ts = chart.timeScale();
  const c = ts.timeToCoordinate(t);
  if (c !== null) return c;
  const nt = nearestCandleTime(t);
  return nt === null ? null : ts.timeToCoordinate(nt);
}}

function drawSessions() {{
  sessionOverlay.style.right  = chart.priceScale('right').width() + 'px';
  sessionOverlay.style.bottom = chart.timeScale().height() + 'px';
  sessionOverlay.innerHTML = '';
  if (!SHOW_SESSIONS) return;

  const range = chart.timeScale().getVisibleRange();
  if (!range) return;

  const dayStart = Math.floor(range.from / 86400) * 86400 - 86400;
  const dayEnd   = Math.ceil(range.to   / 86400) * 86400 + 86400;

  const marks = [];
  for (let day = dayStart; day <= dayEnd; day += 86400) {{
    SESSION_BOUNDARIES.forEach(b => marks.push({{t: day + b.h * 3600, label: b.label, rgb: b.rgb, lineAlpha: b.lineAlpha}}));
  }}
  marks.sort((a, b) => a.t - b.t);

  marks.forEach((m, i) => {{
    const x = coordForTime(m.t);
    if (x === null) return;

    if (i < marks.length - 1 && m.label !== 'CL') {{
      const xNext = coordForTime(marks[i + 1].t);
      if (xNext !== null) {{
        const band = document.createElement('div');
        band.style.cssText = [
          'position:absolute', 'top:0', 'bottom:0',
          'left:' + x + 'px', 'width:' + (xNext - x) + 'px',
          'background:rgba(' + m.rgb + ',0.05)',
        ].join(';');
        sessionOverlay.appendChild(band);
      }}
    }}

    const line = document.createElement('div');
    line.style.cssText = [
      'position:absolute', 'top:0', 'bottom:0', 'left:' + x + 'px',
      'border-left:1px dashed rgba(' + m.rgb + ',' + m.lineAlpha + ')',
    ].join(';');
    sessionOverlay.appendChild(line);

    const lbl = document.createElement('div');
    lbl.textContent = m.label;
    lbl.style.cssText = [
      'position:absolute', 'top:2px', 'left:' + (x + 4) + 'px',
      'font-size:10px', 'color:rgba(' + m.rgb + ',0.8)',
      'font-family:Inter,sans-serif', 'white-space:nowrap',
    ].join(';');
    sessionOverlay.appendChild(lbl);
  }});
}}

function refreshOverlays() {{
  drawZones();
  drawSessions();
}}

chart.subscribeCrosshairMove(refreshOverlays);
chart.timeScale().subscribeVisibleLogicalRangeChange(refreshOverlays);
window.addEventListener('resize', () => {{
  chart.applyOptions({{
    width:  container.offsetWidth,
    height: container.offsetHeight,
  }});
  refreshOverlays();
}});
setTimeout(refreshOverlays, 200);

// This iframe (srcdoc, same-origin) starts at the fixed pixel height
// Streamlit gave it. Stretch it to fill the remaining viewport below its
// own top edge so the chart has no dead whitespace and the page itself
// never needs to scroll to see it.
function fitFrame() {{
  const frame = window.frameElement;
  if (!frame) return;
  const top = frame.getBoundingClientRect().top;
  const vh  = window.parent.innerHeight || document.documentElement.clientHeight;
  const h   = Math.max(400, vh - top - 16);
  frame.style.height = h + 'px';
  requestAnimationFrame(() => {{
    chart.applyOptions({{width: container.offsetWidth, height: container.offsetHeight}});
    refreshOverlays();
  }});
}}
setTimeout(fitFrame, 50);
window.parent.addEventListener('resize', fitFrame);
</script>
</body>
</html>"""
    st.components.v1.html(html, height=700, scrolling=False)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar.expander("Chart Settings", expanded=True):
    show_vol  = st.checkbox("Volume",  value=False)
    show_grid = st.checkbox("Grid",    value=True)
    show_e20  = st.checkbox("EMA 20",  value=False)
    show_e50  = st.checkbox("EMA 50",  value=False)
    show_e100 = st.checkbox("EMA 100", value=False)

with st.sidebar.expander("Overlays", expanded=True):
    # Raw H1/H4/H6/D1 SMC zone overlay, CRT Levels, and Liquidity Sweeps
    # overlays removed (2026-08) -- production no longer trades off a raw
    # H1 zone touch or CRT levels at all (see docs/DECISIONS.md: CRT
    # dropped from scoring entirely, H1-touch replaced by Nested Zone
    # Drilling). The underlying H1/H4/H6/D1 zones and sweep detection
    # still feed the chain (drilling reads them, prioritization scores
    # against sweep events) -- they're just no longer shown as a separate,
    # undifferentiated raw overlay; the chain view already surfaces
    # whichever of them actually mattered enough to get drilled.
    zone_timeframes = ()
    show_crt = show_sweep = False
    zones_near_price_only = st.checkbox("Chains near current price only", value=True)
    chain_atr_multiple = st.slider(
        "Distance (x ATR)", min_value=0.5, max_value=10.0, value=3.0, step=0.5,
        disabled=not zones_near_price_only,
        help="Fixed 10x ATR was still too cluttered to read at a glance -- made adjustable "
             "so you can narrow it live instead of a fixed number nobody can tune.",
    )
    max_chains_shown = st.slider(
        "Max chains shown", min_value=1, max_value=30, value=8,
        disabled=not zones_near_price_only,
        help="Caps to the N most recent chains after the distance filter -- distance alone "
             "can still leave many overlapping boxes stacked at the same price cluster.",
    )
    show_sessions = st.checkbox("Session Dividers", value=False)
    show_chains   = st.checkbox(
        "Nested Zone Chains", value=True,
        help="Every level of every D1>H6>H4>H1>M15>M5 drill chain (production entry mechanism, "
             "see docs/DECISIONS.md), layered on this chart -- gold border marks chain "
             "membership, label shows the full breadcrumb.",
    )

with st.sidebar.expander("Legend", expanded=False):
    st.markdown(
        "**FVG** (Fair Value Gap) — a 3-candle price gap the market left "
        "unfilled; often gets revisited before the move continues.\n\n"
        "**OB** (Order Block) — the last opposite-direction candle before "
        "a strong break, marking where the move likely originated.\n\n"
        "**Swing Support / Resistance** — a recent swing high or low "
        "still acting as a turning point.\n\n"
        "**BSL / SSL** (Buy-Side / Sell-Side Liquidity) — a swing high/low "
        "where stop-losses cluster; the arrow marks where price swept "
        "through it and reversed.\n\n"
        "**Asian Range** — the high/low of the Asian trading session, "
        "watched for a later sweep.\n\n"
        "**Equilibrium** — the 50% midpoint of the h4 range, splitting it "
        "into premium (sell zone) and discount (buy zone).\n\n"
        "**dashed border** — the zone has been touched (mitigated) but "
        "not yet invalidated; still live, just already tested once.\n\n"
        "**Confluence Zone** — an HTF zone where 2+ of the above line up "
        "together (not yet shown on this chart — coming once the LTF "
        "entry-finding pass wires it in)."
    )

st.sidebar.markdown("---")
if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()

# ── Top Selectors ─────────────────────────────────────────────────────────────

c1, c2, c3 = st.columns([1.2, 1.0, 7.8])

with c1:
    symbol = st.selectbox("Symbol", list(ASSETS.keys()), label_visibility="collapsed")

dec        = ASSETS[symbol]["dec"]
raw_db     = ASSETS[symbol]["raw_db"]
curated_db = ASSETS[symbol]["curated_db"]

with c2:
    tf = st.selectbox("Timeframe", list(TF_MAP.keys()), index=1, label_visibility="collapsed")

table = TF_MAP[tf]

# ── Load Data ─────────────────────────────────────────────────────────────────

RESAMPLE_RULE = {"h4": "4h", "h6": "6h", "d1": "1d"}
if table in RESAMPLE_RULE:
    # h6: raw_<symbol>.h6 is never populated by any sync job -- resampled
    # from h1 on the fly instead, same as run_feature_engineering.py/
    # run_crt_detection.py do for h6 features and Equilibrium.
    # h4/d1: raw_<symbol>.{h4,d1} are deprecated (Yahoo-sourced,
    # DST-misaligned -- 27.8% of gold's h4 rows and 36.1%/58.3% of
    # gold's/eurusd's d1 rows sat on a shifted grid, see
    # docs/DECISIONS.md) -- both resampled from MT5 h1 instead, same
    # switch CRT equilibrium/features made. This does mean the 4h/1D
    # chart's range is now capped to h1's own depth (~Sep 2024 onward)
    # instead of the old deeper Yahoo history -- a known, accepted
    # trade-off, not a bug.
    df = load_ohlcv(raw_db, "h1", TF_ROW_LIMIT["1h"], use_rolling_window=True)
    if not df.empty:
        df = resample_ohlc(df, rule=RESAMPLE_RULE[table])
else:
    df = load_ohlcv(raw_db, table, TF_ROW_LIMIT[tf], use_rolling_window=(tf in ROLLING_WINDOW_TF))
if df.empty:
    st.warning("No data."); st.stop()

zones = load_active_zones(curated_db, symbol, dec, zone_timeframes)  # zone_timeframes is always () now -- see Overlays
crt_levels = load_crt_levels(curated_db, symbol, dec) if show_crt else []
sweeps = load_recent_sweeps(curated_db, symbol, dec) if show_sweep else []
nested_chains = load_nested_chains(curated_db, symbol) if show_chains else []

chains_total = len(nested_chains)
if zones_near_price_only and nested_chains:
    current_price = float(df["close_price"].iloc[-1])
    atr = load_latest_atr(curated_db, symbol)
    if atr:
        band = chain_atr_multiple * atr
        price_lo, price_hi = current_price - band, current_price + band
        # Filter whole chains by their TERMINAL (entry) zone's distance, not
        # each level independently -- a chain is one signal, splitting it
        # into "some levels shown, some not" would misrepresent it as
        # partial/broken rather than simply not near price right now.
        nested_chains = [c for c in nested_chains
                          if c["levels"] and c["levels"][-1]["zone_top"] >= price_lo
                          and c["levels"][-1]["zone_bottom"] <= price_hi]
        # Distance alone can still leave many chains stacked at the same
        # price cluster (a real, expected pattern -- not a bug, see prior
        # decluttering work) -- cap to the N most recent on top of it.
        # load_nested_chains already sorts DESC by confirmed_at_bar.
        nested_chains = nested_chains[:max_chains_shown]

# ── OHLC Info Bar ─────────────────────────────────────────────────────────────

latest = df.iloc[-1]
prev   = df.iloc[-2] if len(df) > 1 else latest
chg    = float(latest["close_price"]) - float(prev["close_price"])
pct    = (chg / float(prev["close_price"])) * 100 if float(prev["close_price"]) else 0
cls    = "up" if chg >= 0 else "dn"
sgn    = "+" if chg >= 0 else ""

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
  <span><span class="lbl">Nested Chains</span>&nbsp;<b style="color:#d4b16a">{len(nested_chains)}</b>{f' <span class="lbl">of {chains_total}</span>' if chains_total != len(nested_chains) else ''}</span>
</div>
""", unsafe_allow_html=True)

# ── Render Chart ──────────────────────────────────────────────────────────────

render_chart(df, zones, crt_levels, sweeps, dec, show_vol, show_grid,
             show_e20, show_e50, show_e100, show_sessions, nested_chains=nested_chains)
