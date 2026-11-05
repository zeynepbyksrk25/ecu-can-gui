# OpenECU M220 Test & Kalibrasyon Aracı — Windows Kurulum ve Kullanım

Bu klasör, internete **hiç bağlanmadan** Windows'ta çalışan tek bir `.exe`
dosyası üretmeniz için gereken her şeyi içerir: uygulamanın kaynak kodu
(`app/`, `main.py`) ve kurulum/derleme betikleri. Gerekli Python
paketlerinin (`.whl`) toplam boyutu (~270 MB, özellikle PySide6) sohbet
üzerinden gönderilemeyecek kadar büyük olduğu için, onları **Adım 0**'da
kendiniz (tek komutla) indireceksiniz.

## Adım 0 — Paketleri indirme (İNTERNETLİ bir bilgisayarda)

İnternete bağlı herhangi bir bilgisayarda (Pardus/Linux geliştirme
makineniz de olur, ya da internetli bir Windows bilgisayar) bu klasörün
içinde:

- Linux/macOS: `bash 0_wheels_indir.sh`
- Windows: `0_wheels_indir.bat` dosyasına çift tıklayın

Bu, Windows (Python 3.11, win_amd64) için gereken TÜM paketleri indirip
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
| **CAN Monitor** | Bağlantı (arayüz/kanal/baudrate — arayüz seçimi "▸ Gelişmiş ayarlar" arkasında, varsayılan PCAN), İzleme (gelen/giden CAN trafiği), Gönderim (manuel/periyodik mesaj + DBC yükleme — Ana Sayfa'daki motor komutları ve eyleyici override'ları da aynı DBC'yi kullanır), Log (CAN trafiğini CSV'ye kaydetme) — tek sekmede birleşik |
| A2L | A2L dosyası yükleyip Measurement/Characteristic nesnelerini gezme |
| **Kalibrasyon** | İç sekmeler: **CCP** (canlı değer okuma, RAM'e geçici yazma, **Yönetici rolüyle flaşa kalıcı yazma**), **Harita Editörü** (1D/2D kalibrasyon tabloları, geri al/yinele, ısı haritası), **Geçmiş** (RAM ve FLAŞ yazımlarının eski/yeni değerleri, geri alma — FLAŞ kaydı uygulama kapansa bile kalıcıdır) |
| Grafik | Birden fazla bağımsız grafik paneli ekleyip her birinde ayrı sinyaller izleme; fareyle "sensör takibi" (crosshair) |
| **Tanılama** | CCP bağlantı testi + ham DIAG_SERVICE isteği, CAN bağlantı sağlığı + tüm CAN/CCP/kalibrasyon hatalarının tek listesi — birleşik |
| Test Oturumu | Oturum başlat/bitir, olay günlüğü, PDF test raporu |
| Kullanıcı / Profil | Rol seçimi (Operatör/Mühendis/Yönetici) ve bağlantı+CCP ayarlarını profil olarak kaydetme |

### Eyleyici manuel override (MATLAB/Simulink donanım testi)

Ana Sayfa'daki her eyleyici (Yakıt Pompası Start/Fuel, Yakıt Debisi Valfi,
Glow Plug, Başlatma Motoru) için bir anahtar/komut kutusu vardır. Anahtar
**kapalıyken** değer değiştirmek CAN'a hiçbir şey göndermez. Anahtarı
**açtığınızda** (Mühendis/Yönetici rolü + onay diyaloğu gerekir) uygulama
"override enable=1 + komut değeri" mesajını gönderir — bu sinyali dış bir
MATLAB/Simulink modelindeki Switch bloğu okuyup o eyleyiciyi dışarıdan
sürebilir. Anahtarı kapatınca "enable=0" gönderilir ve model kendi iç
hesaplamasına döner. DBC mesaj/sinyal eşlemesi Ana Sayfa → Ayarlar'dan
girilir (bkz. aşağıdaki bölüm). Detaylı donanım test senaryoları için
projenizdeki `Gercek_Donanim_Test_Plani.md` dokümanına bakın.

### Simülasyon Girişleri (Ana Sayfa) ve Performans sayfası

**Ana Sayfa → Simülasyon Girişleri (sol panel):** Start / Spark / Primary Fuel anahtarları, Throttle (0–120 %), Altitude (0–30 kft), Alfa/Beta (±90°, şimdilik pasif) ve sabit değerler (Ma, Toplam Giriş Basıncı, Ortam Basıncı, Ortam Sıcaklığı). Anahtarlar anında, sürgüler bırakılınca, sabit değer kutuları Enter ile gönderilir; "Hepsini gönder" tümünü yollar. Girişler DBC sinyallerine bağlanır: panel ilk DBC yüklemesinde isimle otomatik eşler, olmayanlar **⚙ Bağla** ile seçilir. Gönderim için Mühendis/Yönetici rolü ve CAN bağlantısı gerekir. Kontrol Paneli ile aynı değeri paylaşır.

