"""
Quant Trader Dashboard — Minimal Trading Interface
Connects to local MySQL Bronze databases and renders multi-timeframe charts.
"""

import os
import sys
import json
import pymysql
import pymysql.cursors
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

st.set_page_config(
    page_title="Quant Trader",
    page_icon="Q",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -- Palette --

C = {
    "bg":         "#000000",
    "chart_bg":   "#000000",
    "card_bg":    "#111111",
    "border":     "#222222",
    "text":       "#d1d4dc",
    "text_dim":   "#787b86",
    "up":         "#26a69a",
    "down":       "#ef5350",
    "ema1":       "#888888",      # gray
    "ema2":       "#d4b16a",      # soft earth yellow
    "ema3":       "#415a77",      # earth navy
    "vol_up":     "rgba(38,166,154,0.3)",
    "vol_down":   "rgba(239,83,80,0.3)",
    "crosshair":  "#758696",
    "grid":       "#1a1a1a",
}

# -- CSS --

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

    .stApp {{
        background-color: {C['bg']};
        font-family: 'Inter', -apple-system, sans-serif;
    }}

    header[data-testid="stHeader"] {{
        background-color: {C['bg']};
    }}

    .block-container {{
        padding: 2.8rem 1rem 0 1rem;
        max-width: 100%;
    }}

    /* Sidebar as tool panel */
    section[data-testid="stSidebar"] {{
        background-color: {C['card_bg']};
        border-right: 1px solid {C['border']};
        width: 260px !important;
    }}

    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stCheckbox label,
    section[data-testid="stSidebar"] .stSlider label {{
        color: {C['text_dim']};
        font-size: 12px;
    }}

    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown h3 {{
        color: {C['text']};
    }}

    /* OHLC bar */
    .tv-ohlc-bar {{
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 8px 14px;
        background: {C['card_bg']};
        border: 1px solid {C['border']};
        border-radius: 4px;
        margin-bottom: 4px;
        font-size: 13px;
        font-variant-numeric: tabular-nums;
    }}

    .tv-ohlc-bar .sep {{
        width: 1px;
        height: 22px;
        background: {C['border']};
    }}

    .tv-ohlc-bar .lbl {{ color: {C['text_dim']}; font-size: 11px; }}
    .tv-ohlc-bar .val {{ color: {C['text']}; font-weight: 500; margin-left: 2px; }}
    .tv-ohlc-bar .up {{ color: {C['up']}; }}
    .tv-ohlc-bar .down {{ color: {C['down']}; }}

    /* Metric cards */
    div[data-testid="stMetric"] {{
        background: {C['card_bg']};
        border: 1px solid {C['border']};
        border-radius: 4px;
        padding: 8px 12px;
    }}

    div[data-testid="stMetric"] label {{
        color: {C['text_dim']} !important;
        font-size: 11px;
    }}

    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {{
        color: {C['text']};
        font-size: 18px;
    }}

    hr {{ border-color: {C['border']}; }}
</style>
""", unsafe_allow_html=True)


# -- Data layer --

ASSETS = {
    "XAUUSD":   {"db": "gold",   "decimals": 2, "label": "Gold Futures"},
    "EURUSD":   {"db": "eurusd", "decimals": 5, "label": "EUR/USD"},
    "DXY":      {"db": "dxy",    "decimals": 3, "label": "Dollar Index"},
    "US10Y":    {"db": "us10y",  "decimals": 3, "label": "10Y Yield"},
    "VIX":      {"db": "vix",    "decimals": 2, "label": "Volatility"},
    "GDX":      {"db": "gdx",    "decimals": 2, "label": "Gold Miners"},
}

TF_MAP = {"5m": "m5", "15m": "m15", "1h": "h1", "4h": "h4", "6h": "h6", "1D": "d1"}


@st.cache_data(ttl=30)
def load_ohlcv(db_name: str, table: str) -> pd.DataFrame:
    """Fetch all available OHLCV rows for a given table."""
    try:
        conn = pymysql.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            port=int(os.getenv('DB_PORT', 3306)),
            user=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', ''),
            database=db_name, charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT price_datetime, open_price, high_price, low_price, close_price, volume
            FROM `{table}` ORDER BY price_datetime ASC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        df = pd.DataFrame(rows)
        if not df.empty:
            df['price_datetime'] = pd.to_datetime(df['price_datetime'])
            df = df.sort_values('price_datetime').reset_index(drop=True)
            for col in ['open_price', 'high_price', 'low_price', 'close_price']:
                df[col] = df[col].astype(float)
            df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        st.error(f"MySQL: {e}")
        return pd.DataFrame()


def get_available_tfs(db_name: str):
    available = []
    for tf_label, tbl in TF_MAP.items():
        try:
            conn = pymysql.connect(
                host=os.getenv('DB_HOST', 'localhost'),
                port=int(os.getenv('DB_PORT', 3306)),
                user=os.getenv('DB_USER', 'root'),
                password=os.getenv('DB_PASSWORD', ''),
                database=db_name, charset='utf8mb4',
            )
            cursor = conn.cursor()
            cursor.execute(f"SELECT 1 FROM `{tbl}` LIMIT 1")
            cursor.close()
            conn.close()
            available.append(tf_label)
        except Exception:
            pass
    return available


def to_chart_json(df, col_map):
    records = []
    for _, row in df.iterrows():
        ts = int(row['price_datetime'].timestamp())
        r = {"time": ts}
        for k, v in col_map.items():
            r[k] = round(row[v], 5)
        records.append(r)
    return json.dumps(records)


def to_line_json(series, dt_series):
    records = []
    for dt, val in zip(dt_series, series):
        if pd.notna(val):
            records.append({"time": int(dt.timestamp()), "value": round(val, 5)})
    return json.dumps(records)


def to_volume_json(df):
    records = []
    for _, row in df.iterrows():
        ts = int(row['price_datetime'].timestamp())
        is_up = row['close_price'] >= row['open_price']
        records.append({
            "time": ts,
            "value": row['volume'],
            "color": C['vol_up'] if is_up else C['vol_down'],
        })
    return json.dumps(records)


# -- Top bar: Asset + TF + Candle Color selection --

top_c1, top_c2, top_c3, top_c4 = st.columns([1.2, 1, 1.5, 6.3])

with top_c1:
    symbol = st.selectbox("Asset", options=list(ASSETS.keys()), index=0, label_visibility="collapsed")

asset = ASSETS[symbol]
db_name = asset["db"]
decimals = asset["decimals"]

available_tfs = get_available_tfs(db_name)
if not available_tfs:
    st.error(f"No data for {symbol}. Run: python main.py")
    st.stop()

tf_default_idx = available_tfs.index("5m") if "5m" in available_tfs else 0
with top_c2:
    tf = st.selectbox("TF", options=available_tfs, index=tf_default_idx, label_visibility="collapsed")

table = TF_MAP[tf]

with top_c3:
    candle_style = st.selectbox("Color", ["Green / Red", "Cyan / Red", "White / Black"], index=2, label_visibility="collapsed")

if candle_style == "Green / Red":
    c_up, c_down = "#26a69a", "#ef5350"
elif candle_style == "Cyan / Red":
    c_up, c_down = "#00bcd4", "#ef5350"
else:
    c_up, c_down = "#d1d4dc", "#555555"

# -- Sidebar (chart settings only) --

st.sidebar.markdown("### Chart Settings")
st.sidebar.markdown("---")

show_vol = st.sidebar.checkbox("Volume", value=False)
show_grid = st.sidebar.checkbox("Grid Lines", value=True)
show_ema20 = st.sidebar.checkbox("EMA 20", value=False)
show_ema50 = st.sidebar.checkbox("EMA 50", value=False)
show_ema100 = st.sidebar.checkbox("EMA 100", value=False)

st.sidebar.markdown("---")
if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()


# -- Load all data --

df = load_ohlcv(db_name, table)

if df.empty:
    st.warning("No data available.")
    st.stop()

# -- OHLC info bar --

latest = df.iloc[-1]
prev = df.iloc[-2] if len(df) > 1 else latest

chg = latest['close_price'] - prev['close_price']
pct = (chg / prev['close_price']) * 100 if prev['close_price'] != 0 else 0
chg_class = "up" if chg >= 0 else "down"
sign = "+" if chg >= 0 else ""

candle_count = len(df)

st.markdown(f"""
<div class="tv-ohlc-bar">
    <span><span class="lbl">O</span><span class="val">{latest['open_price']:.{decimals}f}</span></span>
    <span><span class="lbl">H</span><span class="val">{latest['high_price']:.{decimals}f}</span></span>
    <span><span class="lbl">L</span><span class="val">{latest['low_price']:.{decimals}f}</span></span>
    <span><span class="lbl">C</span><span class="val {chg_class}">{latest['close_price']:.{decimals}f}</span></span>
    <span class="sep"></span>
    <span class="{chg_class}">{sign}{chg:.{decimals}f} ({sign}{pct:.2f}%)</span>
    <span class="sep"></span>
    <span><span class="lbl">Vol</span><span class="val">{int(latest['volume']):,}</span></span>
    <span class="sep"></span>
    <span><span class="lbl">Candles</span><span class="val">{candle_count:,}</span></span>
</div>
""", unsafe_allow_html=True)

# -- Build chart data --

candle_data = to_chart_json(df, {"open": "open_price", "high": "high_price", "low": "low_price", "close": "close_price"})
volume_data = to_volume_json(df)

close = df['close_price']
ema20_data = to_line_json(close.ewm(span=20, adjust=False).mean(), df['price_datetime'])
ema50_data = to_line_json(close.ewm(span=50, adjust=False).mean(), df['price_datetime'])
ema100_data = to_line_json(close.ewm(span=100, adjust=False).mean(), df['price_datetime'])

grid_color = C['grid'] if show_grid else "transparent"
vol_margin = "0.28" if show_vol else "0.02"

# -- EMA series JS --

ema_js = ""
if show_ema20:
    ema_js += f"""
        const ema20 = chart.addLineSeries({{
            color: '{C["ema1"]}', lineWidth: 1, title: 'EMA 20',
            lastValueVisible: false, priceLineVisible: false,
        }});
        ema20.setData({ema20_data});
    """
if show_ema50:
    ema_js += f"""
        const ema50 = chart.addLineSeries({{
            color: '{C["ema2"]}', lineWidth: 1, title: 'EMA 50',
            lastValueVisible: false, priceLineVisible: false,
        }});
        ema50.setData({ema50_data});
    """
if show_ema100:
    ema_js += f"""
        const ema100 = chart.addLineSeries({{
            color: '{C["ema3"]}', lineWidth: 1, title: 'EMA 100',
            lastValueVisible: false, priceLineVisible: false,
        }});
        ema100.setData({ema100_data});
    """

# -- Volume JS --

vol_js = ""
if show_vol:
    vol_js = f"""
        const volSeries = chart.addHistogramSeries({{
            priceFormat: {{ type: 'volume' }},
            priceScaleId: 'vol',
            lastValueVisible: false,
            priceLineVisible: false,
        }});
        volSeries.priceScale().applyOptions({{
            scaleMargins: {{ top: 0.82, bottom: 0 }},
        }});
        volSeries.setData({volume_data});
    """

# -- Render chart --

chart_html = f"""
<!DOCTYPE html>
<html>
<head>
    <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        body {{ margin: 0; padding: 0; background: {C['chart_bg']}; overflow: hidden; }}
        #chart {{ width: 100%; height: 100vh; }}
    </style>
</head>
<body>
    <div id="chart"></div>
    <script>
        const container = document.getElementById('chart');

        const chart = LightweightCharts.createChart(container, {{
            width: container.offsetWidth,
            height: container.offsetHeight,
            layout: {{
                background: {{ type: 'solid', color: '{C["chart_bg"]}' }},
                textColor: '{C["text_dim"]}',
                fontFamily: 'Inter, -apple-system, sans-serif',
                fontSize: 11,
            }},
            grid: {{
                vertLines: {{ color: '{grid_color}' }},
                horzLines: {{ color: '{grid_color}' }},
            }},
            crosshair: {{
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {{
                    color: '{C["crosshair"]}',
                    width: 1,
                    style: LightweightCharts.LineStyle.Dashed,
                    labelBackgroundColor: '#333',
                }},
                horzLine: {{
                    color: '{C["crosshair"]}',
                    width: 1,
                    style: LightweightCharts.LineStyle.Dashed,
                    labelBackgroundColor: '#333',
                }},
            }},
            rightPriceScale: {{
                borderColor: '{C["border"]}',
                scaleMargins: {{ top: 0.05, bottom: {vol_margin} }},
            }},
            timeScale: {{
                borderColor: '{C["border"]}',
                timeVisible: true,
                secondsVisible: false,
                rightOffset: 5,
            }},
            handleScroll: {{ vertTouchDrag: false }},
        }});

        // Candlestick (no price line, no last value label)
        const candleSeries = chart.addCandlestickSeries({{
            upColor: '{c_up}',
            downColor: '{c_down}',
            borderUpColor: '{c_up}',
            borderDownColor: '{c_down}',
            wickUpColor: '{c_up}',
            wickDownColor: '{c_down}',
            lastValueVisible: false,
            priceLineVisible: false,
        }});
        candleSeries.setData({candle_data});

        {ema_js}
        {vol_js}

        chart.timeScale().fitContent();

        window.addEventListener('resize', () => {{
            chart.applyOptions({{
                width: container.offsetWidth,
                height: container.offsetHeight,
            }});
        }});
    </script>
</body>
</html>
"""

components.html(chart_html, height=560, scrolling=False)
