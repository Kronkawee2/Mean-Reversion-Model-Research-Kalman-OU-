"""
Quant Trader Multi-Timeframe Interactive Web Dashboard
Directly queries local MySQL databases (gold / eurusd)
"""

import os
import sys
import pymysql
import pymysql.cursors
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

# Page configuration
st.set_page_config(
    page_title="Quant Trader - Multi-TF Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Dark Mode styling
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .stMetric {
        background-color: #161b22;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #30363d;
    }
    .stSelectbox, .stSlider { color: #ffffff; }
</style>
""", unsafe_allow_html=True)


# Database query helper
@st.cache_data(ttl=30)
def load_data(db_name: str, table_name: str, limit: int = 500) -> pd.DataFrame:
    host = os.getenv('DB_HOST', 'localhost')
    port = int(os.getenv('DB_PORT', 3306))
    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', '')

    try:
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=db_name, charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        query = f"""
            SELECT price_datetime, open_price, high_price, low_price, close_price, volume
            FROM `{table_name}`
            ORDER BY price_datetime DESC
            LIMIT %s
        """
        cursor = conn.cursor()
        cursor.execute(query, (limit,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        df = pd.DataFrame(rows)
        if not df.empty:
            df['price_datetime'] = pd.to_datetime(df['price_datetime'])
            df = df.sort_values('price_datetime').reset_index(drop=True)
            for col in ['open_price', 'high_price', 'low_price', 'close_price']:
                df[col] = df[col].astype(float)
        return df
    except Exception as e:
        st.error(f"Error connecting to MySQL: {e}")
        return pd.DataFrame()


# --- SIDEBAR CONFIGURATION ---
st.sidebar.title("📈 Quant Trader Config")

asset = st.sidebar.selectbox(
    "Select Asset",
    options=["Gold (XAUUSD)", "EUR/USD"],
    index=0
)

db_name = "gold" if asset == "Gold (XAUUSD)" else "eurusd"

tf = st.sidebar.selectbox(
    "Select Timeframe (TF)",
    options=["5m", "15m", "1h", "4h", "6h", "1d"],
    index=2  # default 1h
)

table_map = {"5m": "m5", "15m": "m15", "1h": "h1", "4h": "h4", "6h": "h6", "1d": "d1"}
table_name = table_map[tf]

limit = st.sidebar.slider("Number of Candles", min_value=50, max_value=1000, value=200, step=50)

st.sidebar.markdown("---")
st.sidebar.subheader("EMA Trend Overlay")
show_ema20 = st.sidebar.checkbox("Show EMA 20 (Short-term)", value=True)
show_ema50 = st.sidebar.checkbox("Show EMA 50 (Medium-term)", value=True)
show_ema100 = st.sidebar.checkbox("Show EMA 100 (Long-term)", value=True)

if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()

# --- MAIN CONTENT ---
st.title(f"📊 {asset} — {tf.upper()} Candlestick Chart")

df = load_data(db_name, table_name, limit)

if df.empty:
    st.warning("No price data found in MySQL for this timeframe. Please run quant_backend.py first.")
    st.stop()

# Calculate EMA Overlay
close_prices = df['close_price']
if show_ema20:
    df['EMA_20'] = close_prices.ewm(span=20, adjust=False).mean()
if show_ema50:
    df['EMA_50'] = close_prices.ewm(span=50, adjust=False).mean()
if show_ema100:
    df['EMA_100'] = close_prices.ewm(span=100, adjust=False).mean()

# Latest Metrics Bar
latest = df.iloc[-1]
prev = df.iloc[-2] if len(df) > 1 else latest

price_change = latest['close_price'] - prev['close_price']
pct_change = (price_change / prev['close_price']) * 100 if prev['close_price'] != 0 else 0

decimals = 2 if db_name == "gold" else 5

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Close Price", f"{latest['close_price']:.{decimals}f}", f"{price_change:+.{decimals}f} ({pct_change:+.2f}%)")
col2.metric("High", f"{latest['high_price']:.{decimals}f}")
col3.metric("Low", f"{latest['low_price']:.{decimals}f}")
col4.metric("Open", f"{latest['open_price']:.{decimals}f}")
col5.metric("Volume", f"{int(latest['volume']):,}")

st.markdown("---")

# Plotly Candlestick Chart
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    row_heights=[0.8, 0.2]
)

# Candlestick
fig.add_trace(
    go.Candlestick(
        x=df['price_datetime'],
        open=df['open_price'],
        high=df['high_price'],
        low=df['low_price'],
        close=df['close_price'],
        name="OHLC",
        increasing_line_color='#00c853',
        decreasing_line_color='#ff3d00'
    ),
    row=1, col=1
)

# EMA Overlays
if show_ema20:
    fig.add_trace(
        go.Scatter(x=df['price_datetime'], y=df['EMA_20'], mode='lines', name='EMA 20', line=dict(color='#29b6f6', width=1.5)),
        row=1, col=1
    )
if show_ema50:
    fig.add_trace(
        go.Scatter(x=df['price_datetime'], y=df['EMA_50'], mode='lines', name='EMA 50', line=dict(color='#ffca28', width=1.5)),
        row=1, col=1
    )
if show_ema100:
    fig.add_trace(
        go.Scatter(x=df['price_datetime'], y=df['EMA_100'], mode='lines', name='EMA 100', line=dict(color='#ab47bc', width=1.5)),
        row=1, col=1
    )

# Volume Bar Chart
colors = ['#00c853' if c >= o else '#ff3d00' for c, o in zip(df['close_price'], df['open_price'])]
fig.add_trace(
    go.Bar(x=df['price_datetime'], y=df['volume'], name="Volume", marker_color=colors, opacity=0.7),
    row=2, col=1
)

# Layout styling
fig.update_layout(
    template="plotly_dark",
    height=650,
    margin=dict(l=10, r=10, t=10, b=10),
    xaxis_rangeslider_visible=False,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)

fig.update_yaxes(title_text="Price", row=1, col=1)
fig.update_yaxes(title_text="Volume", row=2, col=1)

st.plotly_chart(fig, use_container_width=True)

# Data Table Tab
with st.expander("📋 View Raw Data Table"):
    st.dataframe(df.sort_values('price_datetime', ascending=False), use_container_width=True)
