# İlerleme

Her madde bitince `[x]` yapılır; yanına test sonucu ve bilinen eksikler yazılır.

## Ana geliştirme
- [x] Aşama 1 – Kalibrasyon değişiklik takibi
  - Yeni: `app/change_tracker.py` (saf mantık), `app/ui/change_icons.py`. Değişen: `history.py` (write_ok, source, delta, for_object, last_applied), `ui/watch_tab.py` (Değişim sütunu, yanıp sönen ok), `ui/map_editor_tab.py` (hücre oku, ipucu, Düzenlemeleri Geri Al / Hücreyi / Haritayı Başlangıca Döndür, onaylı), `ui/history_tab.py` (Δ, Yazma durumu, parametre filtresi), `ui/mainwin/calibration.py` (başarısız yazma da geçmişe).
  - Testler: `tests/test_change_tracker.py`, `tests/test_calibration_tracking.py`.
  - Eksikler: A2L'de tanımlı varsayılan (`a2l_default`) şu an hiçbir kaynaktan beslenmiyor (pyA2L DEFAULT_VALUE okunmuyor) → referans her zaman "oturum başı ECU değeri" ve bu açıkça gösteriliyor. Başlangıca dönüş değeri tabloya düzenleme olarak yükler; ECU'ya yazma normal "ECU'ya Yaz" yolundan (yetki/kayıt korunur). Parametre Listesi'nde Enter anında yazdığı için "yazılmadı" durumu yalnızca yazma sürerken görünür.
  - **Düzeltme turu (ok göstergesi, Modas arayüzü):** Eski `watch_tab`/`map_editor_tab` artık ana arayüzde olmadığından Worksheets pencereleri doğrulandı ve düzeltildi. (1) Değer penceresinde `↑ ↑ +2.5 rpm` çift ok/çift birim hatası giderildi (`format_delta(with_arrow=False)`, `ChangeTracker.change_view` tek kaynak). (2) Ok artık simge: dolu kırmızı = ECU'ya yazıldı, içi boş amber = yazılmadı (bekleyen), ikisi şekilden de ayrılır; başarısız yazma ok göstermez, "✕ uygulanmadı" gösterir; yazımdan sonra ~1,5 sn yanıp söner. (3) Harita hücrelerinde hücre bazlı ok (bekleyen: içi boş, yazılan: dolu kırmızı), tooltip'te eski değer/fark, başlıkta özet ("Yazılmadı: N hücre (↑a ↓b)"). Testler: `test_change_tracker.py`, `test_modas.py`, `test_calibration_tracking.py`. Ekran görüntüsüyle (offscreen Qt) doğrulandı; gerçek ECU/ekranda doğrulanmadı.
  - **Düzeltme turu 2:** (a) Ok/özet bağlantısına tıklama → Calibration Tools > Geçmiş sekmesi açılır, parametre süzülür, son kayıt seçilir (`HistoryTab.show_object`, `MainWindow._modas_show_history`; kayıt yoksa durum çubuğunda uyarı; harita için özet satırında "Geçmişte göster" bağlantısı + sağ tık). (b) Harita başlığında başlangıçtan sapma özeti (oturum başı ilk tam ECU okuması referans; sapan hücre sayısı, en büyük sapma ve konumu, ortalama; `TableWindow.baseline_deviation`). (c) Oturum raporunda kırmızı ↑/↓ dili: parametre özet tablosu (ilk/son/başlangıca göre/↑↓ sayısı) + "Değişim" sütunu; referans = kayıttaki ilk değer, belirtilir (`session_report.calibration_summary`). Testler: `test_modas.py`, `test_calibration_tracking.py`, `test_session_report.py`.
  - Bilinen eksik: harita sapma referansı yalnızca oturum içinde tutulur (A2L varsayılanı hâlâ beslenmiyor); rapor, başarısız yazmaları göstermez (kayıtta yalnızca başarılı `cal:` örnekleri var). Gerçek ECU/ekranda doğrulanmadı.
