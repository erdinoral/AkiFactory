@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 (
    echo [HATA] Klasore gidilemedi.
    pause
    exit /b 1
)

chcp 65001 >nul 2>&1
title AkiFactory

set "ROOT=%~dp0"
set "PYEXE=%ROOT%.venv\Scripts\python.exe"
set "PYW=%ROOT%.venv\Scripts\pythonw.exe"
set "ELECTRON_DIR=%ROOT%electron"
set "ELECTRON_EXE=%ELECTRON_DIR%\node_modules\electron\dist\electron.exe"
set "MARKER=%ROOT%.aki_kuruldu"

rem pythonw varsa konsolsuz script; yoksa python.exe
set "PYRUN=%PYEXE%"
if exist "%PYW%" set "PYRUN=%PYW%"

rem --- Sistem Python bul (3.11 / 3.12) ---
set "BASEPY="
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "BASEPY=%%I"
    if not defined BASEPY (
        for /f "delims=" %%I in ('py -3.11 -c "import sys; print(sys.executable)" 2^>nul') do set "BASEPY=%%I"
    )
)
if not defined BASEPY (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "BASEPY=%%I"
    )
)

rem --- .venv yoksa / bozuksa olustur veya onar ---
set "NEED_VENV=0"
if not exist "%PYEXE%" set "NEED_VENV=1"
if "%NEED_VENV%"=="0" (
    "%PYEXE%" --version >nul 2>&1
    if errorlevel 1 set "NEED_VENV=1"
)

if "%NEED_VENV%"=="1" (
    if not defined BASEPY (
        echo [HATA] Python 3.11 veya 3.12 gerekli.
        echo   https://www.python.org/downloads/
        echo   veya: winget install Python.Python.3.12
        echo   Kurulumda "Add python.exe to PATH" secin, sonra bu PC'yi yeniden baslatin.
        pause
        exit /b 1
    )
    echo [venv] .venv hazirlaniyor / onariliyor...
    "%BASEPY%" -u "%ROOT%scripts\ensure_venv.py"
    if errorlevel 1 (
        echo [HATA] .venv olusturulamadi.
        pause
        exit /b 1
    )
)

if not exist "%PYEXE%" (
    echo [HATA] .venv\Scripts\python.exe hala yok.
    pause
    exit /b 1
)

rem --- Ilk kurulum (motor bagimliliklari, config, modeller) ---
if not exist "%MARKER%" (
    echo [kurulum] Ilk kurulum basliyor — 5-20 dk surebilir...
    "%PYEXE%" -u "%ROOT%scripts\bootstrap.py" --kur
    if errorlevel 1 (
        echo [HATA] Ilk kurulum basarisiz.
        echo  Yukaridaki [HATA] satirlarini kontrol edin, sonra AkiFactory.bat'i tekrar calistirin.
        pause
        exit /b 1
    )
)

if not exist "%ELECTRON_DIR%\node_modules" (
    where node >nul 2>&1
    if errorlevel 1 (
        echo [HATA] Node.js gerekli: https://nodejs.org/
        echo   LTS surumunu kurun, PATH'e ekleyin, terminali kapatip yeniden acin.
        pause
        exit /b 1
    )
    echo [Electron] Ilk kurulum — npm install...
    pushd "%ELECTRON_DIR%"
    call npm.cmd install
    if errorlevel 1 (
        popd
        echo [HATA] npm install basarisiz.
        pause
        exit /b 1
    )
    popd
)

if not exist "%ELECTRON_EXE%" (
    where node >nul 2>&1
    if errorlevel 1 (
        echo [HATA] Node.js gerekli: https://nodejs.org/
        pause
        exit /b 1
    )
    echo [Electron] Binary eksik — onariliyor...
    pushd "%ELECTRON_DIR%"
    call npm.cmd run repair
    if errorlevel 1 (
        popd
        echo [HATA] Electron kurulamadi.
        pause
        exit /b 1
    )
    popd
)

if not exist "%ELECTRON_EXE%" (
    echo [HATA] electron.exe bulunamadi.
    pause
    exit /b 1
)

rem On temizlik / surum — konsolsuz (pythonw)
"%PYRUN%" "%ROOT%scripts\prelaunch_cleanup.py" >nul 2>&1
"%PYRUN%" "%ROOT%scripts\sync_version.py" >nul 2>&1

echo.
echo  AkiFactory aciliyor...
echo.

rem npm.cmd KULLANMA — ekstra konsol flash eder.
rem Electron'u ayri surecte ac, bat penceresini kapat.
start "AkiFactory" /D "%ELECTRON_DIR%" "%ELECTRON_EXE%" .

endlocal
exit /b 0
