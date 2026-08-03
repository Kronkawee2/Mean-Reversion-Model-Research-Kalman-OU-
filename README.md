# Quant Trader โ€” Multi-Asset Quantitative Trading System

เธฃเธฐเธเธเธ”เธถเธเนเธฅเธฐเธเธฑเธ”เน€เธ•เธฃเธตเธขเธกเธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒเธชเธดเธเธ—เธฃเธฑเธเธขเนเธซเธฅเธฑเธ เธ—เธญเธเธเธณ (XAUUSD / GC=F) เนเธฅเธฐ EUR/USD (EURUSD=X) เธเธฃเนเธญเธกเธ”เนเธงเธขเธเนเธญเธกเธนเธฅเธ•เธฑเธงเนเธเธฃเธกเธซเธ เธฒเธ (DXY, US10Y, VIX, GDX) เนเธเธ Multi-Timeframe เธชเธณเธซเธฃเธฑเธเธเธฒเธฃเธเธฑเธ’เธเธฒ Quant Machine Learning, Algorithmic Trading (SMC / CRT) เนเธฅเธฐเธเธฒเธฃเธ—เธณ Backtesting

---

## Overview & System Objectives

เธฃเธฐเธเธเธชเธ–เธฒเธเธฑเธ•เธขเธเธฃเธฃเธกเธเนเธญเธกเธนเธฅเนเธเธ 3 เธเธฑเนเธ (Medallion Data Architecture: Step 1, Step 2, Step 3) เธญเธญเธเนเธเธเธชเธณเธซเธฃเธฑเธเธฃเธฐเธเธ Quantitative Trading เนเธ”เธขเธเธฃเธฐเธกเธงเธฅเธเธฅเธเนเธญเธกเธนเธฅเธเธฃเธญเธเธเธฅเธธเธก 6 เธเธฃเธญเธเน€เธงเธฅเธฒ (5m, 15m, 1h, 4h, 6h, 1d)

### Market Drivers & Inter-Market Relationships

```
                      [US Economic & Market Drivers]
                                    โ”
          โ”โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”ดโ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
          โ”                                                   โ”
  [DX-Y.NYB (DXY)]                                    [^TNX (US 10Y Yield)]
   เธ”เธฑเธเธเธตเธ”เธญเธฅเธฅเธฒเธฃเนเธชเธซเธฃเธฑเธ                                    เธเธฅเธ•เธญเธเนเธ—เธเธเธฑเธเธเธเธฑเธ•เธฃเธฃเธฑเธเธเธฒเธฅ
          โ”                                                   โ”
          โ””โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”ฌโ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
                                    โ”
                โ”โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”ดโ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
                โ”                                       โ”
         [EUR/USD (EURUSD=X)]                   [XAU/USD (GC=F)]
          เธขเธนเนเธฃเน€เธ—เธตเธขเธเธ”เธญเธฅเธฅเธฒเธฃเน                       เธ—เธญเธเธเธณเน€เธ—เธตเธขเธเธ”เธญเธฅเธฅเธฒเธฃเน
```

---

## Free Data Sources & Ingestion Breakdown

| Category | Assets / Tickers | Source | Method | Cost |
| :--- | :--- | :--- | :--- | :---: |
| Trading Assets | XAUUSD=X / GC=F, EURUSD=X | Yahoo Finance | yfinance | Free |
| US Dollar Index | DX-Y.NYB (DXY) | Yahoo Finance | yfinance | Free |
| 10Y Treasury Yield | ^TNX (US 10Y Yield) | Yahoo Finance | yfinance | Free |
| Volatility Index | ^VIX (CBOE Volatility) | Yahoo Finance | yfinance | Free |
| Gold Miners Index | GDX (VanEck Gold Miners) | Yahoo Finance | yfinance | Free |
| Institutional Position | CFTC COT Report (EUR & Step 3) | CFTC.gov | cot_reports | Free |
| Gold ETF Reserve | SPDR Gold Shares (GLD) | SPDR Official | Direct CSV | Free |

---

## Data Architecture (3-Tier Medallion System)

```
โ”โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
โ” 1. Step 1 (Raw Data) (Raw Data โ€” Immutable Storage)              โ”
โ”    - Trading Assets:                                        โ”
โ”        Step 3/   -> m5, m15, h1, h4, h6, d1                   โ”
โ”        eurusd/ -> m5, m15, h1, h4, h6, d1                   โ”
โ”    - Macro Drivers:                                         โ”
โ”        dxy/    -> h1, d1                                    โ”
โ”        us10y/  -> d1                                        โ”
โ”        vix/    -> d1                                        โ”
โ”        gdx/    -> d1                                        โ”
โ””โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”ฌโ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
                        โ”
                        โ–ผ
โ”โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
โ” 2. Step 2 (Processed) (Processed & Feature Engineering)           โ”
โ”    - Indicators: EMA 20/50/200, ATR 14, RSI 14              โ”
โ”    - SMC Engine: BOS, CHoCH, FVG, Order Blocks              โ”
โ”    - CRT Engine: Asian Range, Session Sweeps, Equilibrium   โ”
โ”    - Volume Profile: POC, VAH, VAL, HVN, LVN               โ”
โ”    - 12 Divergence Models (Inter-market & Technical)        โ”
โ”                                                             โ”
โ”    silver_gold/   -> features, smc, crt, vol_profile, divs  โ”
โ”    silver_eurusd/ -> features, smc, crt, vol_profile, divs  โ”
โ””โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”ฌโ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
                        โ”
                        โ–ผ
โ”โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
โ” 3. Step 3 (Signals) (Trading Signals & Dashboard)                 โ”
โ”    - Execution Logic: 5m/15m triggers with 1h/4h/6h/1d bias โ”
โ”    - Backtest Engine & Trade Logs                           โ”
โ”    - Interactive Web Dashboard                              โ”
โ”                                                             โ”
โ”    signals/ -> trade_signals, backtest_logs, equity_curve   โ”
โ””โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
```

---

## Quant Engines Overview

