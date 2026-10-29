@echo off
REM 0_wheels_indir.bat - INTERNETLI bilgisayarda bir kere calistirilir.
REM Windows (Python 3.11, 64 bit) icin gereken paketleri wheels klasorune indirir.
setlocal
cd /d "%~dp0"
title Paketler indiriliyor
echo ============================================================
echo  Paketler indiriliyor (yaklasik 280 MB, internet gerekir)
echo ============================================================
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

if not exist wheels mkdir wheels

echo.
echo Indirme basliyor, lutfen bekleyin...
%PY% -m pip download --python-version 3.11 --implementation cp --abi cp311 --platform win_amd64 --only-binary=:all: -d wheels -r requirements_build.txt
if errorlevel 1 (
    echo.
    echo [HATA] Indirme basarisiz oldu. Internet baglantisini kontrol edin
    echo        ve bu dosyayi tekrar calistirin.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Tamamlandi. wheels klasoru hazir.
echo  Sonraki adim: 1_kurulum.bat
echo ============================================================
pause
