@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run START_WINDOWS.bat first and create the administrator account.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/register.sqlite3'); assert c.execute('select count(*) from users').fetchone()[0]>0" 2>nul
if errorlevel 1 (
  echo Complete administrator setup using START_WINDOWS.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -c "import openpyxl,docx,pdfplumber,olefile,pypdfium2" 2>nul
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements.txt
  if errorlevel 1 (
    echo Dependency installation failed. Read START-HERE.txt.
    pause
    exit /b 1
  )
)
echo Other computers use http://THIS-COMPUTER-IPv4:8765
echo Use ipconfig to find this computer's IPv4 address.
echo Keep this window open while the office is using the system.
ipconfig
.venv\Scripts\python.exe app.py --host 0.0.0.0
pause
