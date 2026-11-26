# OpenECU M220 — Test ve Kalibrasyon Aracı (ECU CAN Arayüzü)

PCAN-USB (ya da sanal hat) üzerinden bir ECU'yu izlemek, CAN çerçeveleri göndermek ve **CCP** ile
kalibre etmek için Windows masaüstü uygulaması (Python 3.11, PySide6). Kaynak kodun tamamı
[`offline_paket/`](offline_paket) klasöründedir; **internetsiz Windows bilgisayarda** tek `.exe` üretme
adımları [`offline_paket/README_WINDOWS.md`](offline_paket/README_WINDOWS.md) dosyasındadır.

## Neler yapar

Arayüz **Bosch Modas Sport** çalışma alanına benzer: üstte **Ribbon** (`Start / Label / Worksheets / Tools / Windows`),
ortada mavi zeminde sürüklenebilir iç pencereler, sağda **Variable list** (`F2`), altta **Log-Windows** (`F3`) ve
worksheet sekmeleri. Motor Başlat / Durdur / **Acil Durdurma** grubu Ribbon'un sağında HER sekmede görünür.

| Sayfa (Tools sekmesi / `Ctrl+1…7`) | İşlev |
|---|---|
| **Worksheets** (açılış) | Modas çalışma alanı: A2L etiketlerini Variable list'ten sürükleyip bırakın → *değer penceresi* (beyaz = ayarlanabilir kalibrasyon, gri = ölçüm) ya da *eğri/harita tablosu*; WP/RP, `Diff`, Measurement (`F9`), Recording (`Ctrl+F9`), Read/Write data |
| **Ana Sayfa** | Motor Başlat / Durdur / **Acil Durdurma** (`Ctrl+Shift+E`), göstergeler, canlı grafik, eyleyici override |
| **CAN Monitor** | Bağlantı, canlı izleme (DBC çözümlemeli), çerçeve gönderme, CSV kaydı |
| **Kalibrasyon** | A2L tarayıcı, CCP bağlantısı, Parametre Listesi, Harita Editörü (yedekten yükleme dahil), geçmiş |
| **Analiz** | Çalışma Alanı (çoklu sinyal grafiği, matematik sinyalleri), Performans |
| **Kontrol Paneli** | Uçak girişleri / sensör override değerleri, senaryolar |
| **Tanılama ve Oturum** | CCP testi, DIAG_SERVICE, olay günlüğü, oturum kaydı, PDF rapor, **Excel (.xlsx) kayıt dosyası** |

Sayfa geçişi: `Ctrl+1` … `Ctrl+7` (ya da Ribbon > Tools).

### Modas kısayolları

| Tuş | İşlev | Tuş | İşlev |
|---|---|---|---|
| `F2` | Variable list göster/gizle | `F9` / `Ctrl+F9` | Ölçüm / kayıt başlat-durdur |
| `F3` | Log penceresi göster/gizle | `F10` | Ribbon sekme harfleri (`S L W T I`) |
| `F5` | Listeyi yenile + ECU'dan oku | `F12` | Worksheet düzenini kaydet |
| `F7` | Proje yöneticisi | `F8` | WP ↔ RP gösterimi |
| `Ctrl+P/D/H/B`, `Ctrl+F` | Physical / Decimal / Hex / Binary, biçim döngüsü | `Ctrl+I` | Variable information |
| `M` / `N` | Seçili değeri artır / azalt | `*` `/` `+` `=` | Tabloda seçili hücreleri çarp / böl / ekle / ata |
| `Delete` | Etiketi görünümden kaldır | `Ctrl+Shift+E` | **Acil Durdurma** |

**WP / RP:** CCP istemcisinde `SELECT/COPY_CAL_PAGE` komutu yoktur ve Flaş yazma gerçek donanımda doğrulanmamıştır; bu
yüzden **WP** = ECU RAM'i (canlı, düzenlenebilir), **RP** = etiketlerin ilk okunan / `COPY WP▶RP` ile saklanan *yerel
referans görüntüsü*dür (salt okunur). `Diff: n` iki sayfa arasında farklı etiket sayısıdır; `COPY WP◀RP` referansı RAM'e
geri yazar (onaylı). **Write data to ECU** yalnızca RAM'e yazar; kalıcı (Flaş) yazma Kalibrasyon > CCP'de kalır.

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
    ui/mainwin/            bağlantı, kalibrasyon/CCP, Ana Sayfa, Kontrol Paneli, profiller, modas.py (Worksheets)
    ui/modas/              Modas arayüzü: ribbon, workspace (MDI + worksheet), windows, variable_list, pages (WP/RP)
    theme.py               TÜM renk token'ları (arayüzde renk sabiti yazmayın)
  tests/                   pytest (CCP simülatörü ve sanal CAN hattı ile; donanım gerektirmez)
```

## Güvenlik ilkeleri (değiştirirken korunmalı)

- **Acil Durdurma 1. basışta onay sormaz**, her sayfadan ve kısayolla çalışır; A2L/DBC sınırı ya da READ_ONLY onu engellemez.
  Düğme (toggle) kilitli kalır; **2. basışta (OFF) onay sorulmaz**, Acil Durdurma sinyali doğrudan **0'a çekilir** ve
  kilit açılır (Motor Start otomatik gönderilmez). 0 yazılamazsa kilitli kalır.
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
