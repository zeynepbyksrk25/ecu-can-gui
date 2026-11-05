@echo off
REM 1_kurulum.bat - wheels klasorunden internetsiz kurulum (venv, sabit surum + hash dogrulamali).
setlocal
cd /d "%~dp0"
title Kurulum
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

if not exist wheels\* (
    echo [HATA] wheels klasoru bos. Once 0_wheels_indir.bat calistirin.
    pause
    exit /b 1
)

echo [1/3] Sanal ortam (venv) olusturuluyor...
%PY% -m venv --clear venv
if errorlevel 1 (
    echo [HATA] venv olusturulamadi.
    pause
    exit /b 1
)

echo [2/3] Paketler internetsiz kuruluyor (surum ve hash dogrulamali)...
venv\Scripts\python.exe -m pip install --no-index --find-links wheels --require-hashes -r requirements.lock.txt
if errorlevel 1 (
    echo [HATA] Paket kurulumu basarisiz oldu. Yukaridaki hatayi kontrol edin.
    echo        wheels klasoru eksik/bozuksa 0_wheels_indir.bat'i yeniden calistirin.
    pause
    exit /b 1
)
venv\Scripts\python.exe -m pip install --no-index --find-links wheels --require-hashes -r requirements.lock.txt -r requirements-dev.lock.txt >nul 2>nul
if errorlevel 1 (
    echo [UYARI] Test paketleri kurulamadi; 3_testleri_calistir.bat calismaz ^(exe etkilenmez^).
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
echo  calistirabilirsiniz. (Istege bagli: 3_testleri_calistir.bat)
echo ============================================================
pause
