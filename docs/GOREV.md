# ECU Test & Calibration GUI – Görev Tanımı (Kalibrasyon, Canlı Trend, Cursor, Data Logging, Simulink MIL)

> Bu dosya tek gerçek kaynaktır. Oturum uzar ve context özetlenirse buraya geri dön.

## 1. Projenin amacı
`offline_paket/` altındaki PySide6 tabanlı ECU Test & Calibration uygulamasını profesyonel ECU kalibrasyon/test yazılımlarının (Bosch Motorsport MODAS, MATLAB Simulink Data Inspector, ETAS INCA/MDA, Vector CANape, AVL Concerto) kullanım deneyimine yaklaştır. Birebir arayüz kopyalama yok; mevcut mimariyi, çalışan özellikleri ve tasarım bütünlüğünü koru.

**Temel hedef:** Kullanıcı ECU'yu kolayca kalibre edebilsin, sinyalleri canlı izlesin, test sırasında hiçbir önemli veriyi kaybetmeden kayıt alsın, test sonrası davranışı ayrıntılı incelesin.

Korunacaklar: Windows çevrimdışı çalışma; mevcut PySide6 mimarisi; PCAN / python-can altyapısı; DBC ve A2L desteği; CCP; mevcut Dashboard, Kontrol Paneli, CAN Monitor, Kalibrasyon ve diğer sayfalar; kullanıcı yetkilendirme ve güvenlik mekanizmaları.

Önce mevcut kodu analiz et. Var olan sınıf/fonksiyonları yeniden kullan. Aynı işi yapan ikinci kayıt, sinyal veya kalibrasyon altyapısı oluşturma.

---
## 2. KALİBRASYON SAYFASI – PARAMETRE DEĞİŞİKLİKLERİNİN GÖRSEL TAKİBİ

### 2.1. Değer değişim göstergeleri
Parametre değeri değiştirildiğinde:
- Artış → parametrenin yanında yukarı yönlü kırmızı ok; azalış → aşağı yönlü kırmızı ok.
- Ok ~1–2 sn yanıp sönsün; sonra daha sade bir yön göstergesi kalabilir.
- Değişim miktarı gösterilsin. Örnek: `Kp_Governor  1.35   ↑ +0.15`, `Ki_Governor  0.65   ↓ -0.15`, `FuelLimit 90 ↑ +5`.
- Renk kırmızı; artış/azalış yalnızca ok yönüyle ayrılsın.

Şu durumlarda da doğru çalışmalı: klavyeden değer girme; SpinBox artır/azalt; harita hücresi değiştirme; birden fazla hücreyi toplu değiştirme; ECU'ya yazma; ECU'dan yeniden okuma.

**Önemli:** ECU'ya yazılmamış değeri uygulanmış gibi gösterme. Düzenlenmiş değer ile ECU'ya uygulanmış değer ayırt edilsin.

### 2.2. Değişiklik geçmişi
Her değişiklik için: parametre adı, eski değer, yeni değer, değişim miktarı, birim, zaman, kullanıcı, ECU'ya yazılıp yazılmadığı, yazmanın başarılı/başarısız olduğu. Parametre bazında geçmiş incelenebilsin. Mümkünse geçmişten eski değere dönülsün; bu da normal kalibrasyon yazma işlemi olarak gerçekleşsin ve loglansın.

### 2.3. Default değerlere geri dönme
İki ayrı işlem:
1. **Değişiklikleri Geri Al:** ECU'ya yazılmamış düzenlemeleri geri al.
2. **Default Değerlere Dön:** Tanımlı varsayılanlara getir.

Varsayılanı yalnızca A2L'de veya mevcut kalibrasyon profilinde gerçekten tanımlıysa kullan. Yoksa tahmin üretme: oturum başında ECU'dan okunan değerleri başlangıç referansı olarak sakla ve kullanıcıya hangi referansın kullanıldığını açıkça göster.

Harita editöründe: seçili hücreyi başlangıca döndürme; seçili haritayı tamamen döndürme; birden fazla parametreyi toplu döndürme; geri alma öncesi onay. Mevcut yetkilendirme, yazma onayı ve ECU'ya yazma mekanizmaları korunsun.

### 2.4. Kullanıcı deneyimi
Kolayca görülsün: ECU'daki mevcut değer; kullanıcının düzenlediği değer; başlangıç/default; değişiklik miktarı; yazma durumu; parametrenin değiştirilebilir olup olmadığı. Harita hücrelerinin değişiklik durumları görsel olarak ayırt edilsin.

