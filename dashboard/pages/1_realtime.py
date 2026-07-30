"""
Quant Trader — TradingView Advanced Interactive Chart Page
"""

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="realtime",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

    .stApp {
        background-color: #000000;
        font-family: 'Inter', -apple-system, sans-serif;
    }

    header[data-testid="stHeader"] {
        background-color: #000000;
    }

    .block-container {
        padding: 2.8rem 0.5rem 0 0.5rem;
        max-width: 100%;
    }

    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


ASSET_TV_MAP = {
    "XAUUSD (Gold)":    {"symbol": "OANDA:XAUUSD"},
    "EUR/USD":           {"symbol": "FX:EURUSD"},
    "DXY (Dollar)":      {"symbol": "CAPITALCOM:DXY"},
    "US 10Y Yield":      {"symbol": "TVC:US10Y"},
    "VIX (Volatility)":  {"symbol": "TVC:VIX"},
    "GDX (Gold Miners)": {"symbol": "AMEX:GDX"},
}

TF_TV_MAP = {
    "5m": "5",
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "6h": "360",
    "1D": "D"
}

col1, col2, col3 = st.columns([2, 1.5, 6.5])

with col1:
    selected_asset_label = st.selectbox(
        "Asset",
        options=list(ASSET_TV_MAP.keys()),
        index=0,
        label_visibility="collapsed"
    )

with col2:
    selected_tf_label = st.selectbox(
        "Timeframe",
        options=list(TF_TV_MAP.keys()),
        index=0,
        label_visibility="collapsed"
    )

tv_symbol = ASSET_TV_MAP[selected_asset_label]["symbol"]
tv_interval = TF_TV_MAP[selected_tf_label]

tv_widget_html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        html, body {{
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100vh;
            background-color: #000000;
            overflow: hidden;
        }}
        #tradingview_widget {{
            width: 100%;
            height: 100vh;
        }}
    </style>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
</head>
<body>
    <div id="tradingview_widget"></div>
    <script type="text/javascript">
        new TradingView.widget({{
            "autosize": true,
            "symbol": "{tv_symbol}",
            "interval": "{tv_interval}",
            "timezone": "Asia/Bangkok",
            "theme": "dark",
            "style": "1",
            "locale": "th",
            "toolbar_bg": "#000000",
            "enable_publishing": false,
            "hide_side_toolbar": false,
            "allow_symbol_change": true,
            "container_id": "tradingview_widget",
            "details": true,
            "hotlist": true,
            "calendar": true,
            "studies": [
                "STD;EMA"
            ],
            "overrides": {{
                "paneProperties.background": "#000000",
                "paneProperties.backgroundType": "solid"
            }}
        }});
    </script>
</body>
</html>
"""

components.html(tv_widget_html, height=580, scrolling=False)
