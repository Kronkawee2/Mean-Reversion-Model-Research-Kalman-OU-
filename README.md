# Quant Trader — Multi-Asset Data Engine

ระบบดึงและจัดเตรียมข้อมูลราคา Multi-Timeframe สำหรับทองคำ (XAUUSD / GC=F), EUR/USD (EURUSD=X) และข้อมูลตัวแปรมหภาค (DXY, US10Y, VIX, GDX) เพื่อใช้ในการสร้าง Quant Model และระบบเทรดอัตโนมัติ

---

## Overview

ระบบทำงานในรูปแบบ Medallion Architecture โดยในขั้น Bronze Layer จะจัดเก็บข้อมูลดิบ (Raw OHLCV) แยกตามสินทรัพย์ลงใน MySQL Database เพื่อความเร็วและความเป็นระเบียบในการดึงไปสกัด Features

### Data Flow Architecture

```
                                [ Free Data Sources ]
                         (Yahoo Finance / CFTC / SPDR)
                                       │
                                       ▼
                     [ Multi-Timeframe Engine (Backend) ]
                        - Fetch 5m, 15m, 1h, 1d
                        - Calculate 4h, 6h via Resampling
                                       │
                                       ▼
                  ┌────────────────────┴────────────────────┐
                  │          MySQL Databases (Bronze)        │
                  ├─────────────────────────────────────────┤
                  │ Assets:                                 │
                  │   - gold    (m5, m15, h1, h4, h6, d1)  │
                  │   - eurusd  (m5, m15, h1, h4, h6, d1)  │
                  │                                         │
                  │ Macro:                                  │
                  │   - dxy     (h1, d1)                    │
                  │   - us10y   (d1)                        │
                  │   - vix     (d1)                        │
                  │   - gdx     (d1)                        │
                  └────────────────────┬────────────────────┘
                                       │
                                       ▼
                    [ Silver & Gold Layers (Quant Models) ]
                        - Feature Engineering & SMC/CRT
                        - Backtesting & Execution Signals
```

---

## Database Architecture

ข้อมูลใน Bronze Layer ถูกแยกเก็บเป็น Database ตามสินทรัพย์เพื่อป้องกันข้อมูลปนกันและรองรับการดึงแบบขนาน:

### 1. Trading Assets
* **gold**: `m5`, `m15`, `h1`, `h4`, `h6`, `d1` (ราคาทองคำ GC=F)
* **eurusd**: `m5`, `m15`, `h1`, `h4`, `h6`, `d1` (ราคา EUR/USD ทศนิยม 5 ตำแหน่ง)

### 2. Macro & Market Drivers
* **dxy**: `h1`, `d1` (US Dollar Index: DX-Y.NYB)
* **us10y**: `d1` (US 10-Year Treasury Yield: ^TNX)
* **vix**: `d1` (CBOE Volatility Index: ^VIX)
* **gdx**: `d1` (VanEck Gold Miners ETF: GDX)

---

## Project Structure

```
yahoo-finance-tracker/
├── quant_backend.py          # Core Data Engine (Fetch, Resample, MySQL Sync)
├── fetcher/                  # Yahoo Finance API client
│   ├── yahoo_finance_client.py
│   └── symbols.py
├── storage/                  # MySQL Schema definitions
│   └── schema_quant.sql      # Schema สำหรับ Bronze Layer ทุก DB
├── analysis/                 # Indicator & Strategy modules
│   └── technical_analysis.py
├── dashboard/                # Interactive Web Dashboard
│   └── app.py
├── docker-compose.yml        # Docker setup (MySQL, phpMyAdmin, Airflow)
├── .env.example              # Environment variables template
├── requirements.txt          # Python dependencies
└── README.md
```