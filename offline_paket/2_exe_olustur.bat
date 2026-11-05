@echo off
REM 2_exe_olustur.bat - 1_kurulum.bat'tan sonra calistirilir.
REM Cikti: dist\ECU_CAN_Arayuzu.exe
setlocal
cd /d "%~dp0"
title EXE olusturuluyor

if not exist venv\Scripts\python.exe (
    echo [HATA] venv bulunamadi. Once 1_kurulum.bat calistirin.
    pause
    exit /b 1
)
if not exist app\fonts\DejaVuSans.ttf (
    echo [HATA] app\fonts\DejaVuSans.ttf yok; PDF raporunda Turkce karakterler bozulur.
    pause
    exit /b 1
)

echo [1/3] PyInstaller kontrol ediliyor...
venv\Scripts\pyinstaller.exe --version
if errorlevel 1 (
    echo [HATA] PyInstaller calistirilamadi. 1_kurulum.bat'in basariyla
    echo        tamamlandigindan emin olun.
    pause
    exit /b 1
)

echo [2/3] Testler calistiriliyor (kuruluysa)...
venv\Scripts\python.exe -c "import pytest" >nul 2>nul
if errorlevel 1 (
    echo        pytest kurulu degil, testler atlandi.
) else (
    venv\Scripts\python.exe -m pytest tests -q
    if errorlevel 1 (
        echo.
        echo [UYARI] Testler BASARISIZ. exe yine de olusturulacak ama bu surum
        echo         gercek teste verilmemeli. Yukaridaki hatalari inceleyin.
        pause
    )
)

echo [3/3] .exe olusturuluyor (bu birkac dakika surebilir)...
REM --collect-submodules can / cantools:
REM   python-can, pcan gibi arayuzleri calisma anda (dinamik) yukler;
REM   PyInstaller'in statik analizi bunu KACIRIR ve exe calistirildiginda
REM   "No module named can.interfaces.pcan" hatasi verir. Bu bayraklar
REM   olmadan exe INTERNETSIZ bilgisayarda PCAN-USB ile CALISMAZ
REM   (bu proje icin gercek donanimla test edilip dogrulanmis bir hata).
REM --collect-all pya2l:
REM   pya2l, A2L dosyalarini SQLAlchemy uzerinden calisma aninda olusan
REM   bir semaya yukler; guvenli tarafta kalmak icin tum alt modulleri
REM   dahil ediyoruz.
REM --collect-all asammdf / --collect-submodules scipy.io: trend disa aktarma (MDF/MAT).
REM --add-data app\fonts: PDF raporu icin Turkce karakterli yazi tipi.
venv\Scripts\pyinstaller.exe main.py ^
    --name ECU_CAN_Arayuzu ^
    --onefile ^
    --noconsole ^
    --noconfirm ^
    --icon app_icon.ico ^
    --add-data "app\fonts;app\fonts" ^
    --collect-submodules can ^
    --collect-submodules cantools ^
    --collect-all pya2l ^
    --collect-all pyqtgraph ^
    --collect-all reportlab ^
    --collect-all asammdf ^
    --collect-submodules scipy.io ^
    --clean

if errorlevel 1 (
    echo.
    echo [HATA] PyInstaller basarisiz oldu. Yukaridaki hata mesajini okuyun.
    echo        Sik gorulen sorun: "No module named X" hatasi alirsaniz,
    echo        bu komuta "--collect-submodules X" veya "--hidden-import X"
    echo        ekleyip tekrar calistirin ^(can/cantools'ta da ayni sorun
    echo        yasanmis ve bu sekilde cozulmustu^).
    pause
    exit /b 1
)
if not exist dist\ECU_CAN_Arayuzu.exe (
    echo [HATA] dist\ECU_CAN_Arayuzu.exe olusmadi.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Basarili! .exe dosyaniz burada:
echo    dist\ECU_CAN_Arayuzu.exe
echo.
echo  Bu TEK dosyayi, PCAN-USB donanimi takili internetsiz
echo  bilgisayara kopyalayip dogrudan calistirabilirsiniz.
echo  (O bilgisayarda ayrica PEAK-System PCAN-USB surucusunun
echo  kurulu olmasi gerekir - README_WINDOWS.md'ye bakin.)
echo ============================================================
pause
