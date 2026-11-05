@echo off
REM 3_testleri_calistir.bat - kurulumu ve uygulama mantigini dogrular (internet gerekmez).
setlocal
cd /d "%~dp0"
title Testler
if not exist venv\Scripts\python.exe (
    echo [HATA] venv bulunamadi. Once 1_kurulum.bat calistirin.
    pause
    exit /b 1
)
venv\Scripts\python.exe -c "import pytest" >nul 2>nul
if errorlevel 1 (
    echo [HATA] pytest kurulu degil. wheels klasorunde test paketleri olmayabilir;
    echo        0_wheels_indir.bat ve 1_kurulum.bat'i yeniden calistirin.
    pause
    exit /b 1
)
set QT_QPA_PLATFORM=offscreen
venv\Scripts\python.exe -m pytest tests -q
if errorlevel 1 (
    echo.
    echo [HATA] Testler BASARISIZ. Bu kurulumu gercek teste vermeyin.
) else (
    echo.
    echo Tum testler basarili.
)
pause
