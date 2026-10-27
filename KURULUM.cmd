@echo off
rem Python paketlerini kurar (Python 3.12+ 64 bit gerekli: https://www.python.org/downloads/)
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (echo KURULUM BASARISIZ & pause & exit /b 1)
echo Kurulum tamam. Program: CALISTIR.cmd
pause
