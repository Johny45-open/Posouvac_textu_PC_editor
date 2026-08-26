@echo off
REM Spoustec pro NVDA – přístupný PC editor Posouvače textu
pushd "%~dp0"
py main.py
if errorlevel 1 (
  echo Spoustim pres python...
  python main.py
)
pause