- [x] Aşama 2 – Canlı trend ve cursor
  - Yeni: `app/trend_model.py` (imleç değeri/boşluk, ΔY, ΔY/Δt, min/max/ort, freeze kesimi, ofset/ölçek, yerleşim JSON), `ui/trend_signal_table.py` (renk/ad/değer/A-B/Δ/stat/birim/göster/dondur/kaynak/ofset; sürükle-bırak sıralama, gruplama, renk, ayrı şerit). `ui/trend_panel.py`: sinyal tablosu, freeze (tümü/tek), dikey serbest mod, A–B aralığına yakınlaştır, yerleşim kaydet/yükle (+otomatik kayıt `layout_path`), `load_static`.
  - Testler: `tests/test_trend_model.py`, `tests/test_trend_analysis_ui.py`.
  - Eksikler: sürükleyerek ofset yok (tablo/menü ile ofset-ölçek); şerit yeniden boyutlandırma pyqtgraph varsayılanı; tek grafik tam ekran için mevcut "Ayır" kullanılıyor; yerleşim otomatik yükleme (`layout_path`) henüz MainWindow'a bağlı değil (menüden elle).
- [x] Aşama 3 – Kayıt altyapısı
  - `SessionRecorder` yeniden yazıldı (geri uyumlu API): kuyruk + yazma iş parçacığı, pause/resume, olay/işaret dosyası, ham CAN → ASC (Rx/Tx), `.meta.json`, düşen/hata sayaçları, çökme kurtarma durumu. UI: Veri kaydı kartı (REC, Duraklat/Sürdür, işaret, canlı istatistik) + üst şeritte REC çipi. Olay günlüğü ve uygulanan kalibrasyonlar (`cal:`) kayda akar.
  - Testler: `tests/test_recorder_pipeline.py`; mevcut `test_session_recorder.py` bir test asenkron yazmaya uyarlandı (hata artık asenkron görünür).
  - Eksikler: Dashboard göstergeleri/Kontrol Paneli girişleri/sensör override için ayrı `register_signal` birimi bağlanmadı (girişler mevcut `input:` ve `_girisler.csv` yolundan); trigger/pre-trigger (6.2) ve test raporu (6.3) yapılmadı.
- [x] Aşama 4 – Export ve test sonrası analiz
  - Yeni: `app/session_export.py` (yükle/listele/MDF4/ASC/LOG/CSV/MAT), `ui/session_browser.py` (oturum listesi, analiz penceresi = TrendPanel + cursor, dışa aktar). `trend_panel.write_mdf` hatası düzeltildi (her sinyal kendi zaman damgasıyla ayrı grup). Format dokümanı: `docs/KAYIT_FORMATLARI.md`.
  - Testler: `tests/test_session_export.py`, `tests/test_session_browser.py`.
  - **AVL Concerto uyumluluğu DOĞRULANMADI** (gerçek Concerto yok).

