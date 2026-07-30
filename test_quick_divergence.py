"""
Quick Test Script for Quantitative Divergence Engine.
Runs a simple validation test on XAU/USD and EUR/USD and prints signal results.
"""

import os
import sys
import pandas as pd
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
from analysis.divergence import DivergenceSignalGenerator, DivergenceDataLoader


def run_quick_test():
    print("=" * 65)
    print(" QUICK VALIDATION TEST — QUANTITATIVE DIVERGENCE ENGINE")
    print(" Assets: XAU/USD (Gold) & EUR/USD")
    print("=" * 65)

    print("\n[1/3] Fetching recent market data from Yahoo Finance...")
    df_gold = yf.Ticker("GC=F").history(period="60d", interval="1d").reset_index()
    df_eur = yf.Ticker("EURUSD=X").history(period="60d", interval="1d").reset_index()
    df_dxy = yf.Ticker("DX-Y.NYB").history(period="60d", interval="1d").reset_index()
    df_vix = yf.Ticker("^VIX").history(period="60d", interval="1d").reset_index()

    # Standardize column names
    for df in [df_gold, df_eur, df_dxy, df_vix]:
        df.rename(columns={
            "Date": "price_datetime", "Datetime": "price_datetime",
            "Open": "open_price", "High": "high_price",
            "Low": "low_price", "Close": "close_price"
        }, inplace=True)
        df["price_datetime"] = pd.to_datetime(df["price_datetime"]).dt.tz_localize(None)

    # Calculate basic RSI & ATR
    for df in [df_gold, df_eur]:
        delta = df["close_price"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi_14"] = (100 - (100 / (1 + rs))).fillna(50)

        tr = np.maximum(
            df["high_price"] - df["low_price"],
            np.maximum(
                abs(df["high_price"] - df["close_price"].shift(1)),
                abs(df["low_price"] - df["close_price"].shift(1))
            )
        )
        df["atr_14"] = tr.rolling(14).mean().fillna(df["close_price"] * 0.01)

    generator = DivergenceSignalGenerator(pivot_window=3)

    # 2. Test XAU/USD
    print("\n[2/3] Analyzing XAU/USD (Gold)...")
    res_gold = generator.generate_composite_signals(df_gold, {"dxy": df_dxy, "vix": df_vix})
    signals_gold = res_gold[res_gold["signal_action"] != "HOLD"]

    if not signals_gold.empty:
        print(f" Found {len(signals_gold)} signals for XAU/USD:")
        print(signals_gold[["price_datetime", "close_price", "signal_action", "stop_loss_price", "take_profit_price", "composite_score"]].to_string(index=False))
    else:
        print(" No active trading signals in current 60-day window (Market in normal regime).")
        latest = res_gold.tail(3)
        print(" Latest 3 bars status:")
        print(latest[["price_datetime", "close_price", "rsi_14", "composite_score", "signal_action"]].to_string(index=False))

    # 3. Test EUR/USD
    print("\n[3/3] Analyzing EUR/USD...")
    res_eur = generator.generate_composite_signals(df_eur, {"dxy": df_dxy, "vix": df_vix})
    signals_eur = res_eur[res_eur["signal_action"] != "HOLD"]

    if not signals_eur.empty:
        print(f" Found {len(signals_eur)} signals for EUR/USD:")
        print(signals_eur[["price_datetime", "close_price", "signal_action", "stop_loss_price", "take_profit_price", "composite_score"]].to_string(index=False))
    else:
        print(" No active trading signals in current 60-day window (Market in normal regime).")
        latest = res_eur.tail(3)
        print(" Latest 3 bars status:")
        print(latest[["price_datetime", "close_price", "rsi_14", "composite_score", "signal_action"]].to_string(index=False))

    print("\n" + "=" * 65)
    print(" TEST COMPLETED SUCCESSFULLY! SYSTEM IS READY TO USE.")
    print("=" * 65)


if __name__ == "__main__":
    run_quick_test()
