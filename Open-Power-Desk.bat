@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "Power Desk" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
  exit /b
)
if exist "%USERPROFILE%\anaconda3\pythonw.exe" (
  start "Power Desk" "%USERPROFILE%\anaconda3\pythonw.exe" "%~dp0app.py"
  exit /b
)
where pyw >nul 2>nul
if not errorlevel 1 (
  start "Power Desk" pyw -3 "%~dp0app.py"
  exit /b
)
echo Python with PyQt5 and psutil is required. See README.md for setup.
pause
