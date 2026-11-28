@echo off
cd /d "%~dp0"
set STOCK_APP_MEMORY=demo
set STOCK_APP_STAGE=wait
set STOCK_APP_NOW=2026-11-30 08:00:00
echo Dummy data only. Real data is not used. Close this window to stop.
start "" http://localhost:8616
python -m streamlit run app.py --server.port 8616 --server.headless true
pause
