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

## Systematic Quantitative Divergence Engine (วิธีการคำนวณ ลอจิกการให้คะแนน และแหล่งอ้างอิงทางการ)

ระบบ Divergence Engine ในโฟลเดอร์ `analysis/divergence/` ถูกออกแบบขึ้นตามหลักการ **Quantitative Multi-Factor Model** สำหรับสินทรัพย์ **XAU/USD** และ **EUR/USD** โดยอ้างอิงจากทฤษฎีการเงินและแหล่งข้อมูลทางการ

### 1. โครงสร้างการทำงาน 5 ขั้นตอน (5-Step Pipeline Architecture)

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Data Collection  ──>  ดึงราคา Gold/EURUSD + DXY + VIX + COT Report  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. Feature Engine   ──>  คำนวณ Z-Score, Rolling Beta & Linear Slope    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. Detector Engine  ──>  ตรวจจับ Technical + Macro + COT Divergence   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 4. Confirmation     ──>  เช็ก VIX Risk + Correlation Stability Filter  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 5. Signal Generator ──>  ออกคำสั่ง BUY/SELL + คำนวณ ATR Stop-Loss / TP  │
└────────────────────────────────────────────────────────────────────────┘
```

---

### 2. วิธีการและลอจิกการถ่วงน้ำหนักคะแนน (Multi-Factor Scoring Methodology)

ระบบใช้การประมวลผลคะแนนรวม **Composite Score (-100 ถึง +100)** เพื่อการันตีว่าจะออกออเดอร์เมื่อเกิดการยืนยันร่วมกันหลายปัจจัย (Multi-factor Confluence) เท่านั้น:

| ประเภทปัจจัย (Factor Category) | สัญญาณ (Signal Type) | คะแนน (Score Weight) | เหตุผลทางสถิติและการเงิน |
| :--- | :--- | :---: | :--- |
| **Inter-Market Macro Driver** | DXY / Bond Yield Divergence | **+50 / -50** | **ปัจจัยมหภาคชี้ขาด (Fundamental Market Driver)** เงินทุนเคลื่อนย้ายตามดอลลาร์และดอกเบี้ย |
| **Technical Divergence (Reversal)** | RSI Regular Bullish / Bearish | **+40 / -40** | เกิดตรงจุดสิ้นสุดเทรนด์ (Extrema) มีนัยสำคัญทางสถิติสูงในการจับจุดกลับตัวใหญ่ |
| **Technical Divergence (Continuation)** | RSI Hidden Bullish / Bearish | **+25 / -25** | สัญญาณย่อยยืนยันการไปต่อตามเทรนด์เดิม |
| **Volatility Risk Adjustment** | High Volatility Regime ($VIX > 25.0$) | **คะแนนโดนหาร 2 (-50%)** | ป้องกันสัญญาณหลอกในช่วงสภาวะตลาดวิกฤตผันผวนสูง |

#### 🎯 เกณฑ์การออกคำสั่งเทรด (Trade Execution Threshhold Logic):
* **คะแนน $\ge +50$**: สั่ง **`BUY`** (ต้องมี Macro Driver หรือ Technical Reversal + Continuation ร่วมกัน)
* **คะแนน $\le -50$**: สั่ง **`SELL`**
* **คะแนนระหว่าง $-49$ ถึง $+49$**: สั่ง **`HOLD`** (ถือรอ ไม่เปิดออเดอร์เมื่อเห็นสัญญาณอินดิเคเตอร์ตัวเดียว)

---

### 3. ระบบบริหารจัดการความเสี่ยง (ATR Dynamic Risk Management)

ระบบคำนวณจุดตัดขาดทุน (Stop Loss) และจุดทำกำไร (Take Profit) ตามความผันผวนจริงของราคา (J. Welles Wilder's ATR Framework):
* **Long Stop Loss (SL)**: $\text{Entry Price} - (1.5 \times \text{ATR}_{14})$
* **Long Take Profit (TP)**: $\text{Entry Price} + (3.0 \times \text{ATR}_{14})$ *(การันตี Risk:Reward Ratio ที่ 1:2)*
* **Short Stop Loss (SL)**: $\text{Entry Price} + (1.5 \times \text{ATR}_{14})$
* **Short Take Profit (TP)**: $\text{Entry Price} - (3.0 \times \text{ATR}_{14})$ *(การันตี Risk:Reward Ratio ที่ 1:2)*

---

### 4. แหล่งข้อมูลทางการและเอกสารอ้างอิง (Official References & Citations)

1. **Corporate Finance Institute (CFI)** — *Divergence Definition & Capital Markets Technical Analysis*
   - https://corporatefinanceinstitute.com/resources/career-map/sell-side/capital-markets/divergence/
2. **Investopedia** — *What Is Divergence in Technical Analysis and Trading?*
   - https://www.investopedia.com/terms/d/divergence.asp
3. **CFTC (U.S. Commodity Futures Trading Commission)** — *Commitment of Traders (COT) Reports*
   - https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
4. **CME Group** — *Gold Futures (GC=F), Silver Futures (SI=F) & FX Intermarket Specifications*
   - https://www.cmegroup.com/
5. **CBOE (Chicago Board Options Exchange)** — *CBOE Volatility Index (VIX) Guidelines*
   - https://www.cboe.com/tradable_products/vix/
6. **UHAS** — *Divergence คืออะไร พร้อมเทคนิคการอ่านกราฟ*
   - https://uhas.com/what-is-divergence-forex/
7. **LiteFinance** — *การเทรดแบบ Divergence คืออะไร*
   - https://www.litefinance.org/th/blog/for-professionals/divergence-ni-fxreks-kar-therd-baeb-divergence-khux-xari-laea-thanganyangri/
8. **JustMarkets** — *ไดเวอร์เจนซ์ (Divergence) คืออะไร และใช้งานอย่างไร*
   - https://justmarkets.com/th/trading-articles/learning/what-is-divergence-and-how-to-use-it
9. **WikiFX** — *How to use divergence effectively*
   - https://www.wikifx.com/th/learn/202405145244267079.html

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
    │   └── divergence/           # Modular Systematic Divergence Package
    │       ├── __init__.py       # Package facade & re-exports
    │       ├── data_collection.py# Data alignment & CFTC COT loader
    │       ├── feature_engineering.py # Rolling Z-Score & Beta Spread
    │       ├── detection.py      # Causal Technical/Macro Divergence Detectors
    │       ├── confirmation.py   # Volatility (VIX) & Correlation filters
    │       └── signal_generator.py# Composite Scoring & ATR Risk SL/TP
    ├── test_quick_divergence.py  # Quick validation test runner script
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