## Simulink MIL
- [x] MIL 1 – Haberleşme (UDP CAN backend)
  - Yeni: `app/sim_protocol.py`, `app/sim_bus.py` (`SimulinkUdpBus(can.BusABC)`: DLC/ID/boyut doğrulama, hatalı paket reddi+sayaç, sıra no ile kayıp tespiti, heartbeat/timeout, model sonradan başlayabilir), `tests/fake_simulink.py`, `docs/MIL_PROTOKOL.md`, `simulink/`. `CanConnection` `sim_udp` arayüzü; Bağlantı sayfasında Mod seçici (REAL/MIL/VIRTUAL; MIL'de bitrate gizli, "fiziksel hat değil" notu; bağlıyken mod değişmez; mod değişince açık kayıt kapanır).
  - Testler: `tests/test_sim_protocol.py`, `tests/test_sim_bus.py` (DBC çift yönlü, extended ID, kayıp, timeout/toparlanma, UI).
  - **Gerçek MATLAB/Simulink ile doğrulanmadı** (yalnızca sahte model).
- [x] MIL 2 – Dashboard ve kontrol
  - Kontrol Paneli/Dashboard aynı CanConnection+DBC yolunu kullandığı için MIL'de çalışır; sinyal kaynağı etiketi "Simulink MIL" trend tablosunda. Test: `tests/test_mil_integration.py` (model çıkışı→Dashboard, Kontrol yazımı→model DBC ölçekli, link kaybı görünür).
  - Eksik: ACK ile doğrulama (modelde uygulanan değer ayrımı) ve alt/üst sınır denetimi mevcut Kontrol Paneli sınırlarına bırakıldı; modelden "uygulanan değer" geri bildirim mesajı protokolde yok.
- [x] MIL 3 – Kalibrasyon
  - Yeni: `app/sim_bridge/parameters.py` (JSON manifest: A2L→Simulink değişken→tip→ölçek→erişim, `tunable_running`, dizi/harita `count`), `app/sim_bridge/param_client.py` (`SimParamClient`: CCPClient bellek arayüzünü taklit eder; mevcut CcpSession/önbellek/Parametre Listesi/Harita Editörü/geçmiş DEĞİŞMEDEN çalışır), protokol tür 4 (parametre yaz/oku/ACK/NAK). Model çalışırken tunable olmayan parametre yazımı gönderilmeden reddedilir ("modeli durdurun"); modelde uygulanan değer geri okunup doğrulanır; flaş yazma MIL'de yok. Bağlantı sayfasında "Parametre eşleme…" (yol kalıcı).
  - Testler: `tests/test_sim_bridge.py`, `tests/test_mil_integration.py` (watch yazma → model, başarısız yazma geçmişte).
  - Eksik: MATLAB'da manifest üretimi betiği yok; modelin param paketlerini işleyen Simulink tarafı örneği yok (yalnızca protokol dokümanı); gerçek model doğrulanmadı.
- [x] MIL 4 – Model kontrolü
  - Yeni: `app/sim_bridge/matlab_ctl.py` (ModelController: NOT CONNECTED…ERROR durum makinesi, ayrı komut iş parçacığı, MatlabEngineBackend (isteğe bağlı bağımlılık; yoksa açık hata) + UdpControlBackend, hız = Simulink pacing), `app/ui/sim_model_panel.py` (Ana Sayfa; yalnızca MIL; Start/Pause/Resume/Stop/Reset, hız, MIL Acil Dur [gerçek motor acil durdurmasının yerine geçmez], model durumu ve UDP durumu ayrı). Model olayları kayda `MODEL` olarak yazılır.
  - Testler: `tests/test_matlab_ctl.py`, `tests/test_mil_integration.py`.
  - **MATLAB Engine yolu gerçek MATLAB/Simulink ile doğrulanmadı** (sahte engine).
- [x] MIL 5 – Kayıt ve analiz
  - MIL kayıtları: `mil:sim_time` ayrı sinyal (alım zamanıyla karışmaz), model Start/Pause/Stop olayları (`MODEL`), model adı+mod üst veride; analiz penceresinde "Simülasyon zamanı ekseni" (`SessionData.to_sim_time`; eşleme yoksa/model yeniden başlamışsa uydurma dönüşüm yok → kapalı). Kalibrasyon event marker mevcut.
  - Testler: `tests/test_mil_integration.py` (sim time kaydı/analizi).
- [x] MIL 6 – Otomatik test
  - Yeni: `app/sim_bridge/scenario.py` (JSON adımlar: model/speed/set/wait/delay/marker/check/monitor; zaman aşımı=TIMEOUT; gereksinimsiz check/monitor = SKIPPED, hiçbir limit uydurulmaz; adım hatasında güvenli dur; metin+JSON rapor), `app/ui/scenario_panel.py` (Tanılama ve Oturum sayfası; GUI iş parçacığı köprüsü), `simulink/scenarios/ornek_motor_start.json` (limitsiz örnek).
  - Testler: `tests/test_scenario.py`, `tests/test_scenario_ui.py`.
  - Eksik: sensör arızası/sınır dışı değer/iletişim kaybı senaryoları için hazır dosya yok (adım türleri yeterli; gereksinim limitleri kullanıcıdan gelmeli).

## İyileştirme turları
- **Tur 1 (performans/dayanıklılık):** SessionRecorder toplu yazma (1M örnek/2,5 sn, düşen 0); trend `arrays()` önbelleği (500k×4 örnek analizde tik 266 ms → 2 ms); büyük oturum yükleme `array('d')` (1M satır 0,7 sn); testler: `test_recorder_pipeline.py::test_burst_*`.
- **Tur 2 (kapsam):** Test raporu (HTML, `app/session_report.py`, oturum listesinde düğme) — GOREV 6.3; tetikleyici ile otomatik kayıt (`app/record_trigger.py` + `ui/trigger_panel.py`, pre/post-trigger, bir kez çalışır) — GOREV 6.2; Parametre Listesi'nde toplu "Seçilileri Başlangıca Döndür" (onaylı); trend yerleşimi MainWindow'da otomatik yükle/kaydet (`trend_yerlesim.json`), sonradan oluşan sinyallere de uygulanır; kayıt üst verisinde DBC birimi/kaynak/zaman tabanı.
- Tur 3+ planı: sensör/giriş override değerlerinin ayrı kaydı, kayıtlı oturumda kalibrasyon olaylarının dikey marker olarak otomatik gösterimi doğrulaması, UX kısayolları.

## Test sonuçları
- Tam paket (MIL 6 + Tur 2 sonrası anlık görüntü): **530 geçti** (25 dk). Sonraki küçük değişiklikler (kısayollar, giriş sinyalleri kaydı, bus hata dönüşümü) ilgili testlerle ayrıca geçti; son durum için tam koşu yeniden başlatıldı.

## Bilinen eksikler / doğrulanamayanlar
- Gerçek MATLAB/Simulink, AVL Concerto, PCAN donanımı bu ortamda yok; ilgili her şey sahte yapıyla test edilir, "gerçek ortamda doğrulanmadı".

## Kayıt / zaman / sonradan inceleme turu (2026-11-28)
- `session_recorder.py`: `time` monotonik (gerçek zaman); `unix_time` + yeni `system_time` (okunabilir, ms) CSV ve olay dosyasında; `.meta.json` zaman bilgisi (`time_source`, UTC farkı, `clock_jumps`); saat atlaması tespiti (`SAAT` olayı); 5 sn'de bir + kapanışta `fsync`.
- `ui/mainwin/connection.py`: hat sessizliği için "CAN trafiği kesildi (ECU kapalı olabilir)" / "geri geldi (N sn)" olayları; kayıt kesintide sürer.
- `session_export.py`: `t_axis` (monotonik analiz ekseni), `data_gaps`, `integrity`; `ui/session_browser.py`: iki zamanlı olay çizelgesi + bütünlük özeti, grafik ekseni monotonik; `session_report.py`: bütünlük, boşluk tablosu, iki zaman sütunu.
- Testler: `tests/test_time_and_integrity.py` (15). Gerçek ECU/PCAN ve gerçek güç kesintisinde doğrulanmadı (sahte zaman/saat atlaması ve sahte hat sessizliği ile test edildi).
- Bilinen eksik: `.asc` zamanları ASC kuralı gereği ilk kareye göre göreli (monotonik değil, sistem saatiyle damgalı kareler); PCAN donanım damgası kaydedilmiyor.

## Modas temizlik turu (2026-11-28)
- Kaldırıldı: Calibration Tools › A2L sekmesi; Analysis penceresi (Çalışma Alanı + Performans); Test Bench'te Uçuş Koşulları, Motor Kontrol, Son Olaylar, Canlı Trendler; Worksheets Input pencereleri; `workspace_tab`, `analiz_tab`, `performance_tab`, `sim_inputs`, `sim_widgets`, `sim_interface`, `graph_signal_dialog`, `modas/testbench` (≈ 6000 satır).
- Eklendi: `signal_feed.py` (Qt'siz besleme: DBC/gösterge → Scope hub'ı, PDF anlık görüntüsü), `ui/modas/signal_picker.py`, `ui/math_dialog.py`; Scope'ta **Sinyaller… / ƒ Matematik / CSV**; matematik tanımları `modas_worksheets.json`'da kalıcı.
- Testler: `test_scope_signals.py` (13) eklendi; kaldırılan sayfalara ait testler silindi/yeniden yazıldı (atlama/devre dışı bırakma yok). Tam paket: 611 geçti (offscreen, `-n 4`).
- Bilinen eksikler / bilinçli kayıplar: Çalışma Alanı gösterge/tablo panelleri ve ayrı pencereye alma yok; Uçuş Koşulları periyodik CAN gönderimi ve A2L eşlemesi yok; Test Bench'te PLA/Start kutusu yok (Control Panel kullanılır); `.asc` ve Scope davranışları gerçek donanımda doğrulanmadı. Not: `test_mapping_dialog` ile `test_modas` flight testi arasındaki sıra bağımlılığı bu turda ilgili testler silindiği için ortadan kalktı.
