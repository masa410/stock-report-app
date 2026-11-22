@echo off
cd /d "%~dp0"
python sync_pc.py
if exist app_url.txt (
  for /f "usebackq delims=" %%u in ("app_url.txt") do start "" "%%u"
)
pause
