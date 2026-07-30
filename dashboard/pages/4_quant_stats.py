"""
Quant Trader Dashboard — Quant Statistics & Analytics Page.
Computes and displays Volume Profile, Smart Money Concepts (SMC/FVG/BOS),
Divergence metrics, and Volatility Analytics directly from MySQL data.
"""

import os
import sys
import pymysql
import pymysql.cursors
import pandas as pd
import numpy as np
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
load_dotenv()

from analysis.volume_profile import VolumeProfileEngine
from analysis.smc_crt import SMCEngine
from analysis.divergence import DivergenceEngine
from analysis.technical_analysis import TechnicalAnalyzer

st.set_page_config(
    page_title="quant_stats",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -- Styling --

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
        padding: 2.8rem 1rem 0 1rem;
        max-width: 100%;
    }

    /* Metric cards styling */
    div[data-testid="stMetric"] {
        background: #111111;
        border: 1px solid #222222;
        border-radius: 6px;
        padding: 10px 14px;
    }

    div[data-testid="stMetric"] label {
        color: #787b86 !important;
        font-size: 12px;
    }

    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #d1d4dc;
        font-size: 20px;
        font-weight: 600;
    }

    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


st.title("Quant Statistics & Analytics Engine")
st.markdown("Detailed quantitative statistical analysis generated from MySQL data")

# -- Data Layer --

ASSETS = {
    "XAUUSD (Gold)":    {"db": "gold",   "decimals": 2},
    "EURUSD":           {"db": "eurusd", "decimals": 5},
    "DXY (Dollar)":      {"db": "dxy",    "decimals": 3},
    "US10Y (10Y Yield)":{"db": "us10y",  "decimals": 3},
    "VIX (Volatility)":  {"db": "vix",    "decimals": 2},
    "GDX (Gold Miners)":{"db": "gdx",    "decimals": 2},
}

TF_MAP = {"5m": "m5", "15m": "m15", "1h": "h1", "4h": "h4", "6h": "h6", "1D": "d1"}


@st.cache_data(ttl=30)
def load_ohlcv_data(db_name: str, table: str) -> pd.DataFrame:
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
            for col in ['open_price', 'high_price', 'low_price', 'close_price']:
                df[col] = df[col].astype(float)
            df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        st.error(f"MySQL Error: {e}")
        return pd.DataFrame()


# -- Selectors --

col1, col2, col3 = st.columns([2, 1.5, 6.5])

with col1:
    selected_asset = st.selectbox("Asset", options=list(ASSETS.keys()), index=0)

asset_cfg = ASSETS[selected_asset]
db_name = asset_cfg["db"]
decimals = asset_cfg["decimals"]

with col2:
    selected_tf = st.selectbox("Timeframe", options=list(TF_MAP.keys()), index=0)

table_name = TF_MAP[selected_tf]

st.divider()

# -- Fetch Data & Run Engines --

df = load_ohlcv_data(db_name, table_name)

if df.empty:
    st.warning(f"No data found for {selected_asset} [{selected_tf}]. Please run data sync.")
    st.stop()

# 1. Volume Profile Engine
vp_engine = VolumeProfileEngine(num_bins=40, value_area_pct=0.70)
vp_res = vp_engine.compute_profile(df)

# 2. SMC / FVG / BOS Engine
smc_engine = SMCEngine()
df_fvg = smc_engine.detect_fvg(df)
df_bos = smc_engine.detect_bos_choch(df_fvg)

bullish_fvg_count = (df_bos['fvg_type'] == 'BULLISH').sum()
bearish_fvg_count = (df_bos['fvg_type'] == 'BEARISH').sum()
bos_count = df_bos['is_bos'].sum() if 'is_bos' in df_bos.columns else 0
choch_count = df_bos['is_choch'].sum() if 'is_choch' in df_bos.columns else 0

# 3. Divergence Engine
tech_analyzer = TechnicalAnalyzer()
df_tech = df.copy()
df_tech['rsi_14'] = tech_analyzer.calculate_rsi(df_tech['close_price'], 14)

div_engine = DivergenceEngine()
df_div = div_engine.detect_rsi_divergence(df_tech)