---
## 3. CANLI TREND – GELİŞMİŞ SİNYAL ANALİZ EKRANI
Mevcut `TrendPanel` MATLAB Data Inspector / MODAS benzeri profesyonel analiz ekranına dönüştürülsün.

### 3.1. Sinyal listesi ve renk tablosu
Grafiğin üstünde/yanında legend tablosu. Her sinyal için: ad, renk, anlık değer, birim, görünür/gizli, freeze durumu, kaynak (PCAN, Simulink MIL, vb.). Renkler tutarlı olsun (aynı sinyal her yerde mümkünse aynı renk). Tablo sürüklenebilir/yeniden sıralanabilir: sıra değiştirme, grafiğe ekle/çıkar, gruplama, renk değiştirme.

### 3.2. Grafikte sürükleme ve hareket
Fareyle sağa/sola ve yukarı/aşağı kaydırma; mouse wheel zoom; yatay (zaman) ve dikey (değer) zoom; tek sinyalin dikey ölçeğini bağımsız değiştirme; sinyalleri ayrı şeritlere taşıma; şerit yeniden boyutlandırma. Sinyal eğrisini dikey offset ile kaydırma mümkün olsun ve **orijinal veriyi değiştirmesin**. Pan, zoom, cursor sürükleme ve offset ayırt edilebilir etkileşim modları olsun; yanlışlıkla veri/zamanlama değişmesin.

### 3.3. Cursor sistemi – Main (A) ve Difference (B)
İki dikey cursor, fareyle sürüklenebilir, tüm şeritlerde ortak zaman konumu.
- Main Cursor: o zamandaki tüm görünür sinyal değerleri sabit panelde gösterilsin, cursor hareket ettikçe güncellensin.
- Difference Cursor: Δt, her sinyalin A değeri, B değeri, ΔY ve istenirse ΔY/Δt gösterilsin.
- Değerler sinyalin gerçek zaman damgalarına göre hesaplanmalı. Büyük veri boşluklarında yanıltıcı interpolasyon yapma; "veri yok" göster. Farklı birimler çalışmalı.

### 3.4. Freeze
Tek sinyal freeze; tüm grafikleri freeze; freeze edilmişi zoom ile inceleme; canlı veri arka planda alınmaya devam; freeze kalkınca canlıya dönüş. Freeze veri alımını durdurmaz, yalnızca görüntüyü kontrol eder.

### 3.5. Geçmişe dönük inceleme
Zamanda geriye kaydırma; geçmişte zoom; aralık seçme; canlı moda dönüş; geçmişte cursor; sinyal karşılaştırma. Bellekteki trend geçmişi ile diske kayıtlı test verisi ayrı tutulsun. Uygulama yeniden açılınca kayıtlı oturum yüklenip aynı analiz özellikleri kullanılabilsin.

### 3.6. Grafik düzeni
Grafik alanı geniş; sinyal listesi daraltılabilir; tek grafik tam ekran; birden fazla şerit; aynı birimde ortak eksen; farklı birimlerin eksenleri okunabilir; her grafik için bağımsız autoscale. Yerleşim kaydedilip sonraki oturumda yüklenebilsin.

---
## 4. DATA LOGGING – KESİNTİSİZ TEST KAYDI
Kayıt sistemi uygulamanın en önemli bileşenlerinden biri. Record'a basıldığı anda arka planda kayıt başlar; grafik hızına/GUI timer'ına bağlı olmaz.

### 4.1. Başlangıç/bitiş
Kayıt panelinde: Record, Pause, Resume, Stop, süre, örnek sayısı, CAN frame sayısı, dosya boyutu, düşen veri sayısı, durum. Record yeni bir test oturumu oluşturur. Belirgin REC göstergesi. Ayrı worker/thread; disk yazma GUI'yi bloke etmesin.

### 4.2. Kaydedilecekler
1. Ham CAN mesajları. 2. DBC ile çözülen tüm sinyaller. 3. A2L ölçüm değerleri. 4. CCP okuma/yazma işlemleri. 5. Kullanıcının değiştirdiği kalibrasyon değerleri. 6. Dashboard göstergeleri. 7. Kontrol Paneli girişleri. 8. Sensör override değerleri. 9. Motor çalışma durumu. 10. Simulink MIL sinyalleri. 11. Simülasyon zamanı ve model durumu. 12. Kullanıcı olayları ve hata mesajları. 13. Test başlangıç/bitiş işaretleri. 14. Bağlantı kopması, yeniden bağlanma, iletişim hataları.

