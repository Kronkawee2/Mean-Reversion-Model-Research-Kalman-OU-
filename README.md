# Quant Trader — Multi-Asset Quantitative Trading System

ระบบดึงและจัดเตรียมข้อมูลราคาสินทรัพย์หลัก ทองคำ (XAUUSD / GC=F) และ EUR/USD (EURUSD=X) พร้อมด้วยข้อมูลตัวแปรมหภาค (DXY, US10Y, VIX, GDX) แบบ Multi-Timeframe สำหรับการพัฒนา Quant Machine Learning, Algorithmic Trading (SMC / CRT) และการทำ Backtesting

---

## Overview & System Objectives

ระบบสถาปัตยกรรมข้อมูลแบบ 3 ชั้น (Medallion Data Architecture: Bronze, Silver, Gold) ออกแบบสำหรับระบบ Quantitative Trading โดยประมวลผลข้อมูลครอบคลุม 6 กรอบเวลา (5m, 15m, 1h, 4h, 6h, 1d)

### Market Drivers & Inter-Market Relationships

```
                      [US Economic & Market Drivers]
                                    │
          ┌─────────────────────────┴─────────────────────────┐
          │                                                   │
  [DX-Y.NYB (DXY)]                                    [^TNX (US 10Y Yield)]
   ดัชนีดอลลาร์สหรัฐ                                    ผลตอบแทนพันธบัตรรัฐบาล
          │                                                   │
          └─────────────────────────┬─────────────────────────┘
                                    │
                ┌───────────────────┴───────────────────┐
                │                                       │
         [EUR/USD (EURUSD=X)]                   [XAU/USD (GC=F)]
          ยูโรเทียบดอลลาร์                       ทองคำเทียบดอลลาร์
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
| Institutional Position | CFTC COT Report (EUR & Gold) | CFTC.gov | cot_reports | Free |
| Gold ETF Reserve | SPDR Gold Shares (GLD) | SPDR Official | Direct CSV | Free |

---

## Data Architecture (3-Tier Medallion System)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. BRONZE LAYER (Raw Data — Immutable Storage)              │
│    - Trading Assets:                                        │
│        gold/   -> m5, m15, h1, h4, h6, d1                   │
│        eurusd/ -> m5, m15, h1, h4, h6, d1                   │
│    - Macro Drivers:                                         │
│        dxy/    -> h1, d1                                    │
│        us10y/  -> d1                                        │
│        vix/    -> d1                                        │
│        gdx/    -> d1                                        │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. SILVER LAYER (Processed & Feature Engineering)           │
│    - Indicators: EMA 20/50/200, ATR 14, RSI 14              │
│    - SMC Engine: BOS, CHoCH, FVG, Order Blocks              │
│    - CRT Engine: Asian Range, Session Sweeps, Equilibrium   │
│    - Volume Profile: POC, VAH, VAL, HVN, LVN               │
│    - 12 Divergence Models (Inter-market & Technical)        │
│                                                             │
│    silver_gold/   -> features, smc, crt, vol_profile, divs  │
│    silver_eurusd/ -> features, smc, crt, vol_profile, divs  │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. GOLD LAYER (Trading Signals & Dashboard)                 │
│    - Execution Logic: 5m/15m triggers with 1h/4h/6h/1d bias │
│    - Backtest Engine & Trade Logs                           │
│    - Interactive Web Dashboard                              │
│                                                             │
│    signals/ -> trade_signals, backtest_logs, equity_curve   │
└─────────────────────────────────────────────────────────────┘
```

---

## Quant Engines Overview

### 1. Smart Money Concepts (SMC Engine)
* Break of Structure (BOS) & Change of Character (CHoCH): ตรวจจับการทะลุโครงสร้างราคา HH, HL, LH, LL
* Order Blocks (OB): ค้นหาฐานราคาแท่งก่อนหน้าการขยายตัวแรง (High-displacement expansion)
* Fair Value Gaps (FVG): ตรวจจับโซนสภาวะเสียสมดุลราคาแบบ 3 แท่ง (`High[i-2] < Low[i]`)
* Liquidity Sweeps (BSL/SSL): ตรวจจับการกวาดสภาพคล่องเหนือ/ใต้ Swing High/Low

### 2. Candle Range Theory (CRT Engine)
* Asian Range (Accumulation): คำนวณกรอบราคาสูงสุด-ต่ำสุดช่วงตลาดเอเชีย (00:00-06:00 UTC)
* Session Sweep (Manipulation): ตรวจจับการกวาดกรอบราคาเอเชียช่วงตลาดลอนดอน/นิวยอร์ก
* Range Equilibrium: คำนวณจุดสมดุล 50% ของกรอบราคาแท่ง HTF (4h, 6h, 1d)

