"""
Streamlit page: Technical Analysis Detail.
"""

import streamlit as st
import pandas as pd

st.set_page_config(page_title="analysis")

st.title("Technical Analysis Detail")
st.markdown("Detailed technical indicator analysis for gold trading decisions")

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
        options=["6mo", "1y", "2y"],
        format_func=lambda x: {
            "6mo": "6 Months",
            "1y": "1 Year",
            "2y": "2 Years",
        }.get(x, x),
        index=1
    )

st.divider()

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
    result = analyzer.analyze(df)

    signal = result['signal']
    st.header(f"Overall Signal: {signal}")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Close Price", f"${result['close']:,.2f}")
    with col2:
        st.metric("Price Change", f"${result['price_change']:+,.2f}", f"{result['price_change_pct']:+.2f}%")
    with col3:
        st.metric("Score", f"Bullish {result['bullish_count']} : {result['bearish_count']} Bearish")

    st.divider()

    st.header("Signals by Indicator")

    for sig in result['signals']:
        with st.container():
            col1, col2, col3 = st.columns([2, 2, 4])

            with col1:
                st.write(f"### {sig['type']}")
            with col2:
                st.write(f"### {sig['label']}")
            with col3:
                st.write(f"_{sig['description']}_")

            st.divider()

    st.header("All Indicators Value")

    ind = result['indicators']
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("Momentum")
        momentum_data = {
            'Indicator': ['RSI (14)'],
            'Value': [f"{ind['rsi_14']:.1f}"],
            'Signal': [
                'Oversold' if ind['rsi_14'] < 30
                else 'Overbought' if ind['rsi_14'] > 70
                else 'Neutral'
            ],
        }
        st.dataframe(pd.DataFrame(momentum_data), hide_index=True)

    with col2:
        st.subheader("Moving Averages")
        close = result['close']
        ma_data = {
            'Type': ['SMA 20', 'SMA 50', 'SMA 200', 'EMA 20'],
            'Value': [
                f"${ind['sma_20']:,.2f}",
                f"${ind['sma_50']:,.2f}",
                f"${ind['sma_200']:,.2f}",
                f"${ind['ema_20']:,.2f}"
            ],
            'vs Price': [
                'Above' if close > ind['sma_20'] else 'Below',
                'Above' if close > ind['sma_50'] else 'Below',
                'Above' if close > ind['sma_200'] else 'Below',
                'Above' if close > ind['ema_20'] else 'Below',
            ],
        }
        st.dataframe(pd.DataFrame(ma_data), hide_index=True)

    with col3:
        st.subheader("MACD")
        macd_signal = 'Bullish' if ind['macd_value'] > ind['macd_signal'] else 'Bearish'
        macd_data = {
            'Component': ['MACD Line', 'Signal Line', 'Histogram'],
            'Value': [
                f"{ind['macd_value']:.4f}",
                f"{ind['macd_signal']:.4f}",
                f"{ind['macd_histogram']:.4f}"
            ],
            'Signal': [
                macd_signal,
                '',
                'Expanding' if ind['macd_histogram'] > 0 else 'Contracting'
            ],
        }
        st.dataframe(pd.DataFrame(macd_data), hide_index=True)

    st.subheader("Bollinger Bands")

    col1, col2 = st.columns(2)

    with col1:
        bb_data = {
            'Band': ['Upper', 'Middle', 'Lower', 'Current Price'],
            'Value': [
                f"${ind['bb_upper']:,.2f}",
                f"${ind['bb_middle']:,.2f}",
                f"${ind['bb_lower']:,.2f}",
                f"${close:,.2f}"
            ],
        }
        st.dataframe(pd.DataFrame(bb_data), hide_index=True)

    with col2:
        bb_range = ind['bb_upper'] - ind['bb_lower']
        position = (close - ind['bb_lower']) / bb_range * 100 if bb_range > 0 else 50

        st.metric("Position in Bands", f"{position:.1f}%")

        if position > 80:
            st.warning("Price close to Upper Band - Potential Pullback")
        elif position < 20:
            st.success("Price close to Lower Band - Potential Bounce")
        else:
            st.info("Price within normal range")

    st.header("Compare Symbols")

    compare_symbols = st.multiselect(
        "Select symbols to compare",
        options=["GC=F", "XAUUSD=X", "GLD", "IAU", "SI=F"],
        default=["GC=F", "GLD"]
    )

    if len(compare_symbols) >= 2:
        compare_data = []
        for sym in compare_symbols:
            try:
                t = yf.Ticker(sym)
                d = t.history(period="6mo", interval="1d")
                if not d.empty:
                    r = analyzer.analyze(d)
                    compare_data.append({
                        'Symbol': sym,
                        'Close': f"${r['close']:,.2f}",
                        'Change': f"{r['price_change_pct']:+.2f}%",
                        'RSI': f"{r['indicators']['rsi_14']:.1f}",
                        'Signal': r['signal'],
                        'Bullish': r['bullish_count'],
                        'Bearish': r['bearish_count'],
                    })
            except Exception:
                pass

        if compare_data:
            st.dataframe(pd.DataFrame(compare_data), hide_index=True, use_container_width=True)

    st.info("Yahoo Finance data - Technical analysis calculated in real-time")

except ImportError as e:
    st.error(f"Missing dependency: {e}")

except Exception as e:
    st.error(f"Error: {e}")
