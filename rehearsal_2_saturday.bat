@echo off
cd /d "%~dp0"
set STOCK_APP_MEMORY=demo
set STOCK_APP_STAGE=wait
set STOCK_APP_NOW=2026-11-28 09:40:00
echo Dummy data only. Real data is not used. Close this window to stop.
start "" http://localhost:8615
python -m streamlit run app.py --server.port 8615 --server.headless true
pause