Her örnekte mümkünse: sinyal adı, değer, birim, kaynak, zaman damgası, zaman tabanı, geçerlilik. CAN mesajları kendi geliş zamanında; CCP/A2L mevcut okuma periyodunda kaydedilsin. GUI'nin 250/500 ms periyodu kayıt frekansını sınırlamasın. Ham CAN ile çözülmüş sinyaller ayırt edilsin.

### 4.3. Veri kaybını önleme
Ayrı kuyruk + worker; yapılandırılabilir kapasite; kuyruk dolarsa sessiz kayıp yok, düşen sayı gösterilir; disk yazma hataları görünür; periyodik flush; beklenmedik kapanışta dosya mümkün olduğunca kurtarılabilir; kapanışta kuyruk boşaltılıp dosya güvenle kapatılır. Mevcut `SessionRecorder` ve `FrameRecorder` önce incelenip geliştirilsin; ikinci altyapı kurma.

### 4.4. Dosya formatları
- **MDF4 (.mf4):** zaman serisi için tercih edilen; AVL Concerto ve diğer araçlarla uyumluluk hedefi; sinyal adı, birim, zaman damgası, kaynak korunur.
- **ASC (.asc):** Vector ASCII CAN log; ham CAN frame standart ASC yapısında.
- **LOG (.log):** içerik ve format açıkça dokümante edilsin; ASC uyumlu ASCII CAN isteniyorsa ASC içeriği `.log` uzantısıyla da üretilebilsin; uzantı değiştirmekle uyumlu varsayılmasın, hedef yazılımla doğrulansın.
- **CSV:** mevcut uzun format korunur.
- **MAT:** MATLAB için export korunur.

Formatlar birbirinin yerine geçmez (ham CAN ≠ fiziksel sinyal zaman serisi).

### 4.5. AVL Concerto
Desteklenen format/veri gereksinimlerini doğrula; MDF4 sürüm uyumluluğunu araştır; kanal adı, birim, zaman, metadata koru; uygun export formatını belirle. Sadece uzantı değiştirerek uyumluluk iddia etme; Concerto'da doğrulanmamış format için garanti verme.

### 4.6. Test oturumları
Her kayıt ayrı oturum. Metadata: ad, açıklama, başlangıç/bitiş, kullanıcı, ECU bağlantı türü, ECU bilgisi, DBC dosyası+versiyonu, A2L dosyası+versiyonu, Simulink model adı, test sırasındaki kalibrasyon değişiklikleri. Geçmiş oturumlar listelenir, yüklenir, incelenir, export edilir.

---
## 5. TEST SONRASI DATA ANALYSIS
Kayıtlı oturumda canlı trenddeki araçlar kullanılabilsin: oturum açma; sinyal seçme; aynı grafikte çoklu sinyal; ayrı şeritler; Main/Difference Cursor; Δt, ΔY, ΔY/Δt; değer tablosu; zaman aralığına zoom; min/max/ortalama; test olayları işaretleme; kalibrasyon değişikliklerini zaman ekseninde gösterme (örn. Fuel Limit değişimi dikey event marker); başlangıç/bitiş işaretleri.

---
## 6. EK ÖZELLİKLER
- **6.1 Marker/annotation:** Manuel olay (Motor start, Ignition ON, Fuel ON, Idle, Acceleration, Maximum RPM, Shutdown, Test error); grafikte ve kayıt dosyasında saklanır.
- **6.2 Trigger / otomatik kayıt (tasarla):** RPM eşiği, EGT limiti, CAN hata sayısı artışı, motor durumu geçişi; pre-trigger/post-trigger veri.
- **6.3 Test raporu:** Kayıt durunca isteğe bağlı; test bilgileri, DBC/A2L, süre, sinyal istatistikleri, min/max, kalibrasyon değişiklikleri, olaylar, hata/bağlantı olayları, dosya konumları.

---
## 7. UI / UX
Profesyonel, sade, hızlı; mevcut tasarım dilini koru; dekoratif öğe yok; grafik alanına maksimum yer; sık işlemler kolay erişilir; kritik işlemlerde bilgilendirme; kalibrasyon yazma ve default'a dönme onaylı; klavye kısayolları; özelleştirilebilir listeler/düzenler; uzun kayıtlarda ve büyük dosya açılışında arayüz donmaz; kayıt ve bağlantı durumu her zaman açık. 1920x1080 ve 1440x900'da kullanılabilir.

