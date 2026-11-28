# Alınan kararlar

Soru sorulmadan alınan her karar: tarih/aşama – karar – gerekçe – alternatifler.

- 2026-11-26 / A1 – "Default'a dön" = A2L'de tanımlı varsayılan yoksa oturum başı ECU değeri; UI'da referans etiketi gösterilir. Başlangıca dönüş ECU'ya doğrudan yazmaz, tabloya düzenleme yükler. Gerekçe: GOREV 2.3 (varsayılan uydurma yok) ve 2.3 sonu (mevcut yazma onayı/yetki korunsun). Alternatif: doğrudan yazma (yetki atlama riski).
- 2026-11-26 / A1 – Başarısız yazmalar da geçmişe `write_ok=False` ile girer; geri alınamaz. Eski geçmiş dosyaları varsayılanlarla yüklenir (geri uyumlu).
- 2026-11-26 / A2 – Trend'e yeni araç düğmeleri üçüncü satıra konuldu (mevcut test panel asgari genişliği <900 px şartı).
- 2026-11-26 / A2 – Sinyal tablosu QTreeWidget (sürükle-bırak + gruplar yerleşik). Ofset/ölçek yalnızca ekran dönüşümü; imleç/istatistik ham veriden.
- 2026-11-26 / A3 – SessionRecorder mevcut sınıf geliştirildi (ikinci altyapı yok); CSV biçimi aynı kaldı, ek bilgi yan dosyalarda (events/meta/asc). Gerekçe: log_export, SignalHub.import_csv geri uyumu.
- 2026-11-26 / A3 – Mevcut `test_write_error_stops_recording` asenkron yazma nedeniyle bekleme döngüsüne uyarlandı (davranış aynı, zamanlama değişti).
- 2026-11-26 / A4 – ASC için python-can `ASCWriter/ASCReader` yeniden kullanıldı (standart yapı + geri okuma testi). `.log`: varsayılan ASC içerikli, ayrıca candump biçimi; hedef yazılımda doğrulanmadı.
- 2026-11-26 / A4 – MDF4 sürümü 4.10, sinyal başına ayrı kanal grubu. Concerto MDF sürüm desteği açık kaynaklardan teyit edilemedi → "doğrulanmadı".
- 2026-11-26 / MIL1 – UDP paketi sabit boyutlu ikili (magic/sürüm/tür/sıra/sim_time + yük); gerekçe: Simulink'te kolay paketleme, doğrulama. Alternatif: JSON/protobuf (Simulink'te ağır).
- 2026-11-26 / MIL1 – Bus bağlantı sağlığı heartbeat'ten; `link_state` "waiting/timeout" → mevcut izleme "bus_warning" (kopma değil uyarı), çünkü model sonradan başlayabilir (11.10).
- 2026-11-26 / MIL1 – MIL'de otomatik CCP bağlantısı atlanır (A2L adres alanı yok); kalibrasyon MIL3'te parametre kanalı ile.
- 2026-11-26 / MIL3 – Kalibrasyon için MATLAB Engine yerine UDP parametre kanalı seçildi (MATLAB gerektirmez, model çalışırken ACK'li, zaman aşımı/NAK net); Engine yalnızca yaşam döngüsü komutlarında isteğe bağlı. Mevcut CcpSession.adopt() + CCPClient-benzeri istemci: ikinci kalibrasyon altyapısı kurulmadı.
- 2026-11-26 / MIL4 – Backend 'stopped' durumu READY/ERROR iken yok sayılır (başlatılmamış model Simulink'te de stopped).
- 2026-11-26 / MIL5 – Simülasyon zamanı kayıt CSV'sine yeni sütun yerine `mil:sim_time` sinyali (en çok 50 ms'de bir) olarak yazılır; gerekçe: CSV biçimi/okuyucular geri uyumlu, wall-clock ile karışmaz.
- 2026-11-26 / MIL6 – Senaryoda karar yalnızca `requirement` kimlikli adımlardan; yoksa SKIPPED ve 'TAMAMLANDI (otomatik karar yok)'. Gerekçe: GOREV 11.9 uydurma limit yasağı.
- 2026-11-28 / KAYIT-ZAMAN – `time` sütunu monotonik saatten (gerçek zaman), `unix_time` + yeni `system_time` sistem saati; sütunlar SONA eklendi (okuyucular konumsal ve `len>=4` denetli: geriye uyumlu). Gerekçe: Windows saat atlaması süre analizini bozmasın; kullanıcı iki zamanı ayrı istedi. Alternatif: yalnız epoch (atlamada bozulur). `time`, örneğin YAŞI kadar geriye gidilerek hesaplanır (kare geliş zamanı sistem saatiyle damgalı olduğundan; kuyrukta beklerken atlama çok nadir).
- 2026-11-28 / KAYIT-ZAMAN – "Gerçek zaman" = monotonik süre varsayıldı (kullanıcı onayladı); PCAN donanım zaman damgası eklenmedi (donanım yok, doğrulanamaz).
- 2026-11-28 / KAYIT-DAYANIKLILIK – fsync 5 sn'de bir + kapanışta (her saniye değil: disk yükü); fsync desteklenmeyen dosya sisteminde hata yutulur.
- 2026-11-28 / KAYIT-BÜTÜNLÜK – Boşluk analizi yalnız `dbc:` sinyalleriyle: CCP/giriş sinyalleri değişince yazıldığı için uzun sessizlikleri meşru; yoksa sahte alarm. Eşik 1 sn.
