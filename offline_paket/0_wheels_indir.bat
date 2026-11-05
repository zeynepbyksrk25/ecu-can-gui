@echo off
REM 0_wheels_indir.bat - INTERNETLI bilgisayarda bir kere calistirilir.
REM Windows (Python 3.11, 64 bit) icin gereken paketleri SABIT surum + hash ile wheels klasorune indirir.
setlocal
cd /d "%~dp0"
title Paketler indiriliyor
echo ============================================================
echo  Paketler indiriliyor (yaklasik 290 MB, internet gerekir)
echo ============================================================
set "PY="
py -3.11 -c "import sys; sys.exit(0 if sys.maxsize>2**32 else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3.11"
if not defined PY (
    python -c "import sys; sys.exit(0 if (sys.version_info[:2]==(3,11) and sys.maxsize>2**32) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo.
    echo [HATA] Python 3.11 ^(64 bit^) bulunamadi.
    echo        Bu paketler Python 3.11 / 64 bit icin hazirlandi; baska surumle
    echo        kurulum calismaz. Bulunan Python:
    python --version 2>nul
    py -0p 2>nul
    echo.
    echo        python.org adresinden Python 3.11 ^(64 bit^) kurun ve kurulumda
    echo        "Add python.exe to PATH" kutusunu isaretleyin. Microsoft Store'daki
    echo        Python kisayolu calismaz.
    echo.
    pause
    exit /b 1
)
echo Kullanilan Python: %PY%
%PY% --version

if not exist wheels mkdir wheels

echo.
echo Indirme basliyor, lutfen bekleyin...
%PY% -m pip download --python-version 3.11 --implementation cp --abi cp311 --platform win_amd64 --only-binary=:all: --require-hashes -d wheels -r requirements.lock.txt
if errorlevel 1 (
    echo.
    echo [HATA] Indirme basarisiz oldu. Internet baglantisini kontrol edin
    echo        ve bu dosyayi tekrar calistirin.
    echo.
    pause
    exit /b 1
)
%PY% -m pip download --python-version 3.11 --implementation cp --abi cp311 --platform win_amd64 --only-binary=:all: --require-hashes -d wheels -r requirements-dev.lock.txt
if errorlevel 1 (
    echo [UYARI] Test paketleri indirilemedi; 3_testleri_calistir.bat calismaz ^(exe etkilenmez^).
)

echo.
echo ============================================================
echo  Tamamlandi. wheels klasoru hazir.
echo  Sonraki adim: 1_kurulum.bat
echo ============================================================
pause
