# 🪙 Quant Trader — Multi-Asset & Macro Data Engine (Gold & EUR/USD)

ระบบดึงข้อมูล จัดเตรียมข้อมูลราคาทองคำ (**XAUUSD / GC=F**), **EUR/USD (EURUSD=X)** และปัจจัยมหภาค (**DXY, US10Y, VIX, GDX**) แบบ **Multi-Timeframe** ตามสถาปัตยกรรม **3-Tier Medallion Data Architecture (Bronze / Silver / Gold)** เพื่อใช้พัฒนา **Quant Machine Learning & Algorithmic Model** โดยเฉพาะ

---

## 🎯 System Overview & Medallion Data Architecture

ข้อมูลถูกแบ่งสถาปัตยกรรมออกเป็น 3 เลเยอร์ เพื่อความเรียบร้อย ความเร็ว และการพัฒนา Quant Model ที่มีประสิทธิภาพ:

```
[ Free Data Sources: Yahoo Finance / Macro Data ]
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. BRONZE LAYER (Raw Data Storage — Immutable)              │
│    - ดึงและเก็บข้อมูล OHLCV ดิบ แยก 1 Database ต่อ 1 สินทรัพย์   │
│    - Trading Assets:  gold/  (m5, m15, h1, h4, h6, d1)     │
│                       eurusd/ (m5, m15, h1, h4, h6, d1)     │
│    - Macro Data:      dxy/   (h1, d1)                       │
│                       us10y/ (d1)                           │
│                       vix/   (d1)                           │
│                       gdx/   (d1)                           │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. SILVER LAYER (Processed & Feature Engineering)           │
│    - Feature Extraction (Returns, Volatility, ATR, EMA)     │
│    - Smart Money Concepts (BOS, CHoCH, FVG, Order Blocks)   │
│    - Candle Range Theory (Asian Range, Session Sweeps)      │
│    - Volume Profile (POC, VAH, VAL, HVN, LVN)               │
│    - 12 Divergence Models (Inter-Market & Technical)        │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. GOLD LAYER (Trading Signals & Interactive Dashboard)     │
│    - Backtest Engine & Trade Execution Signals (5m/15m)     │
│    - Streamlit + Plotly Interactive Web Dashboard           │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Bronze Layer Database Architecture

ข้อมูลดิบถูกจัดเก็บแยกเป็น **6 Databases** ใน MySQL เพื่อความสะอาดและความเร็วสูงสุด:

### 📁 1. Trading Assets Databases
* **`gold`** (Gold Futures / Spot - GC=F): `m5`, `m15`, `h1`, `h4` *(Resampled)*, `h6` *(Resampled)*, `d1`
* **`eurusd`** (EUR/USD Forex - EURUSD=X): `m5`, `m15`, `h1`, `h4` *(Resampled)*, `h6` *(Resampled)*, `d1`

### 📁 2. Macro Driver Databases
* **`dxy`** (US Dollar Index - DX-Y.NYB): `h1`, `d1` — วัดความแข็งแกร่งของดอลลาร์
* **`us10y`** (US 10-Year Treasury Yield - ^TNX): `d1` — อัตราผลตอบแทนพันธบัตรรัฐบาลสหรัฐฯ 10 ปี
* **`vix`** (CBOE Volatility Index - ^VIX): `d1` — ดัชนีความกลัว/ผันผวนของตลาด
* **`gdx`** (VanEck Gold Miners ETF - GDX): `d1` — ดัชนีหุ้นเหมืองทองคำ (ตัวชี้นำราคาทองคำ)

---

## 🌐 Macro Relationships & Drivers Matrix

```
                      [US Economic & Market Drivers]
                                   │
         ┌─────────────────────────┴─────────────────────────┐
         ▼                                                   ▼
 [DX-Y.NYB (DXY)]                                    [^TNX (US 10Y Yield)]
  ดัชนีดอลลาร์สหรัฐ                                    ผลตอบแทนพันธบัตรรัฐบาล 10 ปี
         │                                                   │
         ├─────────────────────────┬─────────────────────────┤
         ▼                         ▼                         ▼
 [EUR/USD (EURUSD=X)]       [^VIX / GDX]              [XAU/USD (GC=F)]
  ความสัมพันธ์ตรงข้าม DXY     ความผันผวน / หุ้นเหมือง     ทองคำเทียบดอลลาร์สหรัฐ
```

---

## 📦 Project Structure

```
Quant_Trade/
└── yahoo-finance-tracker/
    ├── quant_backend.py          # ⚙️ Bronze Layer Data Engine v4 (Sync gold, eurusd, dxy, us10y, vix, gdx)
    ├── fetcher/                  # Yahoo Finance API client & symbol registries
    │   ├── yahoo_finance_client.py
    │   └── symbols.py
    ├── storage/                  # MySQL schema definition
    │   └── schema_quant.sql      # Combined Schema for all 6 Bronze databases
    ├── analysis/                 # Quant Analysis & Feature Engineering
    │   └── technical_analysis.py # EMA 20/50/100 Trend Analyzer
    ├── dashboard/                # Interactive Dashboard
    │   └── app.py                # Streamlit Plotly Multi-TF Dashboard
    ├── docker-compose.yml        # Docker infrastructure (MySQL 8, phpMyAdmin, Airflow)
    ├── .env                      # Database credentials (gitignored)
    ├── .env.example              # Environment variables template
    ├── requirements.txt          # Python dependencies
    └── README.md
```

---

## 🚀 Quick Start (การใช้งาน)

### 1. เริ่มต้นระบบด้วย Docker
เปิด Docker Desktop แล้วรันคำสั่ง:
```bash
docker compose up -d
```
* **phpMyAdmin**: `http://localhost:8080` (User: `root`, Pass: `1234`)

### 2. รันสคริปต์ดึงและอัปเดตข้อมูล Bronze Layer ลง MySQL
```bash
.\venv\Scripts\python.exe quant_backend.py
```

### 3. เปิดหน้า Interactive Web Dashboard
```bash
.\venv\Scripts\python.exe -m streamlit run dashboard/app.py
```
เข้าดูหน้าต่างกราฟที่: `http://localhost:8501`