@echo off
REM Setup script for Windows

echo.
echo Gold Yahoo Finance Tracker - Windows Setup
echo.

echo Creating virtual environment...
python -m venv venv

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt

if not exist .env (
    echo Creating .env file from template...
    copy .env.example .env
)

echo.
echo Setup complete.
echo.
echo To get started:
echo   1. Edit .env with your MySQL credentials
echo   2. Ensure MySQL server is running
echo   3. Initialize database: python init_db.py
echo   4. Run demo: python demo_mysql.py
echo   5. Start dashboard: streamlit run dashboard/1_Chart.py
echo.
pause