---
## 8. TEKNİK KURALLAR
Önce mimariyi analiz et. İncelenecek: `app/ui/trend_panel.py`, `app/ui/kalibrasyon_tab.py`, `app/ui/map_editor_tab.py`, `app/session_recorder.py`, `app/log_export.py`, `app/signal_hub.py`, `app/history.py`, `app/ui/history_tab.py`, `app/ui/log_tab.py`, `app/ui/dashboard_tab.py`, `app/ui/ccp_tab.py`, `app/a2l.py`, `app/ccp/`. (Yollar `offline_paket/` altında olabilir.)

1. GUI thread'inde uzun dosya/CAN/CCP/MATLAB işlemi yok.
2. Veri toplama ile grafik çizimi ayrı.
3. Grafik yenileme frekansı kayıt frekansını sınırlamaz.
4. CAN, CCP, A2L, Simulink zaman damgaları korunur.
5. MIL simülasyon zamanı ile gerçek zamanlı ECU alım zamanı karıştırılmaz.
6. NaN/Inf kontrolü.
7. Büyük kayıtlarda bellek kontrolü.
8. Sinyal adı ve birimler korunur.
9. Mevcut API'ler mümkün olduğunca geriye dönük uyumlu.
10. Var olan testler bozulmaz.
11. Yeni özellikler birim + entegrasyon testleriyle doğrulanır.
12. Lisanslı/çevrimiçi servise zorunlu bağımlılık yok.

## 9. KABUL KRİTERLERİ
**Kalibrasyon:** artış→yukarı ok; azalış→aşağı ok; miktar gösterilir; geçmiş saklanır; yazılmamış değişiklik geri alınır; tanımlı default'a dönülür; harita editöründe aynı davranış.
**Canlı trend:** çoklu sinyal; renk tablosu; sürükleyerek sıralama; pan (yatay/dikey); zoom ve autoscale; Main Cursor tüm değerleri; Difference Cursor farkı; freeze/live; geçmişe gitme; büyük boşlukta yanlış interpolasyon yok.
**Logging:** Record anında başlar; GUI donmadan kayıt; ham CAN + çözülmüş sinyal; A2L/CCP, giriş ve kalibrasyon olayları; kayıp ve disk hataları görünür; Stop sonrası güvenli kapanış; kayıt tekrar açılıp analiz edilir; ASC, LOG, CSV, MDF4 test edilir; AVL Concerto formatı gerçek uyumluluk testiyle doğrulanır (doğrulanamıyorsa açıkça "doğrulanmadı" yaz).

## 10. UYGULAMA STRATEJİSİ (kontrolsüz yeniden yazma yok)
- **Aşama 1 – Kalibrasyon değişiklik takibi:** artış/azalış göstergeleri, değişiklik geçmişi, default/undo, harita editörü entegrasyonu.
- **Aşama 2 – Canlı trend ve cursor:** sinyal tablosu, sürükleme/düzen, Main Cursor, Difference Cursor, freeze ve geçmiş inceleme.
- **Aşama 3 – Kayıt altyapısı:** SessionRecorder geliştirmeleri, ham CAN, tüm sinyal/olay kaydı, REC/Pause/Stop arayüzü, veri kaybı kontrolleri.
- **Aşama 4 – Export ve test sonrası analiz:** MDF4, ASC, LOG, CSV, MAT, AVL uyumluluk doğrulaması, kayıtlı oturumları açma/inceleme.

Her aşama sonunda: değiştirilen dosyaları listele; değişiklikleri açıkla; testleri çalıştır; sonuçları raporla; bilinen eksikleri belirt. Çalışmayan özelliği tamamlanmış gösterme.

**SON HEDEF:** Kullanıcı ECU'ya bağlanır; motor girişlerini ve kalibrasyonları değiştirir; sinyalleri canlı izler; cursor/grafik araçlarıyla analiz eder; tek tuşla kayıt başlatır; tüm veriyi ve kalibrasyon değişikliklerini kaydeder; sonra yeniden açıp karşılaştırır; MATLAB, AVL Concerto ve diğer araçlara aktarır. **Öncelik: veri doğruluğu, kayıt güvenilirliği, kalibrasyon güvenliği, kullanıcı deneyimi.**

---
## 11. SIMULINK MIL ENTEGRASYONU – GERÇEK DONANIM ÖNCESİ ALGORİTMA TESTİ

