@echo off
REM 1_kurulum.bat - wheels klasorunden internetsiz kurulum (venv).
setlocal
cd /d "%~dp0"
title Kurulum
set "PY="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python --version >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo.
    echo [HATA] Python bulunamadi.
    echo        python.org adresinden Python 3.11 kurun ve kurulumda
    echo        "Add python.exe to PATH" kutusunu isaretleyin.
    echo        ^(Microsoft Store'daki Python kisayolu calismaz; gercek
    echo        Python'u python.org'dan kurun.^)
    echo.
    pause
    exit /b 1
)
echo Kullanilan Python: %PY%

if not exist wheels\* (
    echo [HATA] wheels klasoru bos. Once 0_wheels_indir.bat calistirin.
    pause
    exit /b 1
)

echo [1/3] Sanal ortam (venv) olusturuluyor...
%PY% -m venv venv
if errorlevel 1 (
    echo [HATA] venv olusturulamadi.
    pause
    exit /b 1
)

echo [2/3] Paketler internetsiz kuruluyor...
venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements_build.txt
if errorlevel 1 (
    echo [HATA] Paket kurulumu basarisiz oldu. Yukaridaki hatayi kontrol edin.
    echo        Python surumu 3.11 olmali ^(py -3.11 --version^).
    pause
    exit /b 1
)

echo [3/3] Kurulum dogrulaniyor...
venv\Scripts\python.exe -c "import PySide6, can, cantools, pya2l, pyqtgraph, reportlab, PyInstaller; print('Tum paketler basariyla kuruldu.')"
if errorlevel 1 (
    echo [HATA] Kurulum dogrulanamadi.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Kurulum tamamlandi. Simdi 2_exe_olustur.bat dosyasini
echo  calistirabilirsiniz.
echo ============================================================
pause
