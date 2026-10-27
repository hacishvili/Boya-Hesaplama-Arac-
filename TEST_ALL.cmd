@echo off
cd /d "%~dp0"
set QT_QPA_PLATFORM=offscreen
python -m unittest discover -s . -p "test_*.py" -v
if errorlevel 1 (echo TESTLER BASARISIZ & pause & exit /b 1)
echo TUM TESTLER BASARILI
pause
