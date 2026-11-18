# OpenECU M220 — Test ve Kalibrasyon Aracı (ECU CAN Arayüzü)

PCAN-USB (ya da sanal hat) üzerinden bir ECU'yu izlemek, CAN çerçeveleri göndermek ve **CCP** ile
kalibre etmek için Windows masaüstü uygulaması (Python 3.11, PySide6). Kaynak kodun tamamı
[`offline_paket/`](offline_paket) klasöründedir; **internetsiz Windows bilgisayarda** tek `.exe` üretme
adımları [`offline_paket/README_WINDOWS.md`](offline_paket/README_WINDOWS.md) dosyasındadır.

## Neler yapar

| Sayfa | İşlev |
|---|---|
| **Ana Sayfa** | Motor Başlat / Durdur / **Acil Durdurma** (`Ctrl+Shift+E`), göstergeler, canlı grafik, eyleyici override |
| **CAN Monitor** | Bağlantı, canlı izleme (DBC çözümlemeli), çerçeve gönderme, CSV kaydı |
| **Kalibrasyon** | A2L tarayıcı, CCP bağlantısı, Parametre Listesi, Harita Editörü (yedekten yükleme dahil), geçmiş |
| **Analiz** | Çalışma Alanı (çoklu sinyal grafiği, matematik sinyalleri), Performans |
| **Kontrol Paneli** | Uçak girişleri / sensör override değerleri, senaryolar |
| **Tanılama ve Oturum** | CCP testi, DIAG_SERVICE, olay günlüğü, oturum kaydı, PDF rapor, **Excel (.xlsx) kayıt dosyası** |

Sayfa geçişi: `Ctrl+1` … `Ctrl+6`.

## Geliştirme (Linux / macOS / Windows)

```bash
cd offline_paket
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_build.txt -r requirements-dev.txt pytest-xdist ruff
python main.py
```

Windows dışında `pefile`, `pywin32-ctypes` ve `pyinstaller` kurmanıza gerek yoktur (yalnızca `.exe` derlemesi içindir).

```bash
cd offline_paket
ruff check .                      # statik denetim
python -m pytest tests -q -n auto # testler (ekransız; ~1 dk)
```

Linux'ta Qt için `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3` paketleri gerekir.
CI (`.github/workflows/testler.yml`) aynı iki komutu her push ve pull request'te çalıştırır.

## Kod yapısı

```
offline_paket/
  main.py                  giriş noktası (günlük, tek örnek kilidi, Windows zamanlayıcı çözünürlüğü)
  app/
    can_worker.py          CAN bağlantısı, alım iş parçacığı, bus-off kurtarma, gönderim kuyruğu
    scheduler.py           periyodik gönderim (ham kareler) + ortak zamanlama iş parçacığı
    control_panel.py       DBC tabanlı katalog, TxScheduler (Kontrol Paneli periyodik gönderimi)
    ccp/                   CCP protokolü, istemci, oturum iş parçacığı, simülatör, harita IO, tablo yedeği
    a2l.py, dbc.py         A2L ve DBC okuyucular (düz Python özetleri döner)
    xlsx_export.py         bağımlılıksız akışlı .xlsx yazıcı; log_export.py: oturum/CAN kaydı → Excel
    ui/main_window.py      pencere çatısı; iş mantığı ui/mainwin/ altındaki parçalarda
    ui/mainwin/            bağlantı, kalibrasyon/CCP, Ana Sayfa, Kontrol Paneli, profiller
    theme.py               TÜM renk token'ları (arayüzde renk sabiti yazmayın)
  tests/                   pytest (CCP simülatörü ve sanal CAN hattı ile; donanım gerektirmez)
```

## Güvenlik ilkeleri (değiştirirken korunmalı)

- **Acil Durdurma 1. basışta onay sormaz**, her sayfadan ve kısayolla çalışır; A2L/DBC sınırı ya da READ_ONLY onu engellemez.
  Düğme kilitli kalır; **2. basışta onay sorulur**, onaylanırsa Acil Durdurma sinyali **0'a çekilir** ve kilit açılır
  (Motor Start otomatik gönderilmez). Onay verilmezse ya da 0 yazılamazsa kilitli kalır.
- Uzun CCP işleri (harita/flaş/toplu yazma) **arka plan iş parçacığında** yürür; acil yazmalar araya girer
  (`CCPClient.urgent()`). Arayüz iş parçacığında bloklayan CCP işi yazmayın.
- Her tablo yazımından önce ECU içeriği yedeklenir; yazma sonrası geri okuma doğrulanır, hata olursa geri yazılır.
- Flaş yazma **gerçek M220 donanımında doğrulanmamıştır**; yalnızca Yönetici rolü ve çift onayla açılır.
- CCP `GET_SEED`/`UNLOCK` altyapısı vardır (`CCPClient.unlock_resource`) ama ECU'ya özel anahtar algoritması
  bilinmediği için arayüze bağlı değildir.

## Bilinen sınırlar

- DAQ (olay tabanlı sürekli ölçüm) yok; değerler UPLOAD ile sorgulanır, değişken sayısı arttıkça tur süresi uzar.
- STD_AXIS / COM_AXIS eksenli tablolarda bellek yerleşimi doğrulanmadığı için yazma reddedilir.
- Gerçek PCAN/ECU ile uçtan uca doğrulama listesi: `offline_paket/README_WINDOWS.md` → "Donanım devreye alma kontrol listesi".
