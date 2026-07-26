"""
Streamlit page: Real-time Gold Price Feed.
"""

import streamlit as st
from datetime import datetime
import pandas as pd

st.set_page_config(page_title="Real-time Gold")

st.title("Real-time Gold Price Feed")
st.markdown("Latest gold price data from Yahoo Finance")

col1, col2 = st.columns(2)

with col1:
    symbol = st.selectbox(
        "Symbol",
        options=["GC=F", "XAUUSD=X", "GLD", "IAU"],
        format_func=lambda x: {
            "GC=F": "Gold Futures",
            "XAUUSD=X": "Gold/USD Spot",
            "GLD": "SPDR Gold ETF",
            "IAU": "iShares Gold ETF",
        }.get(x, x)
    )

with col2:
    interval = st.selectbox(
        "Interval",
        options=["1d", "1h", "5m", "15m"],
        format_func=lambda x: {
            "1d": "Daily",
            "1h": "Hourly",
            "5m": "5 Minutes",
            "15m": "15 Minutes",
        }.get(x, x)
    )

st.divider()

try:
    import yfinance as yf

    ticker = yf.Ticker(symbol)

    period_map = {
        "1d": "1mo",
        "1h": "5d",
        "5m": "1d",
        "15m": "5d",
    }
    period = period_map.get(interval, "5d")

    df = ticker.history(period=period, interval=interval)

    if df.empty:
        st.warning(f"No data found for {symbol}")
        st.stop()

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    price_change = float(latest['Close']) - float(prev['Close'])
    price_change_pct = (price_change / float(prev['Close'])) * 100

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "Latest Price",
            f"${float(latest['Close']):,.2f}",
            f"${price_change:+.2f} ({price_change_pct:+.2f}%)"
        )
    with col2:
        st.metric("High", f"${float(latest['High']):,.2f}")
    with col3:
        st.metric("Low", f"${float(latest['Low']):,.2f}")
    with col4:
        vol = int(latest['Volume']) if pd.notna(latest['Volume']) else 0
        st.metric("Volume", f"{vol:,}")

    st.divider()

    st.subheader(f"{symbol} - {interval} Chart")
    st.line_chart(df['Close'], use_container_width=True)

    st.subheader("Volume")
    st.bar_chart(df['Volume'], use_container_width=True)

    st.subheader("Recent Data")

    display_df = df.tail(20).copy()
    display_df.index = display_df.index.strftime('%Y-%m-%d %H:%M')
    display_df = display_df[['Open', 'High', 'Low', 'Close', 'Volume']]
    display_df = display_df.round(2)
    display_df = display_df.sort_index(ascending=False)

    st.dataframe(display_df, use_container_width=True)

    st.info(f"Data from Yahoo Finance | Last Updated: {datetime.now().strftime('%H:%M:%S')}")

except ImportError:
    st.error("yfinance not installed. Run: pip install yfinance")

except Exception as e:
    st.error(f"Error: {e}")
    st.info("Please check network connection and try again.")
