# Quant Trader — Multi-Timeframe Data Engine (Gold & EUR/USD)

ระบบดึงข้อมูลและจัดเตรียมข้อมูลราคาทองคำ (**XAUUSD / GC=F**) และ **EUR/USD (EURUSD=X)** แบบ **Multi-Timeframe** สำหรับการพัฒนา **Quant Machine Learning / Algorithmic Model** จัดเก็บลง MySQL database แยกตามสินทรัพย์

## Project Overview

การดึงข้อมูลราคาทองคำ (**XAUUSD / GC=F**) และ **EUR/USD (EURUSD=X)** ้อนหลัง และ Real-time จาก Yahoo Finance 6 Timeframes (`5m`, `15m`, `1h`, `4h`, `6h`, `1d`) เพื่อนำไปสร้าง Features และพัฒนา Quant Model 

### Data Flow Architecture

Yahoo Finance (yfinance) ──> Multi-Timeframe Engine (Resample 4h/6h)
                                                   │
                                                   ▼
                                    Trend Filter (EMA 20 / 50 / 100)
                                                   │
                                                   ▼
                                     MySQL Databases (gold / eurusd)
                                                   │
                                                   ▼
                               Custom Quant Model & Strategy (ML / Algo)

## Database Architecture (โครงสร้างฐานข้อมูล)

ข้อมูลถูกจัดกลุ่มแยก Database ตามสินทรัพย์ (`gold` และ `eurusd`) เพื่อความสะอาดและรวดเร็วในการนำไป Train Model:

### Database: `gold` (Gold Futures / Spot - GC=F) และ `eurusd` (EUR/USD Forex - EURUSD=X) 
* `m5` : ข้อมูลราคา 5 นาที (ย้อนหลัง 60 วัน)
* `m15` : ข้อมูลราคา 15 นาที (ย้อนหลัง 60 วัน)
* `h1` : ข้อมูลราคา 1 ชั่วโมง (ย้อนหลัง ~2 ปี)
* `h4` : ข้อมูลราคา 4 ชั่วโมง (Calculated from 1h)
* `h6` : ข้อมูลราคา 6 ชั่วโมง (Calculated from 1h)
* `d1` : ข้อมูลราคา 1 วัน (ย้อนหลังหลายปี)
* `daily_summary`

## Project Structure

```
gold-yahoo-finance-tracker/
├── quant_backend.py          # Core Quant Data Engine (Fetch, Resample 4h/6h, Store)
├── fetcher/                  # Yahoo Finance API client
│   ├── yahoo_finance_client.py
│   └── symbols.py
├── storage/                  # MySQL schema and connection managers
│   └── schema_quant.sql      # Schema แยก DB gold และ eurusd
├── analysis/                 # Trend Analysis (EMA 20, 50, 100)
│   └── technical_analysis.py
├── dashboard/                # Streamlit UI Dashboard
│   └── app.py
├── docker-compose.yml        # Docker setup (MySQL, phpMyAdmin, Airflow)
├── .env                      # Database credentials
├── requirements.txt          # Python dependencies
└── README.md
```

## 📈 Trend Analysis Indicators
* **EMA 20**: Exponential Moving Average (Short-term trend)
* **EMA 50**: Exponential Moving Average (Medium-term trend)
* **EMA 100**: Exponential Moving Average (Long-term trend)

*(รองรับการเปิด-ปิด หรือคำนวณ EMA เพื่อใช้เป็น Trend Filter ให้กับ Quant Model)*
