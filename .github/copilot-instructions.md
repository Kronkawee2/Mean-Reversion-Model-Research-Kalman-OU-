# Gold Yahoo Finance Tracker - Project Instructions

This is a Yahoo Finance data pipeline for gold trading analysis.

## Project Tech Stack
- **Language**: Python 3.9+
- **Data Source**: Yahoo Finance (yfinance) — ไม่ต้องใช้ API key
- **Database**: MySQL 8.0 (ดูผ่าน phpMyAdmin)
- **Dashboard**: Streamlit
- **Analysis**: Technical Analysis (RSI, MACD, SMA, Bollinger Bands)
- **Scheduling**: Apache Airflow + Docker
- **Data Processing**: Pandas, NumPy

## Key Components
1. **Fetcher**: Yahoo Finance integration via yfinance
2. **Storage**: MySQL with phpMyAdmin for data management
3. **Analysis**: Technical indicators and BULLISH/BEARISH signals
4. **Dashboard**: Multi-page Streamlit visualization
5. **Airflow**: Daily automated data fetching via Docker

## Setup Checklist
- [ ] Install Python 3.9+
- [ ] Install MySQL (XAMPP/WAMP/Docker)
- [ ] Create virtual environment
- [ ] Install dependencies from requirements.txt
- [ ] Configure .env file with MySQL credentials
- [ ] Initialize database: python init_db.py
- [ ] Run demo: python demo_mysql.py
- [ ] Start Streamlit dashboard
- [ ] (Optional) Setup Airflow with Docker

## Development Guidelines
- Keep fetcher, storage, and analysis modules independent
- Use environment variables for all credentials
- Yahoo Finance data is free — no API key required
- Use phpMyAdmin to inspect database tables
- Monitor Airflow DAGs for daily execution status

## Common Commands
```bash
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python init_db.py
python demo_mysql.py
streamlit run dashboard/app.py
docker-compose up -d
```
