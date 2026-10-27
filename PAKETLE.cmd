@echo off
cd /d "%~dp0"
python -m pip install -r requirements-paket.txt
python paketle.py
if errorlevel 1 (echo PAKET BASARISIZ & pause & exit /b 1)
pause
