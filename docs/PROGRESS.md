# İlerleme

Her madde bitince `[x]` yapılır; yanına test sonucu ve bilinen eksikler yazılır.

## Ana geliştirme
- [x] Aşama 1 – Kalibrasyon değişiklik takibi
  - Yeni: `app/change_tracker.py` (saf mantık), `app/ui/change_icons.py`. Değişen: `history.py` (write_ok, source, delta, for_object, last_applied), `ui/watch_tab.py` (Değişim sütunu, yanıp sönen ok), `ui/map_editor_tab.py` (hücre oku, ipucu, Düzenlemeleri Geri Al / Hücreyi / Haritayı Başlangıca Döndür, onaylı), `ui/history_tab.py` (Δ, Yazma durumu, parametre filtresi), `ui/mainwin/calibration.py` (başarısız yazma da geçmişe).
  - Testler: `tests/test_change_tracker.py`, `tests/test_calibration_tracking.py`.
  - Eksikler: A2L'de tanımlı varsayılan (`a2l_default`) şu an hiçbir kaynaktan beslenmiyor (pyA2L DEFAULT_VALUE okunmuyor) → referans her zaman "oturum başı ECU değeri" ve bu açıkça gösteriliyor. Başlangıca dönüş değeri tabloya düzenleme olarak yükler; ECU'ya yazma normal "ECU'ya Yaz" yolundan (yetki/kayıt korunur). Parametre Listesi'nde Enter anında yazdığı için "yazılmadı" durumu yalnızca yazma sürerken görünür.
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

## Bilinen eksikler / doğrulanamayanlar
- Gerçek MATLAB/Simulink, AVL Concerto, PCAN donanımı bu ortamda yok; ilgili her şey sahte yapıyla test edilir, "gerçek ortamda doğrulanmadı".