### 1. Smart Money Concepts (SMC Engine)
* Break of Structure (BOS) & Change of Character (CHoCH): เธ•เธฃเธงเธเธเธฑเธเธเธฒเธฃเธ—เธฐเธฅเธธเนเธเธฃเธเธชเธฃเนเธฒเธเธฃเธฒเธเธฒ HH, HL, LH, LL
* Order Blocks (OB): เธเนเธเธซเธฒเธเธฒเธเธฃเธฒเธเธฒเนเธ—เนเธเธเนเธญเธเธซเธเนเธฒเธเธฒเธฃเธเธขเธฒเธขเธ•เธฑเธงเนเธฃเธ (High-displacement expansion)
* Fair Value Gaps (FVG): เธ•เธฃเธงเธเธเธฑเธเนเธเธเธชเธ เธฒเธงเธฐเน€เธชเธตเธขเธชเธกเธ”เธธเธฅเธฃเธฒเธเธฒเนเธเธ 3 เนเธ—เนเธ (`High[i-2] < Low[i]`)
* Liquidity Sweeps (BSL/SSL): เธ•เธฃเธงเธเธเธฑเธเธเธฒเธฃเธเธงเธฒเธ”เธชเธ เธฒเธเธเธฅเนเธญเธเน€เธซเธเธทเธญ/เนเธ•เน Swing High/Low

### 2. Candle Range Theory (CRT Engine)
* Asian Range (Accumulation): เธเธณเธเธงเธ“เธเธฃเธญเธเธฃเธฒเธเธฒเธชเธนเธเธชเธธเธ”-เธ•เนเธณเธชเธธเธ”เธเนเธงเธเธ•เธฅเธฒเธ”เน€เธญเน€เธเธตเธข (00:00-06:00 UTC)
* Session Sweep (Manipulation): เธ•เธฃเธงเธเธเธฑเธเธเธฒเธฃเธเธงเธฒเธ”เธเธฃเธญเธเธฃเธฒเธเธฒเน€เธญเน€เธเธตเธขเธเนเธงเธเธ•เธฅเธฒเธ”เธฅเธญเธเธ”เธญเธ/เธเธดเธงเธขเธญเธฃเนเธ
* Range Equilibrium: เธเธณเธเธงเธ“เธเธธเธ”เธชเธกเธ”เธธเธฅ 50% เธเธญเธเธเธฃเธญเธเธฃเธฒเธเธฒเนเธ—เนเธ HTF (4h, 6h, 1d)

### 3. Volume Profile Engine
* Point of Control (POC): เธฃเธฐเธ”เธฑเธเธฃเธฒเธเธฒเธ—เธตเนเธกเธตเธงเธญเธฅเธฅเธธเนเธกเธเธฒเธฃเธเธทเนเธญเธเธฒเธขเธชเธฐเธชเธกเธชเธนเธเธชเธธเธ”
* Value Area High (VAH) & Low (VAL): เธเธญเธเน€เธเธ•เธเธทเนเธเธ—เธตเนเธงเธญเธฅเธฅเธธเนเธก 70%
* High / Low Volume Nodes (HVN / LVN): เนเธเธเธฃเธฑเธเนเธเธงเธ•เนเธฒเธเนเธเธฃเธเธชเธฃเนเธฒเธเธงเธญเธฅเธฅเธธเนเธก เนเธฅเธฐเนเธเธเธฃเธฒเธเธฒเธเธธเนเธเน€เธฃเนเธง

### 5. Technical Analysis Core Stack
* **Trend**: EMA (20, 50, 200) + ADX (14) โ€” Trend Bias Classification (STRONG_UPTREND / UPTREND / SIDEWAYS / DOWNTREND / STRONG_DOWNTREND)
* **Momentum**: RSI (14) Wilder's formula + MACD (12, 26, 9) โ€” Momentum Signal (OVERBOUGHT / OVERSOLD / BULLISH / BEARISH)
* **Volatility**: ATR (14) for position sizing + Bollinger Bands (20, 2) โ€” Vol Regime (SQUEEZE / LOW / NORMAL / HIGH)
* **Volume**: Session VWAP + OBV โ€” Volume Confirmation Signal (CONFIRM_BUY / CONFIRM_SELL / NEUTRAL)
* **Support/Resistance**: Fibonacci Retracement (23.6%, 38.2%, 50%, 61.8%, 78.6%) + Swing S/R Zone Detection

---

## Systematic Quantitative Divergence Engine (เธงเธดเธเธตเธเธฒเธฃเธเธณเธเธงเธ“ เธฅเธญเธเธดเธเธเธฒเธฃเนเธซเนเธเธฐเนเธเธ เนเธฅเธฐเนเธซเธฅเนเธเธญเนเธฒเธเธญเธดเธเธ—เธฒเธเธเธฒเธฃ)

เธฃเธฐเธเธ Divergence Engine เนเธเนเธเธฅเน€เธ”เธญเธฃเน `analysis/divergence/` เธ–เธนเธเธญเธญเธเนเธเธเธเธถเนเธเธ•เธฒเธกเธซเธฅเธฑเธเธเธฒเธฃ **Quantitative Multi-Factor Model** เธชเธณเธซเธฃเธฑเธเธชเธดเธเธ—เธฃเธฑเธเธขเน **XAU/USD** เนเธฅเธฐ **EUR/USD** เนเธ”เธขเธญเนเธฒเธเธญเธดเธเธเธฒเธเธ—เธคเธฉเธเธตเธเธฒเธฃเน€เธเธดเธเนเธฅเธฐเนเธซเธฅเนเธเธเนเธญเธกเธนเธฅเธ—เธฒเธเธเธฒเธฃ

### 1. เนเธเธฃเธเธชเธฃเนเธฒเธเธเธฒเธฃเธ—เธณเธเธฒเธ 5 เธเธฑเนเธเธ•เธญเธ (5-Step Pipeline Architecture)

```
โ”โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
โ” 1. Data Collection  โ”€โ”€>  เธ”เธถเธเธฃเธฒเธเธฒ Step 3/EURUSD + DXY + VIX + COT Report  โ”
โ””โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”ฌโ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
                                    โ”
                                    โ–ผ
โ”โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
โ” 2. Feature Engine   โ”€โ”€>  เธเธณเธเธงเธ“ Z-Score, Rolling Beta & Linear Slope    โ”
โ””โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”ฌโ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
                                    โ”
                                    โ–ผ
โ”โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
โ” 3. Detector Engine  โ”€โ”€>  เธ•เธฃเธงเธเธเธฑเธ Technical + Macro + COT Divergence   โ”
โ””โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”ฌโ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
                                    โ”
                                    โ–ผ
โ”โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
โ” 4. Confirmation     โ”€โ”€>  เน€เธเนเธ VIX Risk + Correlation Stability Filter  โ”
โ””โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”ฌโ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
                                    โ”
                                    โ–ผ
โ”โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
โ” 5. Signal Generator โ”€โ”€>  เธญเธญเธเธเธณเธชเธฑเนเธ BUY/SELL + เธเธณเธเธงเธ“ ATR Stop-Loss / TP  โ”
โ””โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”€โ”
```

