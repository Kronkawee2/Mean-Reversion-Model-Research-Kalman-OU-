"""
Main Streamlit Dashboard - Gold Yahoo Finance Tracker.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import logging

st.set_page_config(
    page_title="Gold Yahoo Finance Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .bullish {
        color: #00d084;
        font-weight: bold;
    }
    .bearish {
        color: #ff4b4b;
        font-weight: bold;
    }
    .neutral {
        color: #808080;
        font-weight: bold;
    }
    .stMetric {
        background-color: #1e1e2e;
        padding: 15px;
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

st.title("Gold Yahoo Finance Dashboard")
st.markdown("Gold price data and technical analysis from Yahoo Finance")

st.sidebar.title("Configuration")

symbol = st.sidebar.selectbox(
    "Symbol",
    options=["GC=F", "XAUUSD=X", "GLD", "IAU"],
    format_func=lambda x: {
        "GC=F": "GC=F (Gold Futures)",
        "XAUUSD=X": "XAUUSD=X (Gold/USD Spot)",
        "GLD": "GLD (SPDR Gold ETF)",
        "IAU": "IAU (iShares Gold ETF)",
    }.get(x, x)
)

time_range = st.sidebar.selectbox(
    "Time Range",
    options=["5d", "1mo", "3mo", "6mo", "1y"],
    format_func=lambda x: {
        "5d": "5 Days",
        "1mo": "1 Month",
        "3mo": "3 Months",
        "6mo": "6 Months",
        "1y": "1 Year",
    }.get(x, x)
)

st.sidebar.info(
    "Price data from Yahoo Finance, refreshed daily.\n\n"
    "Includes RSI, SMA, MACD, Bollinger Bands with "
    "BULLISH / NEUTRAL / BEARISH signals."
)


try:
    import yfinance as yf
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from analysis.technical_analysis import TechnicalAnalyzer

    ticker = yf.Ticker(symbol)
    df = ticker.history(period=time_range, interval="1d")

    if df.empty:
        st.error(f"No data found for {symbol}")
        st.stop()

    analyzer = TechnicalAnalyzer()
    analysis = analyzer.analyze(df)

    tab1, tab2, tab3 = st.tabs(["Overview", "Technical Analysis", "Data Table"])

    with tab1:
        st.header("Gold Price Overview")

        col1, col2, col3, col4 = st.columns(4)

        latest_close = analysis['close']
        price_change = analysis['price_change']
        price_change_pct = analysis['price_change_pct']

        with col1:
            st.metric(
                "Close Price",
                f"${latest_close:,.2f}",
                f"${price_change:+.2f} ({price_change_pct:+.2f}%)"
            )

        with col2:
            signal = analysis['signal']
            st.metric(
                "Overall Signal",
                signal,
                f"Bullish: {analysis['bullish_count']} | Bearish: {analysis['bearish_count']}"
            )

        with col3:
            rsi = analysis['indicators']['rsi_14']
            rsi_status = "Overbought" if rsi > 70 else "Oversold" if rsi < 30 else "Neutral"
            st.metric("RSI (14)", f"{rsi:.1f}", rsi_status)

        with col4:
            volume = int(df['Volume'].iloc[-1]) if pd.notna(df['Volume'].iloc[-1]) else 0
            st.metric("Volume", f"{volume:,}")

        st.subheader(f"Price Chart: {symbol}")
        st.line_chart(df['Close'], use_container_width=True)

        st.subheader("Latest Price Summary")

        latest = df.iloc[-1]
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Open", f"${float(latest['Open']):,.2f}")
        with col2:
            st.metric("High", f"${float(latest['High']):,.2f}")
        with col3:
            st.metric("Low", f"${float(latest['Low']):,.2f}")
        with col4:
            st.metric("Close", f"${float(latest['Close']):,.2f}")

    with tab2:
        st.header("Technical Indicators")

        st.subheader("Signals Summary")

        for sig in analysis['signals']:
            col1, col2, col3 = st.columns([1, 1, 4])

            with col1:
                st.write(f"**{sig['type']}**")
            with col2:
                st.write(f"**{sig['label']}**")
            with col3:
                st.write(sig['description'])

        st.divider()

        st.subheader("Indicators")

        ind = analysis['indicators']
        col1, col2, col3 = st.columns(3)

        with col1:
            st.write("**Moving Averages**")
            st.write(f"- SMA 20: ${ind['sma_20']:,.2f}")
            st.write(f"- SMA 50: ${ind['sma_50']:,.2f}")
            st.write(f"- SMA 200: ${ind['sma_200']:,.2f}")
            st.write(f"- EMA 20: ${ind['ema_20']:,.2f}")

        with col2:
            st.write("**MACD**")
            st.write(f"- MACD: {ind['macd_value']:.4f}")
            st.write(f"- Signal: {ind['macd_signal']:.4f}")
            st.write(f"- Histogram: {ind['macd_histogram']:.4f}")

        with col3:
            st.write("**Bollinger Bands**")
            st.write(f"- Upper: ${ind['bb_upper']:,.2f}")
            st.write(f"- Middle: ${ind['bb_middle']:,.2f}")
            st.write(f"- Lower: ${ind['bb_lower']:,.2f}")
            st.write(f"- RSI (14): {ind['rsi_14']:.1f}")

        st.subheader("Price vs Moving Averages")

        ma_analyzer = TechnicalAnalyzer()
        sma_20 = ma_analyzer.calculate_sma(df['Close'], 20)
        sma_50 = ma_analyzer.calculate_sma(df['Close'], 50)

        ma_df = pd.DataFrame({
            'Close': df['Close'],
            'SMA 20': sma_20,
            'SMA 50': sma_50,
        }, index=df.index)

        st.line_chart(ma_df, use_container_width=True)

    with tab3:
        st.header("Price Data Table (OHLCV)")

        display_df = df.copy()
        display_df.index = display_df.index.strftime('%Y-%m-%d')
        display_df = display_df[['Open', 'High', 'Low', 'Close', 'Volume']]
        display_df = display_df.round(2)
        display_df = display_df.sort_index(ascending=False)

        st.dataframe(display_df, use_container_width=True)

        csv = display_df.to_csv()
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name=f"{symbol}_{time_range}.csv",
            mime="text/csv"
        )

except ImportError as e:
    st.error(f"Missing dependency: {e}")
    st.info("Run: pip install -r requirements.txt")

except Exception as e:
    st.error(f"Error: {e}")
    st.info("Please check network connection and try again.")

st.divider()
col1, col2, col3 = st.columns(3)

with col1:
    st.write("Data Source: Yahoo Finance")

with col2:
    st.write(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

with col3:
    st.write("Dashboard v2.0 - Yahoo Finance Edition")