### 11.1. Temel hedef
Gerçek ECU'ya bağlanmadan Model-in-the-Loop ile test: PySide6 GUI ve MATLAB/Simulink aynı Windows bilgisayarda; kontrol algoritması ve motor (plant) modeli Simulink'te; GUI modele giriş sinyalleri ve kalibrasyon gönderir; çıkışlar GUI'de canlı izlenir; simülasyon arayüzden başlatılır/duraklatılır/durdurulur. Mevcut uygulamanın yerine geçmez; PCAN/gerçek ECU korunur; MIL seçilebilir yeni mod.

### 11.2. Çalışma modları
1. REAL ECU (PCAN-USB). 2. MIL / Simulink. 3. VIRTUAL / TEST (donanım ve MATLAB gerektirmez). Bağlantı sayfasından seçilir; her modun durumu açık gösterilir; MIL'de fiziksel CAN bağlıymış gibi gösterme. Mod değişiminde aktif bağlantı ve kayıt güvenle kapatılır. REAL ve MIL aynı anda komut kabul etmesin.

### 11.3. Haberleşme mimarisi
Mevcut `CanConnection` ve `can.BusABC` soyutlamasını kullan; yeni `SimulinkUdpBus` backend'i; UDP üzerinden CAN frame; DBC iki tarafta ortak kaynak; Python tarafında mevcut DBC encode/decode korunur.
GUI→Simulink: PLA/gaz, rakım/ortam, sensör girişleri, operatör komutları, motor kontrol girişleri, sensör override, kalibrasyon değişiklikleri.
Simulink→GUI: RPM, EGT/Tt5, Fuel Flow, yakıt basıncı, itki, motor sıcaklıkları, aktüatör konumları, motor çalışma modu, ECU durum/hata.
Mesajlar DBC ile uyumlu (ID, node, byte order, ölçekleme, birim). UDP protokolü: paket boyutu/alanları dokümante; standart + extended ID; DLC doğrulama; hatalı paket reddi; heartbeat + timeout; veri gelmezse bağlantı hatası. UDP fiziksel CAN gibi sunulmaz; MIL'de gerçek bitrate/bus durumu gösterilmez.

### 11.4. Giriş sinyalleri
Kontrol Paneli MIL'de de çalışır. Örnekler: PLA/Throttle, Ambient Temperature, Ambient Pressure, Altitude, Starter, Ignition, Fuel pump, Fuel command, sensör girişleri. Mevcut projede tanımlı sinyalleri kullan; yeni sinyal adı/birim uydurma. Girişler alt/üst sınır kontrolünden geçer, doğru birimle, DBC ölçeklemesiyle kodlanır, mümkünse ACK ile doğrulanır. Sensör override MIL'de çalışır; gönderilen değer ile modelde uygulanan değer ayırt edilir.

### 11.5. Kalibrasyon → MIL
Kalibrasyon sayfası MIL'de çalışır: oku, değiştir, modele uygula, geri oku, başlangıca döndür, harita/eğri editörleri. A2L adresleri ile Simulink değişkenlerinin aynı olduğu varsayılmaz; açık eşleme katmanı: `A2L Parameter → Simulink Model Variable → Data Type → Scaling → Access Permission` (JSON manifest veya MATLAB üretimi). Erişim: MATLAB Engine API veya UDP parametre kanalı değerlendirilir; mimariye en uygun seçilir. Model çalışırken yazma desteği ve Simulink tunable kuralları kontrol edilir; yazılamıyorsa kullanıcıya modelin durdurulması gerektiği bildirilir.

### 11.3b. Yaşam döngüsü (11.6)
Ana Sayfa'da Simulink Model kontrol paneli: Start, Pause, Resume, Stop, Reset, simülasyon hızı, model durumu, simülasyon zamanı. Durumlar: NOT CONNECTED, CONNECTING, READY, RUNNING, PAUSED, STOPPED, ERROR. MATLAB Engine işlemleri ayrı worker/thread'de, GUI bloke olmaz. Model durumu ile UDP bağlantı durumu ayrı izlenir. MIL'de acil durdurma tanımlı; gerçek motor acil durdurmasının yerine geçmediği belirtilir.