**Performans (sol menü):** Compressor / Combustion / Turbine / Nozzle kartları (kadran + siyah dijital kutular), A kartında gönderilen uçuş koşullarının geri okunuşu ve 3 grafik. Değerler DBC (CAN) ya da A2L (CCP) kaynağından okunur; eşleme isimle otomatik denenir, eşleşmeyen kutuya **sağ tık → Sinyal bağla…**. Kutuya sağ tık → **Eşik ayarla…** (ör. Surge Margin altında sarı/kırmızı); eşik girilmezse renk değişmez. Kadran aralığı A2L min/max'tan alınır, yoksa otomatiktir (sağ tık → Aralığı ayarla). Grafiklerde "Seç…" ile sinyaller, "Normalize" ile farklı birimler tek eksende karşılaştırılır. Ayarlar `sim_interface.json` içinde saklanır.

### Kontrol Paneli (Simulink/MATLAB tabanlı ECU testi)

Sol menüde **Kontrol Paneli**: uçak girişlerini, sensör override'larını, çıkışları ve iç sinyalleri TEK sayfada toplar.

1. **CAN Monitor → DBC yükle** ve **A2L** sekmesinden A2L dosyasını yükleyin. Sinyal kataloğu bu dosyalardan otomatik çıkar (CSV gerekmez).
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
- Flaşa yazmak/geri almak yalnızca **Yönetici** rolüyle mümkündür (Kullanıcı
  / Profil sekmesinden rol seçin).
- Her flaş yazımından önceki değer Kalibrasyon Geçmişi'ne **diske kalıcı**
  olarak kaydedilir; "eski haline getir" uygulama kapanıp açılsa bile
  çalışır (geri alma = eski değeri tekrar flaşa yazmaktır).
- Gerçek donanımda ilk denemenizi önce test ortamında (yedek bir ECU ya da
  düşük riskli bir parametreyle) yapmanız önerilir.

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
  `profiles.json`, `dashboard_config.json`, `watchlist.json`; CAN kayıtları `can_loglari\`.
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
- Seçim kaydedilir (dashboard_config.json) ve Grafik sayfasındaki seçimden bağımsızdır. A2L ölçümlerinin okunması için CCP bağlantısı gerekir.
- Grafik sayfasındaki her panelde de **İsme göre ara...** kutusu vardır.

## Çalışma Alanı (Concerto / Data Inspector tarzı)
Sol menüde **Çalışma Alanı**. Tek ekranda istediğiniz pencereleri kurarsınız:
- **+ Grafik / + Gösterge / + Tablo / + Kontrol** düğmeleriyle pencere ekleyin; başlıklarından sürükleyip kenarlarından boyutlandırın. **Döşe / Kademeli** otomatik düzenler.
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
- **Günlük:** Beklenmeyen hatalar `openecu.log` dosyasına yazılır ve ekranda gösterilir. Aynı veri klasörünü iki program kopyası birlikte kullanamaz.
- **Testler:** `python -m pytest tests -q` (geliştirme ortamında; `pytest`, `PySide6`, `pya2ldb`, `python-can` gerekir).

## Sorun giderme: .bat dosyasına çift tıklayınca bir şey olmuyorsa
- Dosyayı zip'ten **çıkarıp** klasör olarak açtıktan sonra çalıştırın (zip içinden çalışmaz).
- Pencere hemen kapanıyorsa Başlat menüsünden "cmd" açıp klasöre gidin ve dosya adını yazıp Enter'a basın; hata ekranda kalır.
- "Python bulunamadı" uyarısı çıkarsa python.org'dan Python 3.11 kurun (Microsoft Store kısayolu işe yaramaz).
- .bat dosyasına çift tıklayınca **Not Defteri açılıyorsa** (dosya ilişkilendirmesi bozuk): aynı klasördeki **.cmd** kopyasına çift tıklayın (`0_wheels_indir.cmd`, `1_kurulum.cmd`, `2_exe_olustur.cmd`) — içerikleri aynıdır. Dosya adının sonunda gizli bir `.txt` olmadığını da kontrol edin (Gezgin → Görünüm → "Dosya adı uzantıları").

## Yenilikler (21 Ekim 2026)
- Uygulama simgesi turbojet motoru oldu (`app_icon.ico`, kodla çizilir).
- Ana Sayfa'da sensör sağlığı ince bir şerit: yalnızca arızalı sensörler listelenir ("Arıza yok" / "N arıza").
- Eyleyiciler: her kartta CAN | A2L kanal seçici. CAN = DBC mesajı; A2L = CCP ile değişken yazımı
  (⚙ Eşlemeler'de A2L enable / değer değişkenleri girilir). Seçim kalıcıdır.