reg_bull_div = (df_div['div_rsi_signal'] == 'REGULAR_BULLISH').sum()
reg_bear_div = (df_div['div_rsi_signal'] == 'REGULAR_BEARISH').sum()
hid_bull_div = (df_div['div_rsi_signal'] == 'HIDDEN_BULLISH').sum()
hid_bear_div = (df_div['div_rsi_signal'] == 'HIDDEN_BEARISH').sum()

# 4. Volatility & Summary Stats
latest_close = df['close_price'].iloc[-1]
price_returns = df['close_price'].pct_change().dropna()
volatility_ann = price_returns.std() * np.sqrt(252) * 100 if len(price_returns) > 5 else 0

high_low_range = df['high_price'] - df['low_price']
avg_range = high_low_range.mean()

# -- UI Layout --

st.subheader("1. Volume Profile Statistics (VPOC)")
vcol1, vcol2, vcol3, vcol4 = st.columns(4)

with vcol1:
    poc_val = f"${vp_res['poc']:.{decimals}f}" if vp_res['poc'] is not None else "N/A"
    st.metric("Point of Control (POC)", poc_val)

with vcol2:
    vah_val = f"${vp_res['vah']:.{decimals}f}" if vp_res['vah'] is not None else "N/A"
    st.metric("Value Area High (VAH)", vah_val)

with vcol3:
    val_val = f"${vp_res['val']:.{decimals}f}" if vp_res['val'] is not None else "N/A"
    st.metric("Value Area Low (VAL)", val_val)

with vcol4:
    st.metric("Value Area Coverage", "70.0%")

st.divider()

st.subheader("2. Smart Money Concepts (SMC) & Imbalance")
scol1, scol2, scol3, scol4 = st.columns(4)

with scol1:
    st.metric("Bullish FVG Zones", f"{bullish_fvg_count:,}")

with scol2:
    st.metric("Bearish FVG Zones", f"{bearish_fvg_count:,}")

with scol3:
    st.metric("Break of Structure (BOS)", f"{bos_count:,}")

with scol4:
    st.metric("Change of Character (CHoCH)", f"{choch_count:,}")

st.divider()

st.subheader("3. Divergence Signal Statistics")
dcol1, dcol2, dcol3, dcol4 = st.columns(4)

with dcol1:
    st.metric("Regular Bullish Divergence", f"{reg_bull_div:,}")

with dcol2:
    st.metric("Regular Bearish Divergence", f"{reg_bear_div:,}")

with dcol3:
    st.metric("Hidden Bullish Divergence", f"{hid_bull_div:,}")

with dcol4:
    st.metric("Hidden Bearish Divergence", f"{hid_bear_div:,}")

st.divider()

st.subheader("4. Volatility & Price Distribution")
pcol1, pcol2, pcol3, pcol4 = st.columns(4)

with pcol1:
    st.metric("Total Candles Analyzed", f"{len(df):,}")

with pcol2:
    st.metric("Average Candle Range", f"${avg_range:.{decimals}f}")

with pcol3:
    st.metric("Annualized Volatility", f"{volatility_ann:.2f}%")

with pcol4:
    max_p = df['high_price'].max()
    min_p = df['low_price'].min()
    st.metric("Historical Range (Max-Min)", f"${(max_p - min_p):.{decimals}f}")

st.divider()

# Recent FVG / Signal Table
st.subheader("Recent FVG Imbalance & Structure Signals")
fvg_recent = df_bos[df_bos['fvg_type'].notna()].tail(15).copy()
if not fvg_recent.empty:
    fvg_display = fvg_recent[['price_datetime', 'close_price', 'fvg_type', 'fvg_top', 'fvg_bottom']].copy()
    fvg_display.columns = ['Time', 'Close Price', 'FVG Type', 'FVG Top Level', 'FVG Bottom Level']
    fvg_display['Time'] = fvg_display['Time'].dt.strftime('%Y-%m-%d %H:%M')
    st.dataframe(fvg_display.sort_values('Time', ascending=False), use_container_width=True, hide_index=True)
else:
    st.info("No active FVG gaps in recent candles.")
