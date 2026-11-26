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
