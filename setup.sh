#!/bin/bash
# Setup script for Linux/Mac

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
cp -n .env.example .env 2>/dev/null || true

echo "Setup complete."
echo "Next steps:"
echo "   1. Edit .env with your MySQL credentials"
echo "   2. Make sure MySQL is running"
echo "   3. Initialize DB:     python init_db.py"
echo "   4. Run demo:          python demo_mysql.py"
echo "   5. Start dashboard:   streamlit run dashboard/1_chart.py"
echo "   6. (Optional) Docker: docker-compose up -d"
echo ""
echo "Yahoo Finance data is free and does not require an API key."
