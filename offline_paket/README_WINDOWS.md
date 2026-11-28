# OpenECU M220 Test & Kalibrasyon Aracı — Windows Kurulum ve Kullanım

Bu klasör, internete **hiç bağlanmadan** Windows'ta çalışan tek bir `.exe`
dosyası üretmeniz için gereken her şeyi içerir: uygulamanın kaynak kodu
(`app/`, `main.py`) ve kurulum/derleme betikleri. Gerekli Python
paketlerinin (`.whl`) toplam boyutu (~340 MB, özellikle PySide6) sohbet
üzerinden gönderilemeyecek kadar büyük olduğu için, onları **Adım 0**'da
kendiniz (tek komutla) indireceksiniz.

## Adım 0 — Paketleri indirme (İNTERNETLİ bir bilgisayarda)

İnternete bağlı herhangi bir bilgisayarda (Pardus/Linux geliştirme
makineniz de olur, ya da internetli bir Windows bilgisayar) bu klasörün
içinde:

- Linux/macOS: `bash 0_wheels_indir.sh`
- Windows: `0_wheels_indir.bat` dosyasına çift tıklayın

Bu, Windows (Python 3.11, win_amd64) için gereken TÜM paketleri **tam sabit
sürüm ve hash doğrulamasıyla** (`requirements.lock.txt`) indirip
`wheels\` klasörüne koyar — **Windows'ta çalıştırmanıza gerek yoktur**,
pip "başka bir platform için indirme" özelliğini destekler, bu yüzden
Pardus'taki geliştirme makinenizde de çalıştırabilirsiniz.

Bittikten sonra **bu klasörün tamamını** (artık `wheels\` de dolu) USB
bellekle internetsiz Windows bilgisayara taşıyın ve Adım 1'den devam edin.

## Gereksinimler

- Windows 10/11, internete bağlı **olmasına gerek yok**.
- Python 3.11 kurulu olmalı (python.org'dan indirip kurarken **"Add
  python.exe to PATH"** kutucuğunu işaretleyin). Bu adım için de
  internete ihtiyacınız varsa, kurulum dosyasını internetli bir
  bilgisayarda indirip USB ile taşıyabilirsiniz.
- Yönetici (Administrator) yetkisi **gerekmez** — hem `venv` kurulumu hem
  de PyInstaller derlemesi normal kullanıcı yetkisiyle çalışır.
- Gerçek donanımla test edecekseniz: PEAK-System PCAN-USB adaptörü ve
  onun sürücüsü (aşağıya bakın).

## Adım 1 — Kurulum

`wheels\` dolu haldeki bu klasörü internetsiz Windows bilgisayarda açıp
içine girin ve `1_kurulum.bat` dosyasına çift tıklayın. Bu betik:

1. `venv` adında yerel bir Python sanal ortamı oluşturur,
2. `wheels\` klasöründeki tüm paketleri **internete çıkmadan** kurar
   (`pip install --no-index --find-links wheels ...`),
3. kurulumun başarılı olduğunu doğrular.

Hata alırsanız ekrandaki mesaj ne eksik olduğunu söyler; pencere kapanmaz,
"pause" komutuyla açık kalır.

## Adım 2 — .exe oluşturma

`1_kurulum.bat` başarıyla bittikten sonra `2_exe_olustur.bat` dosyasına
çift tıklayın. Birkaç dakika sonra `dist\ECU_CAN_Arayuzu.exe` dosyası
oluşur. Bu **tek dosyayı** gerçek PCAN-USB donanımının takılı olduğu
internetsiz bilgisayara kopyalayıp doğrudan çalıştırabilirsiniz — başka
hiçbir dosyaya ihtiyaç duymaz.

> Neden iki ayrı adım (kurulum / exe oluşturma)? Çünkü PyInstaller
> Windows'ta çalışmalıdır (Linux'tan Windows .exe'si "cross-compile"
> edilemez) — bu yüzden geliştirme Linux'ta yapılsa da, paketleme
> mutlaka bir Windows makinesinde olur.

## Adım 3 — PCAN-USB sürücüsünü kurma (gerçek donanım için)

PCAN-USB adaptörünü kullanabilmek için PEAK-System'in kendi sürücüsü
Windows'a kurulu olmalı (bu, Python paketlerinden ayrı, donanım
sürücüsüdür — internetli bir bilgisayarda PEAK-System'in sitesinden
"PCAN-Basic" veya "PCAN Driver Setup" paketini indirip, kurulum
dosyasını USB ile internetsiz bilgisayara taşıyıp orada çalıştırın).
Sürücü kurulduktan sonra adaptörü takıp Aygıt Yöneticisi'nde
("PEAK PCAN-USB" gibi bir isimle) görünmesi yeterlidir.

## Adım 4 — Uygulamayı kullanma

`ECU_CAN_Arayuzu.exe` çalıştırıldığında **Modas tarzı tek ana pencere** (ribbon: Start / Label / Worksheets / Tools / Windows)
açılır; diğer sayfalar **Tools** sekmesinden (ya da `Ctrl+1…6`) bağımsız araç pencereleri olarak açılır:

| Sayfa | Ne işe yarar |
|---|---|
| **Worksheets** (ana pencere) | Etiket pencereleri (değer / harita), **Scope** (osiloskop), WP/RP sayfaları, Diff, Variable list, Log-Windows. A2L etiketleri burada okunur/yazılır; değişiklikler kırmızı ok ve fark ile görünür. **Osiloskop**: A2L etiketleri Değişken listesinden sürüklenir; DBC sinyali, gösterge, matematik sinyali (ölçekle / A ○ B / hareketli ortalama) ve CSV kaydı **Sinyaller… / ƒ Matematik / CSV** düğmeleriyle eklenir. |
| **Test Bench** (`Ctrl+2`) | **Motor Parametreleri** (RPM/İtki/PLA/Tt5/Fp Başl./Fp Ana/Ft/Ps2/Ps3 göstergeleri, sensör sağlığı, alt modlar), **Eyleyiciler** (manuel override: kilit + onay) ve MIL modunda Simulink model kontrol paneli. Motoru Başlat / Durdur / Acil Durdurma anahtarları ana şeritte. Çalışması için ⚙ Eşleşmeler'de DBC/A2L eşlemelerini bir kere girin. |
| **CAN Trace** (`Ctrl+3`) | Bağlantı (PCAN, baudrate), İzleme (gelen/giden CAN, DBC çözümü), Gönderim (manuel/periyodik, DBC yükleme), Kayıt. |
| **Calibration Tools** (`Ctrl+4`) | **CCP** (bağlantı, canlı değer okuma, RAM'e geçici yazma, **Yönetici rolüyle flaşa kalıcı yazma**) ve **Geçmiş** (RAM/FLAŞ yazımlarının eski/yeni değerleri, geri alma). A2L'nin ayrı sekmesi yok: Project Manager'daki workbase'den yüklenir. |
| **Control Panel** (`Ctrl+5`) | Genel ECU test girdisi: uçak girişleri, sensör/eyleyici override'ları, çıkış izleme (aşağıdaki bölüm). PLA / uçuş koşulları gibi girişler buradan gönderilir. |
| **Diagnostics** (`Ctrl+6`) | CCP bağlantı testi + DIAG_SERVICE, CAN sağlığı, test oturumu (kayıt, PDF/HTML rapor, Excel), kayıtlı oturumlar, tetikleyici ile otomatik kayıt, test senaryoları. |
| **⚙ Ayarlar** (komut şeridi) | Kullanıcı ismi (denetim kayıtları için; tek rol: Mühendis) ve profiller; ⚙ Eşleşmeler ayrı düğme. |

> Kaldırılan eski sayfalar: Analiz (Çalışma Alanı, Performans), Test Bench'teki Uçuş Koşulları / Motor Kontrol / Son Olaylar /
> Canlı Trendler kartları, Worksheets'teki Input pencereleri, Calibration Tools'taki A2L sekmesi. Karşılıkları: Scope, Control Panel,
> Log-Windows, Project Manager + Variable list.

### Eyleyici manuel override (MATLAB/Simulink donanım testi)

Ana Sayfa'daki her eyleyici (Yakıt Pompası Start/Fuel, Yakıt Debisi Valfi,
Glow Plug, Başlatma Motoru) için bir anahtar/komut kutusu vardır. Anahtar
**kapalıyken** değer değiştirmek CAN'a hiçbir şey göndermez. Anahtarı
**açtığınızda** (Mühendis/Yönetici rolü + onay diyaloğu gerekir) uygulama
"override enable=1 + komut değeri" mesajını gönderir — bu sinyali dış bir
MATLAB/Simulink modelindeki Switch bloğu okuyup o eyleyiciyi dışarıdan
sürebilir. Anahtarı kapatınca "enable=0" gönderilir ve model kendi iç
hesaplamasına döner. DBC mesaj/sinyal eşlemesi Ana Sayfa → Ayarlar'dan
girilir (bkz. aşağıdaki bölüm).

### Test Bench: eşleşmeler ve anahtarlar

**Switch (`_sw`) yalnızca Eyleyicilerdedir.** Sensörlerde (Motor Parametreleri) switch eşlemesi ve manuel değer/kilit yoktur; eski `dashboard_config.json` içindeki bu `_sw`'ler yüklenirken temizlenir.

**Motor Komutları (Başlat / Durdur / Acil Durdurma)** ⚙ Eşleşmeler'de yalnızca **Komut** (CAN `MESAJ.SİNYAL` ya da A2L değişken) alır; **Değer ve Switch yoktur**. Düğmeye basınca eşlenen sinyale doğrudan **1** yazılır (tek sinyallik, tek seferlik darbe). Komutlar kilitsizdir ve onay sormaz (Acil Durdurma her zaman basılabilir). Eski kayıttaki değer/switch yok sayılır.

### Kontrol Paneli (Simulink/MATLAB tabanlı ECU testi)

Sol menüde **Kontrol Paneli**: uçak girişlerini, sensör override'larını, çıkışları ve iç sinyalleri TEK sayfada toplar.

1. **CAN Trace → DBC yükle** ve Project Manager'da workbase'e A2L dosyasını tanımlayıp açın. Sinyal kataloğu bu dosyalardan otomatik çıkar (CSV gerekmez).
2. Sınıflandırma: DBC mesajının göndericisi `AIRCRAFT / UCAK / TESTER / HOST` ise **Uçak girişi** (GUI'den periyodik gönderilir; bir mesajın tüm sinyalleri TEK karede gider). Diğer DBC mesajları **Çıkış**. A2L'de `<İsim>_Ovr_Val` + `<İsim>_Ovr_En` çifti **Sensör girişi** (önce değer, sonra bayrak CCP ile yazılır; "ECU'nun gördüğü" = A2L'deki `<İsim>` ölçümü). Diğer A2L ölçümleri **Çıkış**; istenirse İç sinyal yapılır.
3. **+ Sinyal kataloğu** ile ağaçtan işaretleyip **Panele ekle**. Görünümler, çalışma listesi ve senaryolar `kontrol_paneli.json` içinde saklanır.
4. Değerleri yazın (sarı = bekliyor), **Uygula (N)** ile hepsini birlikte gönderin. Aralık dışı değer onay sorar. **Bekleyenleri geri al**, **Tüm override'ları kapat** ve **Gönderimi durdur/başlat** düğmeleri vardır.
5. DBC/A2L dosyası diskte değişirse "Yeniden yükle" çıkar; fark özeti gösterilir. Dosyada artık olmayan sinyaller kırmızı "bulunamadı" olarak kalır.
6. Gönderim için Mühendis/Yönetici rolü gerekir (Operatör kilitli). CAN koparsa gönderim durur ve override durumu "bilinmiyor" görünür.
7. Not: Periyodik uçak girişi kareleri CAN Monitor listesinde gösterilmez.

### Ana Sayfa'yı çalıştırmak için: Ayarlar (bir kerelik kurulum)

Ana Sayfa'daki "Ayarlar" panelinden şunları girip **Ayarları Kaydet**'e basın
(bir dosyaya — `dashboard_config.json` — kaydedilir, bir daha sormaz):

- **Motor Start / Motor Stop / Acil Stop**: DBC'nizdeki mesaj adı, sinyal adı
  ve gönderilecek değer (örn. mesaj `ENGINE_CMD`, sinyal `Start_Req`, değer `1`).
  Motor komutları, Gönderim sekmesinde yüklediğiniz DBC dosyasını kullanır —
  önce orada DBC'yi yükleyin.
- **RPM, İtki, PLA, Tt5, Başlangıç Yakıt Basıncı (FPs), Ana Yakıt Basıncı (FPm), FT, Ps2, Ps3** ve Ortam Koşulları (Batarya
  Gerilimi, Ortam Basıncı, Atmosferik Sıcaklık, Tt0): gerçek A2L
  dosyanızdaki tam Measurement adı (örn. Tt2 için A2L'de `T_T2_degC` gibi
  farklı bir isim kayıtlı olabilir).
- **Eyleyiciler** (Yakıt Pompası Start/Fuel, Yakıt Debisi Valfi, Glow Plug,
  Başlatma Motoru): her biri için DBC mesaj adı + "override enable"
  sinyal adı + "komut değeri" sinyal adı (bkz. bir önceki bölüm).

### Flaş (kalıcı) yazma hakkında önemli uyarı

CCP'nin PROGRAM/PROGRAM_6/CLEAR_MEMORY komut dizilimi ASAM CCP 2.1
spesifikasyonuna göre uygulanmış ve bir yazılım simülatörüyle uçtan uca
doğrulanmıştır — ANCAK **M220 ECU'sunun gerçek flaş programlama akışı bu
uygulamada donanımla doğrulanmamıştır**. Bu yüzden:

- Kalibrasyon (CCP) sekmesinde flaş yazma varsayılan olarak **kapalıdır**;
  "Deneysel flaş yazmayı etkinleştir" kutusunu işaretleyip güçlü bir onay
  diyaloğunu geçmeniz gerekir.
- Flaşa yazmak/geri almak yalnızca **Yönetici** rolüyle mümkündür (sağ üstteki
  ⚙ Ayarlar penceresinden rol seçin).
- Her flaş yazımından önceki değer Kalibrasyon Geçmişi'ne **diske kalıcı**
  olarak kaydedilir; "eski haline getir" uygulama kapanıp açılsa bile
  çalışır (geri alma = eski değeri tekrar flaşa yazmaktır).
- Gerçek donanımda ilk denemenizi önce test ortamında (yedek bir ECU ya da
  düşük riskli bir parametreyle) yapmanız önerilir.

### Ana Sayfa (tek ekran, sidebar'sız)

- Sol: **Eyleyiciler** (kilitli, değer + `_sw`, CAN/A2L). Sağ: **Motor Parametreleri** (göstergeler) ve MIL modunda model kontrol paneli.
- **⚙ Eşleşmeler**: sensör, eyleyici, motor komutu ve giriş sinyalleri. Eyleyicilerde **Değer** ve
  **Anahtar (`_sw`)** eşleşmesi ayrı ayrı **CAN (DBC) ya da A2L** seçilir; sensörlerde yalnızca **Değer** (+ isteğe bağlı
  *Arıza* biti), Motoru Başlat / Durdur / Acil Durdurma'da yalnızca **Komut**
  eşlenir (switch yalnızca Eyleyicilerdedir). Eski `dashboard_config.json` otomatik göç eder.
- **Arayüz uzun işlemlerde donmaz:** harita/tablo, flaş ve toplu parametre yazmaları arka plan iş
  parçacığında yürür (durum çubuğunda "⏳ … yazılıyor"; o sırada Kalibrasyon ve Kontrol Paneli sayfaları
  geçici kilitlenir, ikinci bir uzun iş başlatılamaz, pencere kapatılamaz). Acil Durdurma, eyleyici ve
  override kapatma yazmaları süren işin parçaları arasına ÖNCELİKLE girer. Kontrol Paneli / Ana Sayfa
  periyodik CAN gönderimi de ayrı iş parçacıklarındadır: arayüz takılsa bile kareler kesilmez. Gönderilen
  TÜM kareler (periyodik olanlar dahil) CAN Monitor'da ve CSV kaydında TX olarak görünür.
- **Acil Durdurma 1. basışta ONAY SORMAZ** (kilitli kalır; 2. basışta (OFF) onay SORULMAZ, sinyal doğrudan 0'a çekilir, Motor
  Start otomatik gitmez): tek tıkla ya da **`Ctrl+Shift+E`** ile (hangi sayfa açık olursa olsun, odak bir
  giriş kutusunda bile) gönderilir. `Ctrl+1` … `Ctrl+6` sayfalar arasında geçer. Ana düğmelerin ve durum
  göstergelerinin ekran okuyucu adları vardır.
- **Worksheets'te değer yazma:** Değer penceresine yazıp **Enter** ile RAM'e yazılır. Bunun için rolün
  **Mühendis veya Yönetici** olması gerekir (sağ üstteki ⚙ Ayarlar > rol). **Operatör** rolünde değer pencereleri
  kilitlidir ve ipucu satırı nedenini söyler; değerler yine canlı izlenir.
- **Tablo yedeğinden geri yükleme:** Worksheets'te tablo penceresine sağ tık > **Yedekten Yükle…** tablonun, ECU'ya yazılmadan
  önce otomatik alınmış yedeklerinden birini hücrelere getirir (aynı nesne, adres ve boyut doğrulanır). ECU'ya
  YAZILMAZ; Enter / Write data to ECU ile ayrıca yazarsınız. Seçili hücreleri ECU'daki değere döndürmek için Ctrl+R.
- **Windows zamanlayıcı çözünürlüğü:** uygulama açılışta sistem zamanlayıcısını 1 ms'ye çeker; 10 ms'lik
  periyodik gönderim ~15,6 ms'e yuvarlanmaz. (Gerçek PCAN ile ölçülüp doğrulanmalıdır.)
- **CCP koruma (GET_SEED / UNLOCK):** `CCPClient.get_seed`, `unlock`, `unlock_resource(kaynak, anahtar_fonksiyonu)`
  hazırdır; ECU'ya özel seed-key algoritması bilinmediği için arayüze bağlı değildir.
- **Hatalar sessizce yutulmaz:** kapanış/temizlik dışındaki tüm `except` bloklarında hata `openecu.log`'a yazılır
  (CAN kayıt kancası, bus yeniden açma geri çağrıları, periyodik gönderim durdurma vb.).
- **Acil Durdurma ve Motoru Durdur güvenlik komutlarıdır:** (Acil Durdurma için) eşleme yoksa düğmenin yanında kalıcı "⚠ Acil Durdurma
  eşlenmemiş" uyarısı görünür ve basınca komut GİTMEDİĞİ açıkça bildirilir. Eşleme varsa A2L min/max,
  READ_ONLY ve DBC min/max denetimi komutu ENGELLEMEZ (sınır dışıysa olay günlüğüne not düşülür);
  değer veri tipine / sinyalin bit genişliğine sığmıyorsa yine gönderilmez ve HATA olarak günlüğe yazılır.
  Güvenlik komutları (Acil Durdurma, Motoru Durdur) CAN'da ilk kareden sonra AYNI kareyi 20 ms aralıkla
  4 kez daha yollar (toplam 5; arayüzü bloklamaz, olay günlüğüne yazılır); A2L/CCP'de iletişim hatasında
  en çok 3 kez yeniden yazar. Yazma sonrası geri OKUMA doğrulaması bilerek yoktur: komut bayrağını ECU modeli
  tüketip sıfırlayabilir, bu yüzden uyuşmazlık başarısızlık sayılmaz.
  Aynı sınır muafiyeti Motoru Durdur için de geçerlidir; Motoru Başlat ve eyleyici yazımlarında sınır
  denetimi aynen geçerlidir. Bu davranış otomatik
  testlerle yazılım düzeyinde sınanmıştır; gerçek ECU'da motoru durdurduğu donanımda ayrıca doğrulanmalıdır.
- **Kilit (`_sw`, yalnızca Eyleyiciler)**: kilitli (anahtar=0) iken değer değiştirilemez. Kilit açılınca (Mühendis/Yönetici
  + onay) önce değer, sonra `<ad>_sw = 1` yazılır; tekrar kilitleyince `<ad>_sw = 0`.
- Gösterge değer göstermiyorsa nedeni kartın altında yazar (CCP bağlı değil, ECU adresi yok, ECU
  cevap vermedi…); fare ile üzerine gelince kaynak/ham/fiziksel değer görünür. A2L'deki
  `MOD_COMMON BYTE_ORDER` artık okunur (küçük-endian ECU'larda değerler eskiden bozuk çıkıyordu).
- Testler: `python -m pytest tests` (Windows için `1_kurulum` sonrası venv içinde).

### CAN Monitor (canlı kullanım)

- Arayüz/backend ve kanal seçimi yoktur: bağlantı **PCAN-USB** (`PCAN_USBBUS1`) üzerinden kurulur;
  birden fazla adaptör takılıysa yalnızca o zaman küçük bir adaptör seçici görünür. Baudrate ve
  "açılışta otomatik bağlan" seçimi hatırlanır. Donanımsız geliştirme için ortam değişkeni:
  `OPENECU_CAN_INTERFACE=virtual` (veya `udp_multicast`).
- Sol **İzleme** kartı: her (yön, ID) için bir satır, ID başına ölçülen **periyot (ms)**, DBC mesaj adı ve
  birimli sinyaller, canlı filtreler, hex/ondalık, değişen verinin vurgulanması, seçili mesajın sinyal/ham
  değer paneli. Başlıkta **DBC Yükle** ve **Kayıt** (CSV: RX + TX, yön ve mesaj adıyla).
- Sağ **Gönderim** kartı: *Manuel* ve *Periyodik* sekmeleri. DBC modunda girilmeyen sinyaller önceden
  uyarı olarak gösterilir; çalışan periyodik satırın sinyal değerleri değişince gönderim güncellenir.

### ECU gücü kesilip gelince (güvenilirlik)

- **CAN:** PCAN bus'ı sürücü `auto_reset` ile açılır. Hat bus-off/ağır hatada ve sessizse bekçi `reset()`
  dener, olmazsa adaptörü aynı ayarlarla yeniden açar; toparlanırken gönderim saniyede 1 kareye iner.
  Bağlantı şeridinde "Hat sessiz / kurtarılıyor" yazar; PCAN durum kodu geçişleri olay günlüğüne
  (BAGLANTI) zamanıyla yazılır — gerçek donanımda sorun olursa buradan teşhis edilir.
- **Periyodik gönderimler** (Kontrol Paneli, uçuş/motor girişleri, Gönderim sekmesi) hata alınca durmaz;
  hat/ECU dönünce kendiliğinden sürer.
- **CCP:** tüm CCP okumaları arka plan iş parçacığında yapılır; arayüz hiçbir zaman beklemez. Durum:
  bağlı değil → bağlanıyor → çevrimiçi → **ECU YOK** → (her saniye yeniden CONNECT) → çevrimiçi. ECU
  güç döngüsünden sonra CCP oturumu otomatik yeniden kurulur. Otomatik bağlanma, ECU hazır olana kadar
  geri çekilmeli olarak (0,5 → 5 sn) sürekli dener. Durum üst şeritteki çipte ve CCP/Kalibrasyon
  sekmelerinde görünür.
- **Worksheets > değer penceresi:** değer yazıp **Enter** yazar (Esc iptal), yazılan değer ECU'dan geri okunup doğrulanır. Ölçüm
  (MEASUREMENT) etiketleri gri ve salt okunurdur. Değer yazmak için **Mühendis veya Yönetici** rolü gerekir:
- **RAM'e yazma onay sormaz**; yalnızca FLAŞ (kalıcı) yazma onay ister.
- **Bağlantı izleme**: adaptör çekilirse ~3 sn teyit edilir, "Bağlantı KOPTU" gösterilir,
  adaptör geri gelince otomatik yeniden bağlanır (CCP de devam eder).
- **Kalibrasyon**: Worksheets (Modas Sport tarzı; eğri/harita/dizi her biri kendi iç penceresinde, 1×16 gibi diziler dahil).
- **Duyarlı arayüz**: sayfalar kaydırılabilir, pencere ekrana sığacak şekilde açılır,
  göstergeler orantılı ölçeklenir.
- **Kalıcı dosyalar** sabit kullanıcı klasöründe: Belgelerim\OpenECU_M220_Veri (exe nereden açılırsa açılsın aynı; eski exe-yanı dosyalar ilk açılışta oraya kopyalanır):
  `audit_log.txt` (5 MB'ı aşınca `.1` yedeği), `calibration_history.json` (son 5000 yazım),
  `profiles.json`, `dashboard_config.json`, `modas_worksheets.json`, `modas_templates.json`, `kontrol_paneli.json`,
  `openecu.log` (hata günlüğü); CAN kayıtları `can_loglari\`, tablo yazım yedekleri
  `tablo_yedekleri\`. Her JSON için bir `.bak` yedeği tutulur; bozulan dosya `*.corrupt-<zaman>` olarak saklanır.
- **Simge**: `app_icon.ico` (exe'ye `--icon` ile gömülür).
- **Tablolar (Worksheets)**: Modas Sport tarzı tablo penceresi (X üstte, Y solda, köşede Y\X, hücrelerde Z).

## Scope (osiloskop) — Worksheets
**Label → Scope** (ya da Variable list'te etiket seçip Scope) yeni bir osiloskop penceresi açar. Aynı grafikte:
- **A2L etiketleri:** Variable list'ten sürükleyip bırakın; veri **F9 (Measurement)** ile akar.
- **Sinyaller…:** DBC sinyalleri (CAN'den çözülür), göstergeler ve matematik / CSV sinyalleri. Yalnızca grafikte olan DBC sinyalleri çözülür.
- **ƒ Matematik:** ölçekle (a·x+b), A+B / A−B / A×B / A÷B (örn. P3/P2), hareketli ortalama; düzenle / sil. Tanımlar Worksheets kaydıyla birlikte saklanır (`modas_worksheets.json`).
- **CSV:** *Kayıt aç* eski bir oturum kaydını salt okunur sinyaller olarak çizer (yeni kayıtla üst üste karşılaştırma); *Canlı kaydı CSV'ye aktar*.
- **Hold:** grafiği dondurur (veri arka planda sürer); **Span** zaman penceresi; **Çizim** üst üste / ayrı ayrı; **İmleçler (A/B)** Δ / ortalama / min / maks; sinyal başına renk-kalınlık tablosu.
- Düzen (pencereler, Scope sinyalleri, matematik tanımları) **Worksheets** ile saklanır: **F12** ya da Workfolder › Save; **Tile / Cascade** ile düzenlenir.
- Kaldırıldı: Çalışma Alanı'nın gösterge/tablo panelleri ve "Paneli ayır" (ayrı pencere); Test Bench göstergeleri ve Worksheets değer pencereleri aynı işi görür.

## Güvenli yazma ve kararlılık notları
- **Yazma doğrulaması:** Her kalibrasyon yazımı önce doğrulanır (sonlu sayı, veri tipi aralığı, A2L alt/üst sınırı, READ_ONLY) ve yazdıktan sonra ECU'dan geri okunup karşılaştırılır. Dönüşüm (COMPU_METHOD) çevrilemiyorsa hiçbir şey yazılmaz.
- **Tablo (harita) yazımı:** Önce ECU'daki mevcut içerik okunur ve `tablo_yedekleri/` klasörüne JSON olarak yedeklenir; yazma ya da doğrulama başarısız olursa eski içerik geri yazılır. FIX_AXIS dışındaki eksen türlerinde (STD/COM/RES/CURVE_AXIS) bellek yerleşimi doğrulanmadığından **yazma reddedilir** (okuma serbest).
- **CCP yeniden deneme:** Bellek işaretçisini ilerleten komutlar (DNLOAD/UPLOAD/PROGRAM) cevap kaybolsa bile tekrar gönderilmez; okuma SHORT_UP ile yapılır ve güvenle tekrarlanır.
- **ECU susarsa:** CCP okumaları arka planda yapılır; ECU yanıt vermezse arayüz donmaz ve CAN'a giden periyodik giriş çerçeveleri durmaz. Okumalar birkaç saniye duraklatılır, durum çubuğunda belirtilir.
- **Override'lar:** Bağlantı kapanırken ECU'da açık kalan eyleyici override'ları bırakılmaya çalışılır; bırakılamazsa HATA olarak loglanır ve arayüz "Bilinmiyor" gösterir. "Tüm override'ları kapat" hiçbir rol gerektirmez.
- **Rol yükseltme** onay ister; profil kaydetme/silme rol gerektirir ve üzerine yazma/silme onaylanır. (Roller kimlik doğrulama değil, kaza önleme amaçlıdır.)
- **Kayıt dayanıklılığı:** Tüm ayar/geçmiş/yerleşim dosyaları atomik yazılır (önce geçici dosya, sonra yer değiştirme) ve her kayıtta bir `.bak` yedeği tutulur. Bozuk bir dosya açılışı engellemez: `*.corrupt-<zaman>` adıyla **saklanır** (sonraki kayıt onu ezmez), son iyi yedek (`.bak`) kullanılır. Tek bozuk kayıt/profil/panel atlanır, geri kalanı yüklenir. Yazılamayan kayıtlar loglanır ve ilgili ekranda uyarı verilir.
- **Denetim günlüğü:** Satır sonu/sekme içeren metinlerle sahte kayıt oluşturulamaz; yazma hatası sayılır ve loglanır.
- **Gönderim sekmesi:** Çerçeve göndermek ve periyodik gönderim başlatmak Mühendis/Yönetici rolü ister; her gönderim, başlatma ve durdurma denetim günlüğüne (`GÖNDERİM`) yazılır. Ham modda DLC (0-8) seçilebilir, çakışan bit alanları reddedilir, 5 ms'den kısa periyot onay ister. Reddedilen/başarısız bir periyodik satır "çalışıyor" görünmez. Satır silmek diğer satırların onay kutularını karıştırmaz.
- **DBC:** Aralık dışı değer artık sessizce kaybolmaz, anlaşılır hata verir. Girilmeyen sinyaller en küçük değerle değil DBC başlangıç değeri (yoksa 0, aralığa kırpılmış) ile gider. Fare tekerleği odakta olmayan sayı kutusu/kaydırıcıyı değiştirmez.
- **CAN kaydı:** Aynı saniyede başlatılsa da dosya ezilmez, her 200 satırda diske işlenir, disk hatasında kayıt durur ve uyarı verilir.
- **Günlük:** Beklenmeyen hatalar `openecu.log` dosyasına yazılır ve ekranda gösterilir. Aynı veri klasörünü iki program kopyası birlikte kullanamaz.
- **Testler:** kurulumdan sonra `3_testleri_calistir.bat` (internetsiz, `venv` içinde `pytest`). `2_exe_olustur.bat` exe'den önce testleri de çalıştırır; başarısızsa uyarır.
- **Sabit sürümler:** `requirements.lock.txt` tüm bağımlılıkları sürüm + sha256 ile sabitler (kurulum `--require-hashes` ile yapılır), böylece yeniden derleme farklı bir kütüphane sürümü getirmez. Sürüm güncellemek için lock dosyası yeniden üretilmeli ve testler çalıştırılmalıdır.
- **PDF rapor:** Türkçe karakter için DejaVu Sans yazı tipi `app\fonts\` içinde pakete gömülüdür (yoksa Windows Arial denenir). Rapor yalnızca oturumun başlangıç–bitiş aralığındaki olayları içerir; oturum başlatılmadan rapor üretilmez.

## Sorun giderme: .bat dosyasına çift tıklayınca bir şey olmuyorsa
- Dosyayı zip'ten **çıkarıp** klasör olarak açtıktan sonra çalıştırın (zip içinden çalışmaz).
- Pencere hemen kapanıyorsa Başlat menüsünden "cmd" açıp klasöre gidin ve dosya adını yazıp Enter'a basın; hata ekranda kalır.
- "Python 3.11 (64 bit) bulunamadı" uyarısı çıkarsa python.org'dan **Python 3.11 (64 bit)** kurun; başka sürümlerle (3.12/3.13…) kurulum bilinçli olarak durdurulur çünkü paketler cp311 içindir. Microsoft Store kısayolu işe yaramaz.
- .bat dosyasına çift tıklayınca **Not Defteri açılıyorsa** (dosya ilişkilendirmesi bozuk): aynı klasördeki **.cmd** dosyasına çift tıklayın (`0_wheels_indir.cmd`, `1_kurulum.cmd`, `2_exe_olustur.cmd`, `3_testleri_calistir.cmd`) — bunlar aynı klasördeki `.bat` dosyasını çağıran küçük sarmalayıcılardır. Dosya adının sonunda gizli bir `.txt` olmadığını da kontrol edin (Gezgin → Görünüm → "Dosya adı uzantıları").

## Yenilikler (21 Ekim 2026)
- Uygulama simgesi turbojet motoru oldu (`app_icon.ico`, kodla çizilir).
- Ana Sayfa'da sensör sağlığı ince bir şerit: yalnızca arızalı sensörler listelenir ("Arıza yok" / "N arıza").
- Eyleyiciler: her kartta CAN | A2L kanal seçici. CAN = DBC mesajı; A2L = CCP ile değişken yazımı
  (⚙ Eşlemeler'de A2L enable / değer değişkenleri girilir). Seçim kalıcıdır.

## Donanım devreye alma kontrol listesi (M220)
Aşağıdakiler yazılımın otomatik testleriyle **kanıtlanamaz**; gerçek ECU ile ilk kullanımda elle denenmelidir
(yazılım bu maddelerin ECU'da nasıl davranacağını bilmez, sonuçları not edin):
1. **Acil Durdurma / Motoru Durdur:** Motor çalışırken basın; motor durdu mu, ne kadar sürede? Komut ECU'da
   **mandallanıyor mu**, yoksa kare akışı kesilince varsayılana mı dönüyor (CAN alım zaman aşımı)? Sonucuna
   göre komutun sürekli tutulması gerekebilir (yazılım şimdilik 5 kare gönderir, sonra bırakır).
2. **Sınır dışı komut değeri:** Acil Durdurma/Durdur için yapılandırılan değer A2L/DBC sınırının dışındaysa
   yazılım yine gönderir (olay günlüğünde "sınır denetimi atlandı" notu görünür); ECU'nun bu değere tepkisini doğrulayın.
3. **Eyleyici / sensör override:** Ana Sayfa'dan ve Kontrol Paneli'nden AYNI CAN mesajına yazın; override
   anahtarı ECU'da açık kalıyor mu? (Ana Sayfa ve Kontrol Paneli artık tek değer tablosunu paylaşır ve mesaj
   periyodik gönderilir; ECU'nun periyodik değeri beklediğini doğrulayın.)
4. **Bus-off ve kopma:** Hattı/kabloyu çıkarıp takın; yazılımın toparlanması ve sonrasında komutların
   gönderilmesi (README "Doğrulanmayanlar": PCAN bus-off davranışı ve ECU açılış süresi donanımda doğrulanmadı).
5. **Test Bench kadranları:** Gerçek veriyle iğne, değer ve etiketler okunuyor mu?
6. **Eşleşmeler:** Acil Durdurma dahil tüm motor komutları ⚙ Eşleşmeler'de tanımlı mı? (Tanımsızsa komut
   şeridinde "⚠ Acil Durdurma eşlenmemiş" görünür.)

## Oturum parametre kaydı (CSV)
**Tanılama ve Oturum → Oturumu Başlat** ile birlikte izlenen parametrelerin değerleri diske sürekli yazılır; böylece oturum bittikten (program kapandıktan/çöktükten sonra bile) incelenebilir.
- **Dosya:** veri klasöründe `oturum_kayitlari\<test_ismi>_<tarih_saat>.csv`. Her oturum yeni dosya açar, eskisinin üzerine yazılmaz. Yol oturum kartında ve olay günlüğünde (OTURUM) görünür.
- **Kayıt ilkesi — her veri kendi geliş zamanında ve kendi periyoduyla yazılır** (arayüz zamanlayıcısına bağlı örnekleme yoktur, veri kaybolmaz):
  - **CAN (`dbc:<MESAJ>.<SİNYAL>`):** DBC'deki **tüm** mesajların **her gelişinde**, mesajdaki tüm sinyaller, karenin gerçek geliş zamanıyla yazılır; ekranda kullanılmayan sinyaller de dahil. 10 ms'de bir gelen mesaj 10 ms'de bir, 100 sn'de bir gelen 100 sn'de bir satır üretir. Aynı değer tekrar gelse de her geliş bir satırdır. Ayrı bir iş parçacığında yazılır; kuyruk dolarsa düşen kare sayısı olay günlüğüne HATA olarak yazılır.
  - **A2L/CCP (`a2l:<ölçüm>`):** CCP iş parçacığı her okumada değeri izler; **değer değiştiğinde** okuma zamanıyla bir satır yazılır (başlangıç değeri dahil). ECU'daki bir değişken 10 sn'de bir güncelleniyorsa 10 sn'de bir satır oluşur; değişmeyen değer tekrar tekrar yazılmaz (Excel'in **Geniş tablo** sayfası son değeri korur). Yalnızca arayüzde izlenen (gösterge, Worksheets, Scope, Kontrol Paneli...) değişkenler okunduğu için yalnızca onlar kaydolur.
  - **Kullanıcı girişleri (`input:<anahtar>`):** girildikleri anda. Ana Sayfa göstergeleri ayrıca yazılmaz; değerleri kaynak kimlikleriyle (`a2l:`/`dbc:`) zaten kayıttadır.
- **Biçim:** `time,signal,value,unix_time` (time = oturum başından saniye; unix_time = mutlak zaman). Excel'de açılabilir.
- **Geri açma:** Worksheets › Scope › **CSV › Kayıt aç** ile kayıt yüklenip grafikte çizilir, yeni bir kayıtla üst üste karşılaştırılabilir.
- Veri saniyede bir diske işlenir (çökmede en çok ~1 sn kaybolur). Oturum boyunca girişleriniz de ayrıca `<oturum>_girisler.csv` dosyasına satır satır yazılır. Disk hatasında kayıt durur ve olay günlüğüne HATA yazılır. Oturum başlatılmadıkça kayıt yapılmaz.

## Kayıtlar ve Excel (.xlsx) — testlerden sonra inceleme

Tüm kayıtlar **yalnızca bilgisayara** yazılır; ECU'ya (RAM ya da flaş) hiçbir şey gönderilmez. ECU'ya yazma
yalnızca sizin açıkça başlattığınız kalibrasyon işlemleridir (RAM'e Yaz / Kalıcı Kaydet / Harita yazma).

| Kayıt | Ne zaman | Dosya (`<veri klasörü>` = Belgelerim\OpenECU_M220_Veri) |
|---|---|---|
| **Oturum Excel dosyası** | *Tanılama ve Oturum* > **Oturumu Bitir** (otomatik) | `<veri klasörü>\oturum_kayitlari\<oturum>_<tarih>.xlsx` (+ aynı adlı `.csv`) |
| **CAN kaydı Excel dosyası** | CAN Monitor > **■ Kaydı durdur** (otomatik; ⚙ menüsünden kapatılabilir) | `<veri klasörü>\can_loglari\can_log_<tarih>.xlsx` (+ `.csv`) |
| **Elle Excel'e aktar** | *Tanılama ve Oturum* > **Excel'e Aktar** | seçtiğiniz klasör |

Oturum Excel dosyasının sayfaları:
**Özet** (oturum adı, operatör, süre, olay / hata sayıları, **sayfa başına giriş sayıları**, RAM ve FLAŞ yazım sayıları) ·
**Girişler (tüm sayfalar)** — hangi sayfada ne yaptıysanız hepsi: Ana Sayfa (eyleyici değeri, switch, motor komutu,
uçuş koşulu), Kontrol Paneli, Kalibrasyon (Worksheets değer / tabloları, CCP, geri alma); tarih/saat, sayfa,
tür, hedef (sinyal/parametre), eski ve yeni değer, **başarılı mı / başarısız mı** (reddedilen denemeler dahil),
kullanıcı, rol · **Kalibrasyon yazımları** (RAM / FLAŞ, eski ve yeni değer) · **Olay günlüğü** · **Sinyal özeti**
(her sinyalin örnek sayısı, ilk/son, min/maks/ortalama) · **Parametre kaydı** (her değer kendi geliş zamanıyla:
tarih/saat, süre, sinyal, değer) · **Geniş tablo** (1 sn'de bir satır, sinyaller sütun; son değer korunur: Excel'de
tek zaman ekseniyle doğrudan grafik çizilir).

Notlar:
- Kayıt **oturum boyunca CSV'ye sürekli** yazılır (program çökse bile veri kaybolmaz); Excel dosyası kayıt bitince
  bu CSV'den üretilir. CSV silinmez. Excel üretilemezse (disk dolu, dosya Excel'de açık vb.) olay günlüğüne HATA
  yazılır ve veri CSV'de kalır.
- Çok büyük kayıtlar otomatik olarak "Sayfa (2)", "Sayfa (3)" sayfalarına bölünür (Excel'in 1.048.576 satır sınırı).
  500.000 örnek ~6 sn'de ve ~20 MB bellekle dönüşür.
- **Excel'de açıkken** aynı dosyanın üzerine yazılamaz (Windows kilidi); önce kapatın.
- Excel dosyası uygulamanın kendi yazıcısıyla üretilir (ek paket gerekmez, internetsiz kurulumu bozmaz).

## Geliştirici notları: kod yapısı, testler ve CI

- **Ana pencere parçalara bölündü.** `app/ui/main_window.py` yalnızca pencere çatısını, sayfaları, sinyal
  bağlantılarını ve kapanışı içerir. İş mantığı `app/ui/mainwin/` altındadır: `connection.py` (CAN bağlantısı,
  sağlık izleme, alım/gönderim), `calibration.py` (CCP oturumu, arka plan CCP işleri, harita / Parametre
  Listesi / tanılama / geri alma), `dashboard.py` (eşleşme yazımı, motor komutları, göstergeler),
  `panel.py` (Kontrol Paneli), `profiles.py` (rol ve profiller), `common.py` (sabitler).
- **Renkler tek yerden:** `app/theme.py` içindeki token'lar (`theme.DANGER`, `theme.OK`, `theme.ACCENT`…).
  Arayüz kodunda yeni renk sabiti yazmayın; token kullanın. Süslü parantezli stil metinlerinde
  `theme.paint("... color: @@DANGER@@; ...")` yer tutucusu kullanılır (bir test token'ı olan renklerin elle
  yazılmasını engeller). Yalnızca satıra özgü tek seferlik tonlar (grafik serileri, satır vurguları) koddadır. Kalibrasyon sayfasının tüm iç sekmeleri artık
  diğer sayfalarla aynı kart görünümünü kullanır.
- **A2L arka planda yüklenir** (`A2LTab.load_path`): arayüz donmaz, ilerleme penceresi görünür. Ayrıştırma
  ilişkileri toplu (eager) yüklediği için 6.000 nesnelik dosya ~17 sn yerine ~3,5 sn'de açılır; SQLite oturumu
  ayrıştıran iş parçacığında kapatılır ve bellekte tutulmaz.
- **Testler:** `python -m pytest tests -q` (Windows'ta `3_testleri_calistir.bat`). Her testten sonra açık
  pencereler kapatılır, zamanlayıcıları durdurulur ve çöp toplanır (`tests/conftest.py`); testler birbirini
  etkilemez. Test sürecinin çıkışındaki PySide kapanış çökmesi (yüzlerce pencere birikince) testlerin sonucunu
  bozmaz: süreç, testlerin çıkış koduyla sonlandırılır (gerçek uygulama etkilenmez, temiz kapanır).
  Hızlı koşu için `pip install pytest-xdist` ve `pytest tests -q -n auto`
  (CI böyle çalışır; testler paralel işlemlerde de güvenlidir).
- **Statik denetim:** `ruff check .` (ayar: `ruff.toml`; yalnızca gerçek hata kuralları).
- **CI:** `.github/workflows/testler.yml` her push ve pull request'te ruff + tüm testleri çalıştırır
  (Ubuntu, Python 3.11, ekransız Qt).


## Arayüz notları (2026-11-28)
- **Dil ve rol:** Arayüz tamamen Türkçedir. Tek rol vardır: **Mühendis** (Operatör/Yönetici yok; kimlik doğrulama yoktur). Riskli işlemler rol yerine açık onayla korunur (override kilidi + onay, flaş yazma için "Deneysel flaş yazmayı etkinleştir" kutusu + güçlü onay).
- **Durum çubuğu:** ECU durumu, ölçüm (F9), kayıt süresi, bus yükü, çalışma tabanı ve **bekleyen** (ECU'ya yazılmamış) değişiklik sayısı her zaman görünür. Bekleyen değişiklik varken ribbon altında sarı şerit çıkar: **ECU'ya yaz** / **Geri al** (geri al ECU'ya hiçbir şey göndermez).
- **Yeni pencereler** çalışma alanında çakışmayan ilk boş yere açılır (yer yoksa kademeli).
- **Harita penceresi:** sağ tık › **Isı haritası** hücreleri değerine göre renklendirir (yalnızca görünüm; bekleyen hücreler sarı kalır).
- **Gösterge penceresi:** Etiket › **Gösterge**, seçili ölçümler için ibreli gösterge açar; aralık A2L sınırından gelir, sınır yoksa görülen değerlere göre genişler.