### 3. Volume Profile Engine
* Point of Control (POC): ระดับราคาที่มีวอลลุ่มการซื้อขายสะสมสูงสุด
* Value Area High (VAH) & Low (VAL): ขอบเขตพื้นที่วอลลุ่ม 70%
* High / Low Volume Nodes (HVN / LVN): โซนรับแนวต้านโครงสร้างวอลลุ่ม และโซนราคาพุ่งเร็ว

### 4. 12 Divergence Models Matrix
* Inter-Market Divergence (7 Models): EUR/USD vs Gold Ratio Z-Score, Gold vs DXY, EUR vs DXY, Gold vs Real Yield, EUR vs Yield Spread, Gold vs GDX Miners, Gold vs SPDR ETF Vault Holdings
* Technical & Volume Divergence (4 Models): RSI Regular, RSI Hidden, Volume & OBV Exhaustion, Stochastic/CCI
* Multi-Timeframe Alignment (1 Model): Confluence ระหว่าง HTF Hidden Divergence กับ LTF Regular Divergence

---

## Database Architecture (รายละเอียดฐานข้อมูล)

### 1. Database: `gold` (XAUUSD / GC=F)
* `m5`: ข้อมูลราคา 5 นาที (ย้อนหลัง 60 วัน)
* `m15`: ข้อมูลราคา 15 นาที (ย้อนหลัง 60 วัน)
* `h1`: ข้อมูลราคา 1 ชั่วโมง (ย้อนหลัง 2 ปี)
* `h4`: ข้อมูลราคา 4 ชั่วโมง (คำนวณจาก 1h)
* `h6`: ข้อมูลราคา 6 ชั่วโมง (คำนวณจาก 1h)
* `d1`: ข้อมูลราคา 1 วัน (ย้อนหลังหลายปี)

### 2. Database: `eurusd` (EURUSD=X)
* `m5`: ข้อมูลราคา 5 นาที (ย้อนหลัง 60 วัน)
* `m15`: ข้อมูลราคา 15 นาที (ย้อนหลัง 60 วัน)
* `h1`: ข้อมูลราคา 1 ชั่วโมง (ย้อนหลัง 2 ปี)
* `h4`: ข้อมูลราคา 4 ชั่วโมง (คำนวณจาก 1h)
* `h6`: ข้อมูลราคา 6 ชั่วโมง (คำนวณจาก 1h)
* `d1`: ข้อมูลราคา 1 วัน (ทศนิยม 5 ตำแหน่ง)

### 3. Database: Macro Indicators
* `dxy`: `h1`, `d1` (US Dollar Index)
* `us10y`: `d1` (US 10-Year Treasury Yield)
* `vix`: `d1` (CBOE Volatility Index)
* `gdx`: `d1` (VanEck Gold Miners ETF)

---

## Project Structure

```
Quant_Trade/
└── yahoo-finance-tracker/
    ├── quant_backend.py          # Core Quant Data Engine (Fetch, Resample 4h/6h, Store)
    ├── fetcher/                  # Yahoo Finance & Market API client
    │   ├── yahoo_finance_client.py
    │   └── symbols.py
    ├── storage/                  # MySQL schema definitions
    │   └── schema_quant.sql      # Bronze layer unified schema
    ├── analysis/                 # Quant Engines & Indicators
    │   ├── technical_analysis.py # Trend Analyzer (EMA 20, 50, 100)
    │   ├── features.py           # Feature Engineering & Resampling
    │   ├── smc_crt.py            # SMC (BOS, CHoCH, FVG, OB) & CRT Engine
    │   ├── volume_profile.py     # Volume Profile Engine (POC, VAH, VAL)
    │   └── divergence.py         # 12 Divergence Detection Engine
    ├── dashboard/                # Interactive Web Dashboard
    │   └── app.py                # Streamlit Multi-TF Plotly Dashboard
    ├── docker-compose.yml        # Docker setup (MySQL, phpMyAdmin, Airflow)
    ├── .env.example              # Environment template
    ├── requirements.txt          # Python dependencies
    └── README.md
```

---

## Trend Analysis Indicators

* **EMA 20**: Exponential Moving Average (Short-term trend filter)
* **EMA 50**: Exponential Moving Average (Medium-term trend filter)
* **EMA 100**: Exponential Moving Average (Long-term trend filter)

*(รองรับการเปิด-ปิดคำนวณเพื่อใช้เป็น Trend Filter ให้กับ Quant Model)*