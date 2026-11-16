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

`ECU_CAN_Arayuzu.exe` çalıştırıldığında sekmeler sırasıyla:

| Sekme | Ne işe yarar |
|---|---|
| **Ana Sayfa** | Annunciator lamba şeridi (RED STOP LAMP/MIL LAMP/vb.), Motor Komutları, 8 ibre göstergeli Motor Parametreleri (RPM/İtki/PLA/Tt5/FP/FT/Ps2/Tt2), Sensör Durumu ve Arıza Tablosu, gömülü canlı grafik, **Eyleyiciler** (manuel override anahtarları — MATLAB/Simulink ile donanım testi için). Aşağıdaki "Ayarlar" bölümüne bakın — bu sekmenin çalışması için DBC/A2L eşlemelerini bir kere girmeniz gerekir. |
| **CAN Monitor** | Bağlantı (arayüz/kanal/baudrate — arayüz seçimi "▸ Gelişmiş ayarlar" arkasında, varsayılan arayüz `virtual` — **gerçek test için `pcan` seçin**), İzleme (gelen/giden CAN trafiği), Gönderim (manuel/periyodik mesaj + DBC yükleme — Ana Sayfa'daki motor komutları ve eyleyici override'ları da aynı DBC'yi kullanır), Log (CAN trafiğini CSV'ye kaydetme) — tek sekmede birleşik |
| **Kalibrasyon** | İç sekmeler (5): **A2L** (A2L dosyası yükleyip Measurement/Characteristic nesnelerini gezme; kalibrasyonun ilk adımı), **CCP** (canlı değer okuma, RAM'e geçici yazma, **Yönetici rolüyle flaşa kalıcı yazma**), **Harita Editörü** (1D/2D kalibrasyon tabloları, geri al/yinele, ısı haritası), **Parametre Listesi** (adres/hex ile serbest satırlar, toplu yaz/oku), **Geçmiş** (RAM ve FLAŞ yazımlarının eski/yeni değerleri, geri alma — FLAŞ kaydı uygulama kapansa bile kalıcıdır) |
| **Tanılama ve Oturum** | CCP bağlantı testi + ham DIAG_SERVICE isteği, CAN bağlantı sağlığı, test oturumu (başlat/bitir, PDF test raporu) ve TEK olay günlüğü ("Tümü / Yalnız hatalar" süzgeci) — birleşik |
| **⚙ Ayarlar** (komut şeridi; sekme değil) | Rol seçimi (Operatör/Mühendis/Yönetici), bağlantı+CCP ayarlarını profil olarak kaydetme ve Eşleşmeler. "Rol: …" etiketine tıklayarak da açılır |

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

### Simülasyon Girişleri (Ana Sayfa) ve Performans sayfası

**Ana Sayfa → Uçuş Koşulları (sol panel):** Altitude (0–30 kft), Alfa/Beta (±90°) ve sabit değerler (Ma, Toplam Giriş Basıncı, Ortam Basıncı, Ortam Sıcaklığı). Değerler Enter/bırakma ile anında CAN'dan gönderilir; "Hepsini gönder" tümünü yollar. Girişler DBC sinyallerine bağlanır: panel ilk DBC yüklemesinde isimle otomatik eşler, olmayanlar ⚙ Eşleşmeler > Uçuş Koşulları'ndan seçilir. Gönderim için Mühendis/Yönetici rolü ve CAN bağlantısı gerekir. Kontrol Paneli ile aynı değer tablosunu paylaşır.

**Ana Sayfa → Motor Kontrol** (Çalıştırma/Start, Ateşleme/Spark, Gaz Kolu/PLA, Birincil Yakıt) **Eyleyiciler gibi çalışır:** her satırın **Değer** ve **Anahtar (`_sw`)** eşleşmesi ayrı ayrı **CAN (DBC) ya da A2L** seçilir (⚙ Eşleşmeler > Sinyaller > Motor Kontrol); satır **kilitli** açılır (Mühendis/Yönetici + ilk kullanımda onay). Eyleyicilerden tek fark: `_sw` burada **isteğe bağlıdır** (eşlenmemişse kilit yalnızca değeri açar, kilitlenince değer 0'a çekilir). Eski sürümde doğrudan gönderilen Start/Spark/Gaz Kolu/Yakıt eşleşmeleri ilk açılışta otomatik olarak yeni modele taşınır (yalnızca değer bağlaması; `_sw`'yi siz seçin).

**Motor Komutları (Başlat / Durdur / Acil Durdurma)** ⚙ Eşleşmeler'de **Komut** (CAN `MESAJ.SİNYAL` ya da A2L değişken) + **Değer** + isteğe bağlı **Anahtar (`_sw`)** alır. Düğmeye basınca önce değer, sonra `_sw = 1` yazılır; ikisi aynı CAN mesajındaysa tek karede gider. Komutlar kilitsizdir (Acil Durdurma her zaman basılabilir).

**Analiz → Performans:** Compressor / Combustion / Turbine / Nozzle kartları (kadran + siyah dijital kutular), A kartında gönderilen uçuş koşullarının geri okunuşu ve 3 grafik. Değerler DBC (CAN) ya da A2L (CCP) kaynağından okunur; eşleme isimle otomatik denenir, eşleşmeyen kutuya **sağ tık → Sinyal bağla…**. Kutuya sağ tık → **Eşik ayarla…** (ör. Surge Margin altında sarı/kırmızı); eşik girilmezse renk değişmez. Kadran aralığı A2L min/max'tan alınır, yoksa otomatiktir (sağ tık → Aralığı ayarla). Grafiklerde "Seç…" ile sinyaller, "Normalize" ile farklı birimler tek eksende karşılaştırılır. Ayarlar `sim_interface.json` içinde saklanır.

### Kontrol Paneli (Simulink/MATLAB tabanlı ECU testi)

Sol menüde **Kontrol Paneli**: uçak girişlerini, sensör override'larını, çıkışları ve iç sinyalleri TEK sayfada toplar.

1. **CAN Monitor → DBC yükle** ve **Kalibrasyon → A2L** sekmesinden A2L dosyasını yükleyin. Sinyal kataloğu bu dosyalardan otomatik çıkar (CSV gerekmez).
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
- **RPM, İtki, PLA, Tt5, FP, FT, Ps2, Tt2** ve Ortam Koşulları (Batarya
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

- Üstte yatay sekme çubuğu; **Ana Sayfa sekmesi sabittir** (kapatılamaz/taşınamaz) ve
  16" laptopta (en az ~1280x720 etkin çözünürlük) **kaydırma olmadan** tek ekrana sığar.
- Sol: **Uçuş Koşulları**, **Motor Kontrol** ve **Eyleyiciler** (ikisi kilitli, değer + `_sw`, CAN/A2L) +
  **Son olaylar** (komut gönderildi / hata / bağlantı, renkli). Sağ: **Motor Parametreleri** (8 gösterge) + **Canlı Trendler**.
- **⚙ Eşleşmeler**: sensör, eyleyici, motor komutu ve giriş sinyalleri. Sensör ve eyleyicilerde
  her değişkenin **Değer** ve **Anahtar (`_sw`)** eşleşmesi ayrı ayrı **CAN (DBC) ya da A2L**
  olarak seçilir (sensörlerde isteğe bağlı *Arıza* biti de). Motoru Başlat / Durdur / Acil
  Durdurma da CAN veya A2L olabilir. Eski `dashboard_config.json` otomatik göç eder.
- **Arayüz uzun işlemlerde donmaz:** harita/tablo, flaş ve toplu parametre yazmaları arka plan iş
  parçacığında yürür (durum çubuğunda "⏳ … yazılıyor"; o sırada Kalibrasyon ve Kontrol Paneli sayfaları
  geçici kilitlenir, ikinci bir uzun iş başlatılamaz, pencere kapatılamaz). Acil Durdurma, eyleyici ve
  override kapatma yazmaları süren işin parçaları arasına ÖNCELİKLE girer. Kontrol Paneli / Ana Sayfa
  periyodik CAN gönderimi de ayrı iş parçacıklarındadır: arayüz takılsa bile kareler kesilmez. Gönderilen
  TÜM kareler (periyodik olanlar dahil) CAN Monitor'da ve CSV kaydında TX olarak görünür.
- **Acil Durdurma ONAY SORMAZ:** tek tıkla gönderilir (Motoru Başlat/Durdur da öyle).
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
- **Kilit (`_sw`)**: kilitli (anahtar=0) iken değer değiştirilemez. Kilit açılınca (Mühendis/Yönetici
  + onay) önce değer, sonra `<ad>_sw = 1` yazılır; tekrar kilitleyince `<ad>_sw = 0`.
- **Canlı Trendler**: normalize yok, her sinyal gerçek birimiyle (çoklu Y ekseni); 60 sn/5 dk/10 dk/1 sa,
  yakınlaştır/uzaklaştır, A/B imleçleri ve Δ, iki sinyalin farkı, Test Başlat/Bitir işaretleri,
  CSV/MAT/MDF dışa aktarım.
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
- **Kalibrasyon > Parametre Listesi:** değerler sürekli canlıdır; Değer hücresine yazıp **Enter** yazar
  (Esc / başka yere tıklamak iptal), yazılan değer ECU'dan geri okunup doğrulanır.
- **Ayarlanabilir parametreler (clbc_*)** grafik/trend/çalışma alanı/performans listelerinde
  "Ayarlanabilir parametreler" grubunda görünür.
- Doğrulanamayanlar: PCAN-USB'nin gerçek bus-off davranışı ve gerçek ECU açılış süresi yalnızca
  yazılım simülasyonuyla test edildi; ilk gerçek testte olay günlüğünü kontrol edin.

### PCAN-View ile birlikte test etme (donanımsız-adjacent)

PEAK-System'in PCAN-View programı ve bu uygulama, aynı CAN kanalına
**aynı anda** bağlanabilir (fiziksel kablolama gerekmez): PCAN-View'de
mesaj gönderip bu uygulamanın İzleme sekmesinde göründüğünü, ya da bu
uygulamadan gönderip PCAN-View'de göründüğünü doğrulayarak çift yönlü
haberleşmeyi test edebilirsiniz.

### Önemli sınırlamalar (bilinçli olarak uygulanmadı)

- **Flaş yazmanın M220'ye özel akışı doğrulanmadı** (bkz. yukarıdaki uyarı) —
  komut dizilimi standarda göre uygulandı ama gerçek donanımla test edilmedi.
- **Diagnostics ekranı** ECU'ya özel arıza kodu formatını "bilmediği"
  için ham DIAG_SERVICE istek/cevabı gösterir, yorumlamaz.
- **STD_AXIS/COM_AXIS eksenli haritalar**: Harita Editörü'nde fonksiyon
  değerlerinin bellek adresi sadece FIX_AXIS eksenler için doğrulanmıştır;
  diğer eksen tipleri için ekranda uyarı gösterilir.
- **Kullanıcı rolleri kimlik doğrulama değildir** (şifre yok) — amaç,
  denetim günlüğünde kimin ne yaptığını görünür kılmak ve kalibrasyon
  yazma gibi işlemleri kazara tetiklemeyi zorlaştırmaktır.

## Sorun giderme

- **"python" tanınmıyor**: Python kurulurken PATH'e eklenmemiş; Python'u
  kaldırıp yeniden kurun, "Add python.exe to PATH" kutusunu işaretleyin.
- **PyInstaller "not recognized"**: `1_kurulum.bat` başarıyla bitmemiş
  olabilir; tekrar çalıştırıp hata mesajını okuyun.
- **exe çalışınca "No module named can.interfaces.pcan" (veya benzeri)**:
  `2_exe_olustur.bat` içindeki `--collect-submodules`/`--collect-all`
  bayraklarına eksik olan paketi ekleyip yeniden derleyin (script
  içinde örnek ve açıklama var).
- **PCAN-USB Bağlantı sekmesinde görünmüyor**: PEAK-System sürücüsünün
  kurulu olduğundan ve adaptörün Aygıt Yöneticisi'nde göründüğünden
  emin olun.

## Son sürümde değişenler (özet)

- **CCP varsayılanları**: CRO ID `6F9`, DTO ID `6F8` (CCP sekmesinden değiştirilebilir).
- **Otomatik CCP**: CAN'a bağlanınca CCP kendiliğinden bağlanır (kutucuktan kapatılabilir);
  "CCP Bağlan / Bağlantıyı Kes" düğmeleri elle kullanım için durur.
- **RAM'e yazma onay sormaz**; yalnızca FLAŞ (kalıcı) yazma onay ister.
- **Bağlantı izleme**: adaptör çekilirse ~3 sn teyit edilir, "Bağlantı KOPTU" gösterilir,
  adaptör geri gelince otomatik yeniden bağlanır (CCP de devam eder).
- **Kalibrasyon**: "Parametre Listesi" (Adres / Hex / Değer / Ad, sınırsız sayıda satır, toplu
  yaz/oku) ve "Harita Editörü" (birden çok eğri/harita/dizi aynı anda sekmelerde, 1×16 gibi diziler dahil).
- **Duyarlı arayüz**: sayfalar kaydırılabilir, pencere ekrana sığacak şekilde açılır,
  göstergeler orantılı ölçeklenir.
- **Kalıcı dosyalar** exe'nin yanındaki klasörde (yazılamazsa Belgelerim\OpenECU_M220_Veri):
  `audit_log.txt` (5 MB'ı aşınca `.1` yedeği), `calibration_history.json` (son 5000 yazım),
  `profiles.json`, `dashboard_config.json`, `watchlist.json`, `kontrol_paneli.json`, `sim_interface.json`,
  `workspace_layouts.json`, `openecu.log` (hata günlüğü); CAN kayıtları `can_loglari\`, tablo yazım yedekleri
  `tablo_yedekleri\`. Her JSON için bir `.bak` yedeği tutulur; bozulan dosya `*.corrupt-<zaman>` olarak saklanır.
- **Simge**: `app_icon.ico` (exe'ye `--icon` ile gömülür).
- **Lookup (Harita Editörü)**: üstte grafik (seçili hücre kırmızı nokta, GİZLE düğmesi), gri eksen
  başlıklı değer tablosu, ONLINE/OFFLINE rozeti ve "Ayrıntıları göster" ile hücre başına
  Adres / Hex / Değer / Ad / Tip / Birim listesi (Değer sütunu düzenlenebilir).
  Parametre Listesi'ne "Açıklama" (A2L) sütunu eklendi.

## Ana Sayfa – kompakt yerleşim
- Solda dar "Simülasyon Girişleri" sütunu; sağda 8 gösterge tek satırda (dar ekranda otomatik 4×2), altında Sensör Durumu ile Canlı Grafik yan yana, en altta Eyleyiciler şeridi.
- DBC/A2L eşlemeleri (eski "Ayarlar" formu) artık sayfada değil: Motor Parametreleri başlığındaki **⚙ Eşlemeler** düğmesiyle açılan pencerede. Bağlı olmayan gösterge varsa yanında "⚠ N gösterge bağlı değil" uyarısı çıkar.

## Ana Sayfa – son düzen
- Sol: Simülasyon Girişleri + Eyleyiciler (gönderdiklerim). Sağ: Motor Parametreleri (4×2) ve Sensör tablosu yan yana, altta kalan alanı dolduran Canlı Grafik (izlediklerim). Dar pencerede tablo göstergelerin altına iner, sayfa dikey kayar.

## Ana Sayfa – seçilebilir Canlı Grafik
- Canlı Grafik'in sağ üstündeki **Sinyalleri seç** düğmesiyle istediğiniz sayıda sinyal çizdirilir: 8 gösterge sinyali (RPM, İtki, PLA ...) ve yüklü A2L'deki tüm ölçümler. Penceredeki **İsme göre ara...** kutusu listeyi süzer.
- Seçim kaydedilir (dashboard_config.json) ve Analiz → Çalışma Alanı'ndaki grafik panellerinden bağımsızdır. A2L ölçümlerinin okunması için CCP bağlantısı gerekir.

## Çalışma Alanı (Concerto / Data Inspector tarzı)
**Analiz → Çalışma Alanı** iç sekmesi. Tek ekranda istediğiniz pencereleri kurarsınız:
- **+ Grafik / + Gösterge / + Tablo** düğmeleriyle pencere ekleyin (giriş gönderimi için Ana Sayfa veya Kontrol Paneli kullanılır; eski yerleşimlerdeki "Kontrol" pencereleri açılışta atlanır); başlıklarından sürükleyip kenarlarından boyutlandırın. **Döşe / Kademeli** otomatik düzenler.
- **Yerleşimi kaydet** ile düzeni isimle saklayın, listeden seçince yüklenir. Son düzen program kapanırken otomatik hatırlanır (workspace_layouts.json).
- Soldaki **Sinyaller** listesi: A2L ölçümleri (CCP ile okunur), DBC sinyalleri (CAN'den çözülür), göstergeler, girişler, matematik ve içe aktarılan kayıtlar. **İsme göre ara...** ile süzün, çift tıklayıp etkin pencereye ekleyin.
- **Dondur:** ekran sabitlenir, veri arka planda kaydedilmeye devam eder; fareyle yakınlaştırıp kaydırabilirsiniz. **Devam** canlı akışa döner.
- Grafik penceresi: **Üst üste / Ayrı ayrı** çizim, tablodan sinyal başına **renk ve kalınlık**, fareyle gezince anlık değerler, **İmleçler (A/B)** ile aralıkta Δ, ortalama, min, maks.
- **ƒ Matematik sinyali…**: ölçekle (a·x+b), A+B / A−B / A×B / A÷B (örn. P3/P2), hareketli ortalama. Sonuç yeni bir sinyal olarak çizilir; geçmiş veriye de uygulanır.
- **⧉ Paneli ayır:** seçili paneli (başlığına tıklayıp) uygulamanın dışında ayrı bir pencereye alır; ikinci monitöre taşıyabilirsiniz. Ayrı penceredeki **Çalışma alanına geri yerleştir** düğmesi geri getirir. Ayrılmış pencereler konumlarıyla birlikte yerleşime kaydedilir.
- **Kaydı temizle:** veriyi siler, zamanı 0'a alır. **CSV'ye aktar / CSV aç:** kayıtları dışa/içe aktarır; eski bir kaydı yenisiyle üst üste çizip karşılaştırabilirsiniz.

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
5. **Performans kadranları:** Gerçek veriyle iğne, değer ve etiketler okunuyor mu? Aralıklar (sağ tık →
   Aralığı ayarla) doğru mu?
6. **Eşleşmeler:** Acil Durdurma dahil tüm motor komutları ⚙ Eşleşmeler'de tanımlı mı? (Tanımsızsa komut
   şeridinde "⚠ Acil Durdurma eşlenmemiş" görünür.)

## Oturum parametre kaydı (CSV)
**Tanılama ve Oturum → Oturumu Başlat** ile birlikte izlenen parametrelerin değerleri diske sürekli yazılır; böylece oturum bittikten (program kapandıktan/çöktükten sonra bile) incelenebilir.
- **Dosya:** veri klasöründe `oturum_kayitlari\<test_ismi>_<tarih_saat>.csv`. Her oturum yeni dosya açar, eskisinin üzerine yazılmaz. Yol oturum kartında ve olay günlüğünde (OTURUM) görünür.
- **Neler yazılır:** A2L/CCP ile okunan ve izlenen değerler (`a2l:<ölçüm>`: Ana Sayfa göstergeleri ve grafiği, Parametre Listesi, Çalışma Alanı), Ana Sayfa göstergeleri (`gauge:<anahtar>`), Simülasyon girişleri (`input:<anahtar>`) ve Çalışma Alanı'nda seçili DBC sinyalleri (`dbc:<MESAJ>.<SİNYAL>`). Aynı değer iki kaynaktan gelirse tek satır yazılır.
- **Biçim:** `time,signal,value,unix_time` (time = oturum başından saniye; unix_time = mutlak zaman). Excel'de açılabilir.
- **Geri açma:** Analiz → Çalışma Alanı → **CSV aç** ile kayıt yüklenip grafikte çizilir, yeni bir kayıtla üst üste karşılaştırılabilir.
- Veri saniyede bir diske işlenir (çökmede en çok ~1 sn kaybolur). Disk hatasında kayıt durur ve olay günlüğüne HATA yazılır. Manuel adresli (A2L'siz) Parametre Listesi satırları kaydedilmez. Oturum başlatılmadıkça kayıt yapılmaz.

## Geliştirici notları: kod yapısı, testler ve CI

- **Ana pencere parçalara bölündü.** `app/ui/main_window.py` yalnızca pencere çatısını, sayfaları, sinyal
  bağlantılarını ve kapanışı içerir. İş mantığı `app/ui/mainwin/` altındadır: `connection.py` (CAN bağlantısı,
  sağlık izleme, alım/gönderim), `calibration.py` (CCP oturumu, arka plan CCP işleri, harita / Parametre
  Listesi / tanılama / geri alma), `dashboard.py` (eşleşme yazımı, motor komutları, göstergeler),
  `panel.py` (Kontrol Paneli, simülasyon, Performans), `profiles.py` (rol ve profiller), `common.py` (sabitler).
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
