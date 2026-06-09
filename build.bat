@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

echo.
echo ==============================================================
echo            WeChat AI Assistant - Build Script
echo ==============================================================
echo.

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"
if errorlevel 1 (
    echo Failed to enter project root: %PROJECT_ROOT%
    exit /b 1
)

echo [1/6] Checking Node.js...
where node >nul 2>&1
if errorlevel 1 (
    echo Node.js was not found. Install Node.js first.
    echo https://nodejs.org/
    exit /b 1
)
for /f "tokens=*" %%i in ('node -v') do set "NODE_VERSION=%%i"
echo     Node.js !NODE_VERSION!

echo [2/6] Checking Python...
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python was not found. Install Python 3.8+ first.
        exit /b 1
    )
    set "PYTHON_EXE=python"
)
for /f "tokens=*" %%i in ('"!PYTHON_EXE!" --version') do set "PY_VERSION=%%i"
echo     !PY_VERSION!

echo [3/6] Checking Node dependencies...
if not exist "node_modules" (
    call npm install
    if errorlevel 1 (
        echo npm install failed.
        exit /b 1
    )
)
echo     Node dependencies are ready.

echo [4/6] Building Python backend...
if not exist "backend-dist" mkdir backend-dist

"!PYTHON_EXE!" -m PyInstaller --name wechat-bot-backend --distpath "%PROJECT_ROOT%backend-dist" --workpath "%PROJECT_ROOT%build" --specpath "%PROJECT_ROOT%build" --noconfirm --clean --console --hidden-import wcferry --hidden-import quart --hidden-import hypercorn --hidden-import openai --hidden-import httpx "%PROJECT_ROOT%run.py"
if errorlevel 1 (
    echo PyInstaller build failed.
    exit /b 1
)
echo     Python backend build complete.

echo [5/6] Auditing backend artifacts...
"!PYTHON_EXE!" "%PROJECT_ROOT%scripts\audit_release_artifacts.py" "%PROJECT_ROOT%backend-dist\wechat-bot-backend"
if errorlevel 1 (
    echo Backend artifact audit failed.
    exit /b 1
)
echo     Backend artifact audit complete.

echo [6/6] Building Electron release packages (portable + setup)...
call npm run build:release
if errorlevel 1 (
    echo Electron release build failed.
    exit /b 1
)

if exist "%PROJECT_ROOT%release\win-unpacked" rmdir /s /q "%PROJECT_ROOT%release\win-unpacked"
if exist "%PROJECT_ROOT%release\builder-debug.yml" del /f /q "%PROJECT_ROOT%release\builder-debug.yml"
if exist "%PROJECT_ROOT%release\app-update.yml" del /f /q "%PROJECT_ROOT%release\app-update.yml"
del /f /q "%PROJECT_ROOT%release\*.msi" >nul 2>&1

echo     Generating SHA256SUMS.txt...
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$releaseDir = '%PROJECT_ROOT%release'; $files = Get-ChildItem -LiteralPath $releaseDir -Filter '*.exe' | Sort-Object Name; if (-not $files) { throw 'No release executables found.' }; $lines = foreach ($file in $files) { '{0}  {1}' -f (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLower(), $file.Name }; Set-Content -LiteralPath (Join-Path $releaseDir 'SHA256SUMS.txt') -Value $lines -Encoding utf8"
if errorlevel 1 (
    echo SHA256SUMS generation failed.
    exit /b 1
)

"!PYTHON_EXE!" "%PROJECT_ROOT%scripts\audit_release_artifacts.py" --allow-release-update-metadata "%PROJECT_ROOT%release"
if errorlevel 1 (
    echo Electron artifact audit failed.
    exit /b 1
)

echo.
echo ==============================================================
echo                    Build Complete
echo ==============================================================
echo.
echo Output: %PROJECT_ROOT%release\
echo.

if not defined CI if exist release start "" explorer release >nul 2>&1