---

### 2. เธงเธดเธเธตเธเธฒเธฃเนเธฅเธฐเธฅเธญเธเธดเธเธเธฒเธฃเธ–เนเธงเธเธเนเธณเธซเธเธฑเธเธเธฐเนเธเธ (Multi-Factor Scoring Methodology)

เธฃเธฐเธเธเนเธเนเธเธฒเธฃเธเธฃเธฐเธกเธงเธฅเธเธฅเธเธฐเนเธเธเธฃเธงเธก **Composite Score (-100 เธ–เธถเธ +100)** เน€เธเธทเนเธญเธเธฒเธฃเธฑเธเธ•เธตเธงเนเธฒเธเธฐเธญเธญเธเธญเธญเน€เธ”เธญเธฃเนเน€เธกเธทเนเธญเน€เธเธดเธ”เธเธฒเธฃเธขเธทเธเธขเธฑเธเธฃเนเธงเธกเธเธฑเธเธซเธฅเธฒเธขเธเธฑเธเธเธฑเธข (Multi-factor Confluence) เน€เธ—เนเธฒเธเธฑเนเธ:

| เธเธฃเธฐเน€เธ เธ—เธเธฑเธเธเธฑเธข (Factor Category) | เธชเธฑเธเธเธฒเธ“ (Signal Type) | เธเธฐเนเธเธ (Score Weight) | เน€เธซเธ•เธธเธเธฅเธ—เธฒเธเธชเธ–เธดเธ•เธดเนเธฅเธฐเธเธฒเธฃเน€เธเธดเธ |
| :--- | :--- | :---: | :--- |
| **Inter-Market Macro Driver** | DXY / Bond Yield Divergence | **+50 / -50** | **เธเธฑเธเธเธฑเธขเธกเธซเธ เธฒเธเธเธตเนเธเธฒเธ” (Fundamental Market Driver)** เน€เธเธดเธเธ—เธธเธเน€เธเธฅเธทเนเธญเธเธขเนเธฒเธขเธ•เธฒเธกเธ”เธญเธฅเธฅเธฒเธฃเนเนเธฅเธฐเธ”เธญเธเน€เธเธตเนเธข |
| **Technical Divergence (Reversal)** | RSI Regular Bullish / Bearish | **+40 / -40** | เน€เธเธดเธ”เธ•เธฃเธเธเธธเธ”เธชเธดเนเธเธชเธธเธ”เน€เธ—เธฃเธเธ”เน (Extrema) เธกเธตเธเธฑเธขเธชเธณเธเธฑเธเธ—เธฒเธเธชเธ–เธดเธ•เธดเธชเธนเธเนเธเธเธฒเธฃเธเธฑเธเธเธธเธ”เธเธฅเธฑเธเธ•เธฑเธงเนเธซเธเน |
| **Technical Divergence (Continuation)** | RSI Hidden Bullish / Bearish | **+25 / -25** | เธชเธฑเธเธเธฒเธ“เธขเนเธญเธขเธขเธทเธเธขเธฑเธเธเธฒเธฃเนเธเธ•เนเธญเธ•เธฒเธกเน€เธ—เธฃเธเธ”เนเน€เธ”เธดเธก |
| **Volatility Risk Adjustment** | High Volatility Regime ($VIX > 25.0$) | **เธเธฐเนเธเธเนเธ”เธเธซเธฒเธฃ 2 (-50%)** | เธเนเธญเธเธเธฑเธเธชเธฑเธเธเธฒเธ“เธซเธฅเธญเธเนเธเธเนเธงเธเธชเธ เธฒเธงเธฐเธ•เธฅเธฒเธ”เธงเธดเธเธคเธ•เธเธฑเธเธเธงเธเธชเธนเธ |

#### ๐ฏ เน€เธเธ“เธ‘เนเธเธฒเธฃเธญเธญเธเธเธณเธชเธฑเนเธเน€เธ—เธฃเธ” (Trade Execution Threshhold Logic):
* **เธเธฐเนเธเธ $\ge +50$**: เธชเธฑเนเธ **`BUY`** (เธ•เนเธญเธเธกเธต Macro Driver เธซเธฃเธทเธญ Technical Reversal + Continuation เธฃเนเธงเธกเธเธฑเธ)
* **เธเธฐเนเธเธ $\le -50$**: เธชเธฑเนเธ **`SELL`**
* **เธเธฐเนเธเธเธฃเธฐเธซเธงเนเธฒเธ $-49$ เธ–เธถเธ $+49$**: เธชเธฑเนเธ **`HOLD`** (เธ–เธทเธญเธฃเธญ เนเธกเนเน€เธเธดเธ”เธญเธญเน€เธ”เธญเธฃเนเน€เธกเธทเนเธญเน€เธซเนเธเธชเธฑเธเธเธฒเธ“เธญเธดเธเธ”เธดเน€เธเน€เธ•เธญเธฃเนเธ•เธฑเธงเน€เธ”เธตเธขเธง)

---

### 3. เธฃเธฐเธเธเธเธฃเธดเธซเธฒเธฃเธเธฑเธ”เธเธฒเธฃเธเธงเธฒเธกเน€เธชเธตเนเธขเธ (ATR Dynamic Risk Management)

