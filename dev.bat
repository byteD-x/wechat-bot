@echo off
setlocal
chcp 65001 >nul

echo.
echo ============================================================
echo   WeChat AI Assistant - Dev Mode
echo ============================================================
echo.

cd /d "%~dp0"

if not exist "node_modules" (
    echo Installing frontend dependencies...
    call npm install
    if errorlevel 1 (
        echo Frontend dependency install failed.
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Missing .venv\Scripts\python.exe. Please create the virtualenv first.
    exit /b 1
)

echo Starting Electron dev mode...
echo Backend will be started by Electron automatically.
call npm run dev
exit /b %errorlevel%
