"""
Streamlit page: Price Trends & Historical Analysis.
"""

import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="trends")

st.title("Gold Price Trends")
st.markdown("Gold price trends and moving averages analysis")

col1, col2 = st.columns(2)

with col1:
    symbol = st.selectbox(
        "Symbol",
        options=["GC=F", "XAUUSD=X", "GLD"],
        format_func=lambda x: {
            "GC=F": "Gold Futures",
            "XAUUSD=X": "Gold/USD Spot",
            "GLD": "SPDR Gold ETF",
        }.get(x, x)
    )

with col2:
    period = st.selectbox(
        "Time Range",
        options=["1mo", "3mo", "6mo", "1y", "2y"],
        format_func=lambda x: {
            "1mo": "1 Month",
            "3mo": "3 Months",
            "6mo": "6 Months",
            "1y": "1 Year",
            "2y": "2 Years",
        }.get(x, x),
        index=2
    )

try:
    import yfinance as yf
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from analysis.technical_analysis import TechnicalAnalyzer

    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval="1d")

    if df.empty:
        st.warning(f"No data found for {symbol}")
        st.stop()

    analyzer = TechnicalAnalyzer()

    st.subheader("Price vs Moving Averages")

    sma_20 = analyzer.calculate_sma(df['Close'], 20)
    sma_50 = analyzer.calculate_sma(df['Close'], 50)
    ema_20 = analyzer.calculate_ema(df['Close'], 20)

    chart_df = pd.DataFrame({
        'Close': df['Close'],
        'SMA 20': sma_20,
        'SMA 50': sma_50,
        'EMA 20': ema_20,
    }, index=df.index)

    st.line_chart(chart_df, use_container_width=True)

    st.subheader("RSI (Relative Strength Index)")

    rsi = analyzer.calculate_rsi(df['Close'], 14)
    rsi_df = pd.DataFrame({'RSI': rsi}, index=df.index)
    st.line_chart(rsi_df, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.write("Overbought > 70")
    with col2:
        st.write("Neutral 30-70")
    with col3:
        st.write("Oversold < 30")

    st.subheader("Bollinger Bands")

    bb = analyzer.calculate_bollinger_bands(df['Close'])
    bb_df = pd.DataFrame({
        'Close': df['Close'],
        'Upper Band': bb['upper'],
        'Middle Band': bb['middle'],
        'Lower Band': bb['lower'],
    }, index=df.index)

    st.line_chart(bb_df, use_container_width=True)

    st.subheader("Volume Trend")
    st.bar_chart(df['Volume'], use_container_width=True)

    st.subheader("Summary Statistics")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        avg_close = df['Close'].mean()
        st.metric("Avg Close", f"${avg_close:,.2f}")

    with col2:
        max_high = df['High'].max()
        st.metric("Max High", f"${max_high:,.2f}")

    with col3:
        min_low = df['Low'].min()
        st.metric("Min Low", f"${min_low:,.2f}")

    with col4:
        total_days = len(df)
        st.metric("Trading Days", f"{total_days}")

    st.subheader("Performance")

    first_close = float(df['Close'].iloc[0])
    last_close = float(df['Close'].iloc[-1])
    total_change = last_close - first_close
    total_change_pct = (total_change / first_close) * 100

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Change", f"${total_change:+,.2f}", f"{total_change_pct:+.2f}%")
    with col2:
        daily_returns = df['Close'].pct_change().dropna()
        volatility = daily_returns.std() * np.sqrt(252) * 100
        st.metric("Annualized Volatility", f"{volatility:.1f}%")

    st.info(f"Displaying {len(df)} trading days | Source: Yahoo Finance")

except ImportError as e:
    st.error(f"Missing dependency: {e}")

except Exception as e:
    st.error(f"Error: {e}")