เธฃเธฐเธเธเธเธณเธเธงเธ“เธเธธเธ”เธ•เธฑเธ”เธเธฒเธ”เธ—เธธเธ (Stop Loss) เนเธฅเธฐเธเธธเธ”เธ—เธณเธเธณเนเธฃ (Take Profit) เธ•เธฒเธกเธเธงเธฒเธกเธเธฑเธเธเธงเธเธเธฃเธดเธเธเธญเธเธฃเธฒเธเธฒ (J. Welles Wilder's ATR Framework):
* **Long Stop Loss (SL)**: $\text{Entry Price} - (1.5 \times \text{ATR}_{14})$
* **Long Take Profit (TP)**: $\text{Entry Price} + (3.0 \times \text{ATR}_{14})$ *(เธเธฒเธฃเธฑเธเธ•เธต Risk:Reward Ratio เธ—เธตเน 1:2)*
* **Short Stop Loss (SL)**: $\text{Entry Price} + (1.5 \times \text{ATR}_{14})$
* **Short Take Profit (TP)**: $\text{Entry Price} - (3.0 \times \text{ATR}_{14})$ *(เธเธฒเธฃเธฑเธเธ•เธต Risk:Reward Ratio เธ—เธตเน 1:2)*

---

## Systematic Quantitative Feature Engineering Architecture (7 Categories & Python Pipeline)

เธฃเธฐเธเธ Feature Engineering เนเธเธเธเธฃเธเธงเธเธเธฃเนเธเนเธเธฅเน€เธ”เธญเธฃเน `analysis/features/` เธ–เธนเธเธญเธญเธเนเธเธเธกเธฒเธชเธณเธซเธฃเธฑเธ **XAU/USD** เนเธฅเธฐ **EUR/USD** เน€เธเธทเนเธญเธชเธฃเนเธฒเธเธเธตเน€เธเธญเธฃเนเธ—เธตเนเธเธดเนเธ (Stationary) เธเธฃเธฒเธจเธเธฒเธ Look-ahead Bias เธชเธณเธซเธฃเธฑเธเธฃเธฐเธเธ Quantitative Trading

### 1. เธซเธกเธงเธ”เธซเธกเธนเนเธเธตเน€เธเธญเธฃเนเธ—เธฑเนเธ 7 (7 Feature Categories)

| เธซเธกเธงเธ”เธซเธกเธนเน (Category) | เธเธทเนเธญเธเธตเน€เธเธญเธฃเน (Feature Name) | เธชเธนเธ•เธฃเธเธณเธเธงเธ“ (Mathematical Formula) | Inputs | Asset | เน€เธซเธ•เธธเธเธฅเน€เธเธดเธเธเธฒเธฃเน€เธเธดเธเนเธฅเธฐเธเนเธญเธเธงเธฃเธฃเธฐเธงเธฑเธ |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **Price / Return** | `feat_log_return` | $r_t = \ln(P_t / P_{t-1})$ | Close Price | เธ—เธฑเนเธเธเธนเน | เนเธเธฅเธเธฃเธฒเธเธฒเนเธซเนเธเธฅเธฒเธขเน€เธเนเธ Stationary Series เธฅเธ”เธเธฑเธเธซเธฒ Non-Stationarity |
| **Price / Return** | `feat_price_ema_dist_z` | $\frac{P_t - \text{EMA}_{20}(P)}{\sigma_{60}(P)}$ | Close, EMA | เธ—เธฑเนเธเธเธนเน | เธงเธฑเธ”เธฃเธฐเธขเธฐเธซเนเธฒเธเธเธฒเธเนเธเธงเนเธเนเธกเธซเธฅเธฑเธ เน€เธเธทเนเธญเธชเนเธเธชเธฑเธเธเธฒเธ“ Mean-Reversion |
| **Price / Return** | `feat_log_return_slope` | $\text{OLS Slope}_5(r_t)$ | Log Return | เธ—เธฑเนเธเธเธนเน | เธงเธฑเธ”เธเธงเธฒเธกเน€เธฃเนเธเธเธญเธเนเธกเน€เธกเธเธ•เธฑเธกเธฃเธฒเธเธฒ (Momentum Acceleration) |
| **Volatility** | `feat_garman_klass_vol` | $\sqrt{\frac{0.5(\ln(H/L))^2 - (2\ln 2 - 1)(\ln(C/O))^2}{N}}$ | OHLC | เธ—เธฑเนเธเธเธนเน | เนเธกเนเธเธขเธณเธเธงเนเธฒ Close-to-Close Volatility 8 เน€เธ—เนเธฒ เธเธฑเธเธชเธ เธฒเธงเธฐ Volatility Regime |
| **Volatility** | `feat_parkinson_vol` | $\sqrt{\frac{(\ln(H/L))^2}{4 \ln 2 \cdot N}}$ | High, Low | เธ—เธฑเนเธเธเธนเน | เธงเธฑเธ”เธเธงเธฒเธกเธเธฑเธเธเธงเธเธเธฒเธ High-Low Range |
| **Volatility** | `feat_atr_pct` | $\frac{\text{ATR}_{14}}{P_{\text{Close}}} \times 100$ | OHLC | เธ—เธฑเนเธเธเธนเน | Normalized ATR % เธชเธณเธซเธฃเธฑเธเน€เธเธฃเธตเธขเธเน€เธ—เธตเธขเธเธเธงเธฒเธกเธเธฑเธเธเธงเธเธเนเธฒเธกเธเนเธงเธเธฃเธฒเธเธฒ |
| **Volatility** | `feat_volatility_ratio` | $\frac{\sigma_{10}(r)}{\sigma_{60}(r)}$ | Log Return | เธ—เธฑเนเธเธเธนเน | เธงเธฑเธ”เธเธฒเธฃเธเธตเธเธ•เธฑเธง (Compression < 0.7) เธซเธฃเธทเธญเธฃเธฐเน€เธเธดเธ”เธ•เธฑเธง (Expansion > 1.3) เธเธญเธเธเธงเธฒเธกเธเธฑเธเธเธงเธ |
| **Correlation/Spread**| `feat_dxy_spread_z` | $\frac{(P_{\text{Asset}} - \beta \cdot P_{\text{DXY}}) - \mu_N}{\sigma_N}$ | Asset, DXY | เธ—เธฑเนเธเธเธนเน | Cointegration Residual Spread เน€เธ—เธฃเธ” Mean-Reversion เน€เธกเธทเนเธญเธฃเธฒเธเธฒเธซเธฅเธธเธ”เธเธฒเธเธ”เธญเธฅเธฅเธฒเธฃเน |
| **Correlation/Spread**| `feat_gsr_zscore` | $\frac{(P_{\text{Step 3}} / P_{\text{Step 2}}) - \mu_N}{\sigma_N}$ | Step 3, Step 2 | Step 3 Only | Step 3-Step 2 Ratio Mispricing เธชเธฑเธเธเธฒเธ“ Relative Value เธชเธณเธซเธฃเธฑเธเธ—เธญเธเธเธณ |
| **Macro** | `feat_dxy_return_z` | $\frac{r_{\text{DXY}} - \mu_N(r_{\text{DXY}})}{\sigma_N}$ | DXY Close | เธ—เธฑเนเธเธเธนเน | เนเธกเน€เธกเธเธ•เธฑเธกเธเธญเธเธ”เธญเธฅเธฅเธฒเธฃเนเธชเธซเธฃเธฑเธเธ—เธตเนเน€เธเนเธเธ•เธฑเธงเธเธฑเธเน€เธเธฅเธทเนเธญเธเธซเธฅเธฑเธ |
| **Macro** | `feat_real_yield_proxy` | $r_{\text{US10Y}} - r_{\text{DXY}}$ | US10Y, DXY | เธ—เธฑเนเธเธเธนเน | เธเธฅเธ•เธญเธเนเธ—เธเธ—เธตเนเนเธ—เนเธเธฃเธดเธ (Real Rate Delta) เธชเนเธเธเธฅเนเธ”เธขเธ•เธฃเธเธ•เนเธญเธ—เธญเธเธเธณ |
| **Macro** | `feat_gdx_gold_residual`| $r_{\text{Step 3}} - \beta \cdot r_{\text{GDX}}$ | Step 3, GDX | Step 3 Only | เธซเธธเนเธเน€เธซเธกเธทเธญเธเธ—เธญเธเธเธณ (GDX) เน€เธเนเธเธ•เธฑเธงเธเธณเธฃเธฒเธเธฒเธ—เธญเธเธเธณเนเธ—เนเธ (Leading Indicator) |
| **Positioning** | `feat_cot_percentile` | $\frac{\text{CommNet}_t - \min_{52w}}{\max_{52w} - \min_{52w}} \times 100$ | CFTC COT | เธ—เธฑเนเธเธเธนเน | % Extreme เธเธญเธเธเธฑเธเธฅเธเธ—เธธเธเธชเธ–เธฒเธเธฑเธเธฃเธฒเธขเนเธซเธเน (Commercial Hedgers) เธฃเธญเธ 52 เธชเธฑเธเธ”เธฒเธซเน |
| **Positioning** | `feat_cot_zscore` | $\frac{\text{CommNet}_t - \mu_{52w}}{\sigma_{52w}}$ | CFTC COT | เธ—เธฑเนเธเธเธนเน | Standardized Position Factor เธชเธณเธซเธฃเธฑเธเธชเธ–เธฒเธเธฑเธเธฃเธฒเธขเนเธซเธเน |
| **Positioning** | `feat_cot_delta_4w` | $\text{CommNet}_t - \text{CommNet}_{t-4}$ | CFTC COT | เธ—เธฑเนเธเธเธนเน | เธงเธฑเธ”เธญเธฑเธ•เธฃเธฒเธเธฒเธฃเธชเธฐเธชเธก/เธเธฃเธฐเธเธฒเธขเธชเธฑเธเธเธฒเธเธญเธเธชเธ–เธฒเธเธฑเธเธฃเธฒเธขเนเธซเธเนเธฃเธญเธ 4 เธชเธฑเธเธ”เธฒเธซเน |
| **Filter** | `feat_vix_regime_flag` | $I(\text{VIX}_t > 25.0)$ | VIX Close | เธ—เธฑเนเธเธเธนเน | Binary Flag เธชเธ เธฒเธงเธฐเธงเธดเธเธคเธ• (VIX > 25) เธชเธณเธซเธฃเธฑเธเธฅเธ”เธเธฒเธฃเธ–เธทเธญเธเธฃเธญเธ Leverage |

---

### 2. เนเธเธฃเธเธชเธฃเนเธฒเธเนเธเนเธเน€เธเธ Python Feature Spec (`analysis/features/`)

```
analysis/features/
โ”โ”€โ”€ __init__.py                # Master package entry point & re-exports
โ”โ”€โ”€ price_return.py            # PriceReturnFeatures (Log return, EMA dist z, Slope)
โ”โ”€โ”€ volatility.py              # VolatilityFeatures (Garman-Klass, Parkinson, ATR %, Vol ratio)
โ”โ”€โ”€ correlation_beta.py        # CorrelationBetaFeatures (Beta, Cointegration spread z, GSR z)
โ”โ”€โ”€ macro.py                   # MacroFeatures (DXY z, Real yield proxy, GDX residual, VIX flag)
โ”โ”€โ”€ positioning.py             # PositioningFeatures (COT percentile, COT z-score, COT 4w delta)
โ””โ”€โ”€ pipeline.py                # QuantFeaturePipeline (Master Data Transformer & Quant Score)
```

---

### 3. เธ•เธฑเธงเธญเธขเนเธฒเธเธเธฒเธฃเนเธเนเธเธฒเธเนเธ Python Pipeline

```python
from analysis.features import QuantFeaturePipeline, PriceReturnFeatures, VolatilityFeatures

# เธชเธฃเนเธฒเธ Feature Pipeline เธชเธณเธซเธฃเธฑเธ XAU/USD (Step 3)
pipeline = QuantFeaturePipeline(asset_name="Step 3")

# เธฃเธฑเธเธเธฃเธฐเธกเธงเธฅเธเธฅเนเธเธฅเธ Raw Data -> Features -> Composite Quant Score
df_features = pipeline.transform(
    df_asset=df_gold,
    df_drivers={"dxy": df_dxy, "us10y": df_us10y, "vix": df_vix, "gdx": df_gdx, "Step 2": df_silver},
    df_cot=df_cot_gold
)
```

---

---

## Quantitative Smart Money Concepts (SMC) & Candle Range Theory (CRT) Architecture

เธฃเธฐเธเธ SMC & CRT Engine เนเธเธเน€เธเนเธเธฃเธฐเธเธเนเธเนเธเธฅเน€เธ”เธญเธฃเน `analysis/smc_crt/` เธ–เธนเธเธญเธญเธเนเธเธเธกเธฒเธชเธณเธซเธฃเธฑเธ **XAU/USD** เนเธฅเธฐ **EUR/USD** เนเธ”เธขเน€เธเธฅเธตเนเธขเธเธกเนเธเธ—เธฑเธจเธเนเน€เธเธดเธเธเธธเธ“เธ เธฒเธเนเธซเนเธเธฅเธฒเธขเน€เธเนเธเธชเธนเธ•เธฃเธเธ“เธดเธ•เธจเธฒเธชเธ•เธฃเนเนเธฅเธฐเธเธเนเธเธฃเนเธเธฃเธกเนเธฃเน Look-ahead bias

### 1. เธ•เธฒเธฃเธฒเธเธเธธเธ“เธฅเธฑเธเธฉเธ“เธฐ SMC / CRT (Feature & Detection Matrix)

| เธซเธกเธงเธ”เธซเธกเธนเน (Category) | เธเธทเนเธญเธเธตเน€เธเธญเธฃเน (Feature Name) | เธชเธนเธ•เธฃ/เธเธดเธขเธฒเธกเธ—เธฒเธเธเธ“เธดเธ•เธจเธฒเธชเธ•เธฃเน (Rule Definition) | Inputs | เธเธฒเธฃเธ•เธตเธเธงเธฒเธกเนเธฅเธฐเธเธฒเธฃเธเธณเนเธเนเธเน |
| :--- | :--- | :--- | :--- | :--- |
| **Structure** | `smc_structure_signal` | $\text{Bullish BOS} \iff C_t > \text{SwingHigh}_{\text{prev}}$ in Uptrend | OHLC | เธขเธทเธเธขเธฑเธเธเธฒเธฃเนเธเธ•เนเธญเธเธญเธเน€เธ—เธฃเธเธ”เนเนเธซเธเน (Trend Continuation) |
| **Structure** | `smc_choch` | $\text{Bullish CHoCH} \iff C_t > \text{SwingHigh}_{\text{prev}}$ in Downtrend | OHLC | เธขเธทเธเธขเธฑเธเธเธธเธ”เธเธฅเธฑเธเธ•เธฑเธงเธ•เนเธเน€เธ—เธฃเธเธ”เน (Trend Reversal) |
| **Liquidity** | `smc_liquidity_sweep`| $\text{BSL Sweep} \iff H_t > \text{SwingHigh} \land C_t \le \text{SwingHigh}$ | OHLC | เธฅเนเธฒเธชเธ เธฒเธเธเธฅเนเธญเธ (Stop Hunt / Liquidity Sweep) เน€เธ•เธฃเธตเธขเธกเธเธฅเธฑเธเธ•เธฑเธง |
| **Liquidity** | `smc_eqh_eql` | $\|H_1 - H_2\| / P \le 0.0005$ | High, Low | เธชเธฃเธฐเธชเธ เธฒเธเธเธฅเนเธญเธ (Equal Highs/Lows) เน€เธเนเธฒเธซเธกเธฒเธขเธเธญเธเธฃเธฒเธเธฒ |
| **Imbalance** | `smc_fvg_type` | $\text{Bullish FVG} \iff H_{t-2} < L_t \land (L_t - H_{t-2}) > \theta$ | High, Low | เธเนเธญเธเธงเนเธฒเธเธชเธ เธฒเธงเธฐเน€เธชเธตเธขเธชเธกเธ”เธธเธฅเธฃเธฒเธเธฒ เนเธเธเธฃเธญเธฃเธฑเธเน€เธกเธทเนเธญเธฃเธฒเธเธฒเธขเนเธญเธเธเธฅเธฑเธ |
| **Order Flow** | `smc_ob_type` | $\text{Bullish OB} \iff \text{Last Bearish Candle before BOS}$ | OHLC, Vol | เธเธฒเธเธฃเธฒเธเธฒเธญเธญเน€เธ”เธญเธฃเนเธฃเธฒเธขเนเธซเธเน (Order Block) เนเธเธเน€เธเนเธฒเธญเธญเน€เธ”เธญเธฃเน |
| **CRT Framework** | `crt_session_sweep` | $\text{Sweep of Asian Range High/Low in London/NY}$ | OHLC, Time | Candle Range Theory: เธเธฒเธฃเธเธงเธฒเธ”เธเธฃเธญเธเธฃเธฒเธเธฒเน€เธญเน€เธเธตเธข (00:00-06:00) |
| **Equilibrium** | `smc_zone` | $\text{Discount} \iff P_t < 0.5(H_{\text{HTF}} + L_{\text{HTF}})$ | High, Low | Buy เน€เธเธเธฒเธฐเนเธเนเธเธ Discount ($< 50\%$), Sell เนเธเนเธเธ Premium ($> 50\%$) |

---

### 2. เนเธเธฃเธเธชเธฃเนเธฒเธเนเธเนเธเน€เธเธ Python SMC/CRT (`analysis/smc_crt/`)

```
analysis/smc_crt/
โ”โ”€โ”€ __init__.py                # Package facade & re-exports
โ”โ”€โ”€ structure.py               # SMCStructureEngine (Swing High/Low, BOS, CHoCH)
โ”โ”€โ”€ liquidity.py               # SMCLiquidityEngine (EQH/EQL, BSL/SSL Liquidity Sweeps)
โ”โ”€โ”€ imbalance.py               # SMCImbalanceEngine (FVG, Liquidity Voids, Active Mitigation)
โ”โ”€โ”€ order_block.py             # SMCOrderBlockEngine (Bullish/Bearish Order Blocks)
โ”โ”€โ”€ crt_engine.py              # CRTEngine (Asian Range 00:00-06:00, Session Sweeps, 50% Median)
โ””โ”€โ”€ scoring.py                 # SMCScoringEngine (Composite Score -100 to +100 & Strategy Blueprint)
```

---

### 3. เธ•เธฑเธงเธญเธขเนเธฒเธเธเธฒเธฃเนเธเนเธเธฒเธ SMC/CRT Strategy Blueprint

```python
from analysis.smc_crt import SMCScoringEngine

# เธชเธฃเนเธฒเธ SMC/CRT Engine
smc_engine = SMCScoringEngine(pivot_window=3)

# เธฃเธฑเธเธเธฃเธฐเธกเธงเธฅเธเธฅเธขเนเธญเธเธซเธฅเธฑเธเธเธ XAU/USD เธซเธฃเธทเธญ EUR/USD
df_smc = smc_engine.generate_strategy_blueprint(
    df_asset=df_gold,
    df_drivers={"dxy": df_dxy, "vix": df_vix}
)
```

---

### 4. เนเธซเธฅเนเธเธเนเธญเธกเธนเธฅเธ—เธฒเธเธเธฒเธฃเนเธฅเธฐเน€เธญเธเธชเธฒเธฃเธญเนเธฒเธเธญเธดเธ (Official References & Citations)

1. **GitHub open-source `smart-money-concepts`** (Josh Yattridge)
   - https://github.com/joshyattridge/smart-money-concepts
2. **Equiti News & Trading Ideas** โ€” *What is the Smart Money Concept (SMC) in Forex?*
   - https://www.equiti.com/sc-en/news/trading-ideas/what-is-the-smart-money-concept-smc-in-forex-and-how-can-you-use-it/
3. **Trade The Pool** โ€” *Smart Money Concepts Terminology Guide*
   - https://tradethepool.com/technical-skill/smart-money-concepts-terminology/
4. **DYOR Academy** โ€” *SMC Price Action, Order Blocks, Liquidity & FVG Reference*
   - https://dyor.net/academy/en/price_action/smart-money-concepts
5. **ACY Securities** โ€” *Confirmation Model: OB + FVG + Liquidity Sweep*
   - https://acy.com/en/market-news/education/confirmation-model-ob-fvg-liquidity-sweep-j-o-20251112-094218/
6. **Scribd Guide** โ€” *SMC OrderBlock Strategy Guide*
   - https://www.scribd.com/document/869902609/SMC-OrderBlock-Strategy-Guide
7. **CFTC (U.S. Commodity Futures Trading Commission)** โ€” *Commitment of Traders (COT) Reports*
   - https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
8. **CME Group** โ€” *FX & Precious Metals Session Trading Hours Specifications*
   - https://www.cmegroup.com/market-data/real-time-and-historical-data.html

---

## Quantitative Volume Profile Engine & Profile Shape Classifier Architecture (P-shape, b-shape, D-shape)

เธฃเธฐเธเธ Volume Profile Engine เนเธเธเน€เธเนเธเธฃเธฐเธเธเนเธเนเธเธฅเน€เธ”เธญเธฃเน `analysis/volume_profile/` เธ–เธนเธเธญเธญเธเนเธเธเธกเธฒเธชเธณเธซเธฃเธฑเธ **XAU/USD** เนเธฅเธฐ **EUR/USD** เน€เธเธทเนเธญเธเธณเธเธงเธ“ Volume-at-Price Histogram, เธชเธ–เธดเธ•เธดเน€เธเธดเธเธฃเธนเธเธ—เธฃเธ (Skewness, Kurtosis, Concentration Ratio), เนเธฅเธฐเธเธณเนเธเธเธเธฃเธฐเน€เธ เธ— Profile Shape (P-shape, b-shape, D-shape)

> [!NOTE]
> **เธเนเธญเนเธ•เธเธ•เนเธฒเธเธซเธฅเธฑเธเธฃเธฐเธซเธงเนเธฒเธ Volume Profile เธเธฑเธ Market Profile**:
> - **Volume Profile (เธ—เธตเนเนเธเนเนเธเธฃเธฐเธเธเธเธตเน)**: เธงเธฑเธ”เธเธฃเธดเธกเธฒเธ“เธเธฒเธฃเธเธทเนเธญเธเธฒเธขเธ•เธฒเธกเธฃเธฐเธ”เธฑเธเธฃเธฒเธเธฒ (**Volume-at-Price**)
> - **Market Profile (TPO)**: เธงเธฑเธ”เธฃเธฐเธขเธฐเน€เธงเธฅเธฒเธ—เธตเนเธฃเธฒเธเธฒเนเธเนเธญเธขเธนเนเธ•เธฒเธกเธฃเธฐเธ”เธฑเธเธฃเธฒเธเธฒ (**Time-at-Price**)

### 1. เธ•เธฒเธฃเธฒเธเธเธณเนเธเธเธเธฃเธฐเน€เธ เธ—เธฃเธนเธเธ—เธฃเธ Volume Profile (Profile Shape Classification Matrix)

| เธฃเธนเธเธ—เธฃเธ Profile (Profile Shape) | เธเธดเธขเธฒเธกเน€เธเธดเธเธชเธ–เธดเธ•เธด (Statistical Condition) | เธ•เธณเนเธซเธเนเธ POC & Value Area | เธชเธ เธฒเธเนเธงเธ”เธฅเนเธญเธกเธ•เธฅเธฒเธ” (Market Regime) | เธเธฅเธขเธธเธ—เธเนเธเธฒเธฃเน€เธ—เธฃเธ” (Trading Implications) |
| :--- | :--- | :--- | :--- | :--- |
| **D-shape** | $\text{POC}_{\text{norm}} \in [0.40, 0.60] \land \|\gamma_1\| \le 0.5$ | POC เธญเธขเธนเนเธ•เธฃเธเธเธฅเธฒเธเธชเธกเธกเธฒเธ•เธฃ | Fair Value / Equilibrium; เนเธฃเธเธเธทเนเธญเนเธฃเธเธเธฒเธขเธชเธกเธ”เธธเธฅ | Range Trading (Buy VAL, Sell VAH, Target POC) |
| **P-shape** | $\text{POC}_{\text{norm}} \ge 0.65 \land \text{TopBotRatio} \ge 1.4$ | POC เธญเธขเธนเนเนเธเธเธเธ (เนเธเธฅเน VAH) | Bullish Short-Covering / Upward Expansion | Bullish Trend Continuation (Buy on Retest POC) |
| **b-shape** | $\text{POC}_{\text{norm}} \le 0.35 \land \text{TopBotRatio} \le 0.70$ | POC เธญเธขเธนเนเนเธเธเธฅเนเธฒเธ (เนเธเธฅเน VAL) | Bearish Long-Liquidation / Downward Expansion | Bearish Trend Continuation (Sell on Retest POC) |

---

### 2. เนเธเธฃเธเธชเธฃเนเธฒเธเนเธเนเธเน€เธเธ Python Volume Profile (`analysis/volume_profile/`)

```
analysis/volume_profile/
โ”โ”€โ”€ __init__.py                # Package facade & re-exports
โ”โ”€โ”€ calculator.py              # Volume-at-Price Histogram (50 Bins), POC, Value Area (70%), HVN & LVN
โ”โ”€โ”€ statistical_features.py    # Skewness, Kurtosis, Concentration Ratio, Top/Bottom Ratio, POC Loc
โ”โ”€โ”€ classifier.py              # Profile Shape Classifier (detect_p_shape, detect_b_shape, detect_d_shape)
โ”โ”€โ”€ signals.py                 # Rule-based Trading Signals (Trend Continuation, Reversal, Range)
โ””โ”€โ”€ pipeline.py                # VolumeProfilePipeline (Master Data Transformer)
```

---

### 3. เธ•เธฑเธงเธญเธขเนเธฒเธเธเธฒเธฃเนเธเนเธเธฒเธ Volume Profile Pipeline

```python
from analysis.volume_profile import VolumeProfilePipeline

# 1. เธชเธฃเนเธฒเธ Volume Profile Pipeline
pipeline = VolumeProfilePipeline(num_bins=50, value_area_pct=0.70)

# 2. เธฃเธฑเธเธเธณเธเธงเธ“เนเธฅเธฐเธเธณเนเธเธ Profile Shape เธเธ XAU/USD เธซเธฃเธทเธญ EUR/USD
out = pipeline.process(df_gold)
print("Profile Shape:", out["shape_label"])
print("POC:", out["poc"], "VAH:", out["vah"], "VAL:", out["val"])
print("Action:", out["action"], "Reason:", out["reason"])
```

---

### 4. เนเธซเธฅเนเธเธเนเธญเธกเธนเธฅเธ—เธฒเธเธเธฒเธฃเนเธฅเธฐเน€เธญเธเธชเธฒเธฃเธญเนเธฒเธเธญเธดเธ (Official References & Citations)

1. **NinjaTrader Futures Blog** โ€” *Understanding the 4 Common Volume Profile Shapes (D, P, b, B)*
   - https://ninjatrader.com/futures/blogs/trade-futures-understanding-the-4-common-volume-profile-shapes/
2. **Trader-Dale** โ€” *Market Profile Different Profiles and Their Application*
   - https://www.trader-dale.com/market-profile-different-profiles-and-their-application/
3. **Trader-Dale** โ€” *How to Read Volume Profile Shapes: What the Market is Really Telling You*
   - https://www.trader-dale.com/how-to-read-volume-profile-shapes-what-the-market-is-really-telling-you/
4. **CrossTrade Learn** โ€” *Technical Indicators: Market Profile & TPO*
   - https://crosstrade.io/learn/technical-indicators/market-profile-tpo
5. **GoCharting Blog** โ€” *Market Profile Indicator Complete Guide*
   - https://gocharting.com/blog/market-profile-indicator/market-profile-complete-guide
6. **Alchemy Markets** โ€” *Volume Profile Effective Trading Guide*
   - https://alchemymarkets.com/education/indicators/volume-profile/

---

## Database Architecture (เธฃเธฒเธขเธฅเธฐเน€เธญเธตเธขเธ”เธเธฒเธเธเนเธญเธกเธนเธฅ)

### 1. Database: `Step 3` (XAUUSD / GC=F)
* `m5`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 5 เธเธฒเธ—เธต (เธขเนเธญเธเธซเธฅเธฑเธ 60 เธงเธฑเธ)
* `m15`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 15 เธเธฒเธ—เธต (เธขเนเธญเธเธซเธฅเธฑเธ 60 เธงเธฑเธ)
* `h1`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 1 เธเธฑเนเธงเนเธกเธ (เธขเนเธญเธเธซเธฅเธฑเธ 2 เธเธต)
* `h4`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 4 เธเธฑเนเธงเนเธกเธ (เธเธณเธเธงเธ“เธเธฒเธ 1h)
* `h6`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 6 เธเธฑเนเธงเนเธกเธ (เธเธณเธเธงเธ“เธเธฒเธ 1h)
* `d1`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 1 เธงเธฑเธ (เธขเนเธญเธเธซเธฅเธฑเธเธซเธฅเธฒเธขเธเธต)

### 2. Database: `eurusd` (EURUSD=X)
* `m5`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 5 เธเธฒเธ—เธต (เธขเนเธญเธเธซเธฅเธฑเธ 60 เธงเธฑเธ)
* `m15`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 15 เธเธฒเธ—เธต (เธขเนเธญเธเธซเธฅเธฑเธ 60 เธงเธฑเธ)
* `h1`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 1 เธเธฑเนเธงเนเธกเธ (เธขเนเธญเธเธซเธฅเธฑเธ 2 เธเธต)
* `h4`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 4 เธเธฑเนเธงเนเธกเธ (เธเธณเธเธงเธ“เธเธฒเธ 1h)
* `h6`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 6 เธเธฑเนเธงเนเธกเธ (เธเธณเธเธงเธ“เธเธฒเธ 1h)
* `d1`: เธเนเธญเธกเธนเธฅเธฃเธฒเธเธฒ 1 เธงเธฑเธ (เธ—เธจเธเธดเธขเธก 5 เธ•เธณเนเธซเธเนเธ)

### 3. Database: Macro Indicators
* `dxy`: `h1`, `d1` (US Dollar Index)
* `us10y`: `d1` (US 10-Year Treasury Yield)
* `vix`: `d1` (CBOE Volatility Index)
* `gdx`: `d1` (VanEck Gold Miners ETF)

---

## Project Structure

```
Quant_Trade/
โ””โ”€โ”€ yahoo-finance-tracker/
    โ”โ”€โ”€ quant_backend.py          # Core Quant Data Engine (Fetch, Resample 4h/6h, Store)
    โ”โ”€โ”€ fetcher/                  # Yahoo Finance & Market API client
    โ”   โ”โ”€โ”€ yahoo_finance_client.py
    โ”   โ””โ”€โ”€ symbols.py
    โ”โ”€โ”€ storage/                  # MySQL schema definitions
    โ”   โ””โ”€โ”€ schema_quant.sql      # Step 1 (Raw Data) unified schema
    โ”โ”€โ”€ analysis/                 # Quant Engines & Indicators
    โ”   โ”โ”€โ”€ technical_analysis.py # Trend Analyzer (EMA 20, 50, 100)
    โ”   โ”โ”€โ”€ features.py           # Feature Engineering & Resampling
    โ”   โ”โ”€โ”€ smc_crt.py            # SMC (BOS, CHoCH, FVG, OB) & CRT Engine
    โ”   โ”โ”€โ”€ volume_profile.py     # Volume Profile Engine (POC, VAH, VAL)
    โ”   โ””โ”€โ”€ divergence/           # Modular Systematic Divergence Package
    โ”       โ”โ”€โ”€ __init__.py       # Package facade & re-exports
    โ”       โ”โ”€โ”€ data_collection.py# Data alignment & CFTC COT loader
    โ”       โ”โ”€โ”€ feature_engineering.py # Rolling Z-Score & Beta Spread
    โ”       โ”โ”€โ”€ detection.py      # Causal Technical/Macro Divergence Detectors
    โ”       โ”โ”€โ”€ confirmation.py   # Volatility (VIX) & Correlation filters
    โ”       โ””โ”€โ”€ signal_generator.py# Composite Scoring & ATR Risk SL/TP
    โ”โ”€โ”€ test_quick_divergence.py  # Quick validation test runner script
    โ”โ”€โ”€ dashboard/                # Interactive Web Dashboard
    โ”   โ””โ”€โ”€ app.py                # Streamlit Multi-TF Plotly Dashboard
    โ”โ”€โ”€ docker-compose.yml        # Docker setup (MySQL, phpMyAdmin, Airflow)
    โ”โ”€โ”€ .env.example              # Environment template
    โ”โ”€โ”€ requirements.txt          # Python dependencies
    โ””โ”€โ”€ README.md
```

---

## Trend Analysis Indicators

* **EMA 20**: Exponential Moving Average (Short-term trend filter)
* **EMA 50**: Exponential Moving Average (Medium-term trend filter)
* **EMA 100**: Exponential Moving Average (Long-term trend filter)

*(เธฃเธญเธเธฃเธฑเธเธเธฒเธฃเน€เธเธดเธ”-เธเธดเธ”เธเธณเธเธงเธ“เน€เธเธทเนเธญเนเธเนเน€เธเนเธ Trend Filter เนเธซเนเธเธฑเธ Quant Model)*
