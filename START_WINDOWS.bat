@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Install Python 3.12 64-bit for Windows, then run this file again.
    pause
    exit /b 1
  )
)
.venv\Scripts\python.exe -c "import openpyxl,docx,pdfplumber,olefile,pypdfium2" 2>nul
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements.txt
  if errorlevel 1 (
    echo Installation failed. Read START-HERE.txt.
    pause
    exit /b 1
  )
)
echo Open http://127.0.0.1:8765 in your browser.
echo Create your personal administrator account before starting LAN mode.
.venv\Scripts\python.exe app.py --open-browser
pause
