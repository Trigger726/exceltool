@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo  SheetKit - Windows build
echo ============================================================
echo.

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js was not found on PATH.
  echo         Install the LTS build from https://nodejs.org/ and run again.
  exit /b 1
)

if not exist "%PY%" (
  echo [1/5] Creating the Python virtual environment...
  python -m venv "%VENV%"
  if errorlevel 1 exit /b 1
) else (
  echo [1/5] Using the existing virtual environment.
)

echo [2/5] Installing Python dependencies...
"%PY%" -m pip install --disable-pip-version-check --timeout 120 --retries 10 -r requirements-dev.txt
if errorlevel 1 exit /b 1

echo [3/5] Installing frontend dependencies...
pushd frontend
call npm install --no-audit --no-fund
if errorlevel 1 (popd & exit /b 1)

echo [4/5] Building the frontend into a single HTML file...
call npm run build
if errorlevel 1 (popd & exit /b 1)
popd

if not exist "python\sheetkit\webui\index.html" (
  echo [ERROR] The frontend build did not produce python\sheetkit\webui\index.html
  exit /b 1
)

echo [5/5] Packaging the Windows executable...
"%PY%" -m PyInstaller --noconfirm --clean SheetKit.spec
if errorlevel 1 exit /b 1

echo.
echo ============================================================
echo  Build finished: dist\SheetKit.exe
echo  Double-click it to run. Copy that single file anywhere.
echo  The target machine needs the WebView2 Runtime
echo  (built into Windows 11; Windows 10 may need it installed).
echo ============================================================
exit /b 0
