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
- [ ] MIL 1 – Haberleşme (UDP CAN backend)
- [ ] MIL 2 – Dashboard ve kontrol
- [ ] MIL 3 – Kalibrasyon
- [ ] MIL 4 – Model kontrolü
- [ ] MIL 5 – Kayıt ve analiz
- [ ] MIL 6 – Otomatik test

## İyileştirme turları
(boş)

## Bilinen eksikler / doğrulanamayanlar
- Gerçek MATLAB/Simulink, AVL Concerto, PCAN donanımı bu ortamda yok; ilgili her şey sahte yapıyla test edilir, "gerçek ortamda doğrulanmadı".
