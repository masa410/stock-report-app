@echo off
cd /d "%~dp0"
set STOCK_APP_MEMORY=demo
set STOCK_APP_STAGE=prov
set STOCK_APP_NOW=2026-11-25 18:20:00
echo Dummy data only. Real data is not used. Close this window to stop.
start "" http://localhost:8614
python -m streamlit run app.py --server.port 8614 --server.headless true
pause