### 11.7. Hız ve zaman
Hızlar: 0.25x, 0.5x, 1x, 2x, 5x, Fastest. Hız yalnızca GUI timer'ını hızlandırarak simüle edilmez; Simulink solver/pacing dikkate alınır. Zaman tabanları ayrı: MIL=Simulation Time; REAL=Monotonic Acquisition Time; kullanıcı kayıtları=Wall-clock. Karıştırılmaz. Grafik/cursor/logging gerçek simülasyon zamanını kullanabilir.

### 11.8. MIL'de trend ve logging
Tüm trend ve kayıt özellikleri MIL'de çalışır: Simulink çıkışları canlı trendde; cursor'lar; freeze/geçmiş; kalibrasyon event marker; model Start/Pause/Stop olayları kaydedilir; simülasyon zamanı korunur; kayıt sonrası aynı analiz ekranında incelenir. MIL kayıtları gerçek ECU kayıtlarıyla karışmaz; kaynak ve model adı metadata'da.

### 11.9. Test senaryoları
Python tarafında tanımlanabilir senaryolar (ilk aşamada manuel kontrol + temel yürütme): modeli başlat → başlangıç parametreleri → PLA → starter → RPM izle → koşulda sonraki adım → yakıt/ateşleme → EGT/RPM/Fuel Flow izle → limit aşımında işaretle → kayıtları sakla. Örnekler: motor start, idle, PLA artışı, ivmelenme, maksimum nokta, kontrollü shutdown, sensör arızası, sınır dışı değer, iletişim kaybı. Gerçek limitler model gereksinimlerinden gelir; uydurma limitle otomatik başarı/başarısızlık kararı verilmez.

### 11.10. MIL doğrulama testleri
MATLAB yokken REAL ECU modu çalışır; model başlamadan MIL bağlantısı açılır; model sonradan başlayınca bağlanır; durunca durum güncellenir; yeniden başlayınca tekrar bağlanır; Python girişleri modelde doğrulanır; çıkışlar DBC ile doğru çözülür; kalibrasyon değişiklikleri modelde doğrulanır; Start/Pause/Resume/Stop çalışır; simülasyon zamanı doğru kaydedilir; MIL kayıtları tekrar açılır; MATLAB Engine koparsa GUI donmaz; UDP kaybı/gecikmesi bildirilir. MATLAB'sız ortamda UDP testleri sahte modelle otomatik çalışır; gerçek MATLAB/Simulink testleri ayrı işaretli grupta.

### 11.11. Dosya organizasyonu (öneri; mevcut yapıya uyan daha iyisi varsa onu kullan)
`app/sim_bus.py` (python-can uyumlu UDP backend), `app/sim_protocol.py` (paket encode/decode), `app/sim_bridge/health.py`, `app/sim_bridge/matlab_ctl.py`, `app/sim_bridge/parameters.py`, `app/sim_bridge/simulink_parameters.py`, `simulink/` (MATLAB betikleri, örnek model bağlantısı, doküman), `tests/test_sim_bus.py`, `tests/test_sim_protocol.py`, `tests/test_sim_bridge.py`. MATLAB Engine API zorunlu bağımlılık olmaz.

### 11.12. MIL aşamaları
1. Haberleşme: UDP CAN backend, DBC uyumlu alışveriş, giriş/çıkış, heartbeat, CAN Monitor entegrasyonu.
2. Dashboard ve kontrol: Kontrol Paneli→Simulink, model çıkışları Dashboard'da, trend/sinyal altyapısı MIL ile.
3. Kalibrasyon: A2L–Simulink eşleme, okuma/yazma, harita/eğri editörü, değişiklik geçmişi.
4. Model kontrolü: MATLAB Engine, Start/Pause/Resume/Stop/Reset, hız ve durum.
5. Kayıt ve analiz: MIL sinyal kaydı, simülasyon zamanı, olaylar, analiz ve export.
6. Otomatik test: senaryolar, otomatik giriş, beklenen davranış kontrolleri, test raporu.

### 11.13. Son kabul
Gerçek ECU olmadan: MIL modu seç → modeli arayüzden başlat → algoritma Simulink'te çalışsın → Kontrol Paneli girişlerini değiştir → kalibrasyonu değiştir ve modele uygula → Dashboard ve trendlerde izle → Main/Difference Cursor ile analiz → tüm veriyi kaydet → modeli durdur → kayıtları yeniden aç → aynı arayüzü sonra PCAN ile gerçek ECU'da kullan.
**Temel prensip:** MIL ve REAL aynı GUI, sinyal isimleri, kalibrasyon ekranı, trend araçları ve kayıt altyapısını kullanır; yalnızca backend değişir.
