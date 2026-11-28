# Kayıt dosyaları ve dışa aktarma formatları

Her kayıt ayrı bir **oturumdur**; aynı kök ad (`<ad>_<tarih_saat>`) ile dosya grubu yazılır (`<veri klasörü>/oturum_kayitlari/`).

| Dosya | İçerik |
|---|---|
| `.csv` | Uzun biçim: `time,signal,value,unix_time,system_time`. `time` = **gerçek zaman** (kayıt başından sn, MONOTONİK saat), `unix_time` = **sistem zamanı** (epoch, ms), `system_time` = aynı sistem zamanı okunabilir (`YYYY-MM-DD HH:MM:SS.mmm`, yerel saat). Sinyal kimliği öneki kaynağı verir: `dbc:` (CAN çözülmüş), `a2l:` (CCP ölçümü), `gauge:`, `input:` (kullanıcı girişi), `cal:` (uygulanan kalibrasyon), `mil:` (Simulink). |
| `.events.csv` | `time,unix_time,kind,text,system_time` (zamanlar CSV ile aynı): BASLANGIC, DURAKLATMA, DEVAM, MARKER, HATA, KALIBRASYON, bağlantı olayları… |
| `.asc` | Ham CAN kareleri, Vector ASCII (python-can `ASCWriter`); Rx/Tx, standart+extended ID. İlk kare gelince oluşur. |
| `.meta.json` | Üst veri: ad, kullanıcı/rol, mod (REAL/MIL/VIRTUAL), bağlantı, DBC/A2L dosya adı+boyut+SHA-256, Simulink model, sinyal tablosu (birim/kaynak/zaman tabanı), istatistik, `status` (`recording` → çökerse `recovered`; `complete`; `error`). |
| `_girisler.csv` | Kullanıcı girişleri (mevcut `InputLog`). |

## Zaman: gerçek zaman ve sistem zamanı ayrı kaydedilir
* **Gerçek zaman (`time`)** monotonik saatten gelir: Windows saati elle/NTP ile atlasa bile kesintisiz akar. Süre, periyot, gecikme analizi ve grafik ekseni bunu kullanır.
* **Sistem zamanı (`unix_time`, `system_time`)** PC saatidir: başka kayıt/notlarla eşleştirmek içindir; saat değişirse atlar. Atlama (>0,5 sn) olduğunda `SAAT` olayı yazılır ve `.meta.json > clock_jumps`'a eklenir.
* CAN kareleri PC'de alındığı anda damgalanır (PCAN donanım zaman damgası kullanılmaz; gerçek donanımla doğrulanmadı). `.asc` zamanları Vector ASC kuralıyla ilk kareye göre göreli yazılır.
* `.meta.json`: `time_source: "monotonic"`, `utc_offset_min`, `timezone`, `csv_columns`, `clock_jumps`. Eski kayıtlar (4 sütun, `time` sistem saatinden türetilmiş) aynen açılır; raporda "eski kayıt" diye belirtilir.

## ECU gücü kesilince / bağlantı sorunlarında
Kayıt DURMAZ. Hat 3 sn sessiz kalınca `BAGLANTI` olayı ("CAN trafiği kesildi … ECU kapalı olabilir"), trafik dönünce "CAN trafiği geri geldi (kesinti ≈ N sn)" yazılır. CCP için "ECU cevap vermiyor" / "ECU geri geldi" olayları yazılır. CSV'deki boşluk, olay çizelgesinde nedenleriyle görünür.

## Sonradan inceleme ve kayıt bütünlüğü
Oturum tarayıcı/rapor, her kayıt için bütünlük özeti verir (`SessionData.integrity()`): düşen veri, bozuk satır, yarım kapanan kayıt, saat atlaması ve CAN veri boşlukları (≥1 sn; yalnız `dbc:` kare-güdümlü sinyaller). Boşluk çevresindeki olayla (duraklatma/bağlantı/hata/saat/CCP) açıklanır; **açıklanamayan boşluk hata olarak** işaretlenir. Olay çizelgesi her olayı iki zamanla gösterir.

## Veri kaybı denetimi
`record()` çağıranı bloklamaz; kayıt, sınırlı kuyruk + ayrı yazma iş parçacığıyla yazılır. Kuyruk dolarsa `dropped` artar ve arayüzde (REC çipi, Veri kaydı kartı) görünür. Disk hatası `error` olarak görünür ve kayıt durur. CSV ve olay dosyası her saniye flush edilir (uygulama çökmesinde en çok ~1 sn kayıp) ve 5 sn'de bir `fsync` ile diske zorlanır (PC elektriği kesilirse en çok ~5 sn); kapanışta da `fsync`; beklenmedik kapanışta en çok ~1 sn veri kaybolur, oturum listesinde "KURTARILDI" görünür.

## Dışa aktarma (`app/session_export.py`) — formatlar birbirinin yerine geçmez
* **MDF4 (.mf4)** – fiziksel sinyaller; her sinyal kendi zaman damgalarıyla ayrı kanal grubunda; ad, birim, kaynak/zaman tabanı açıklamada. Sürüm 4.10. **AVL Concerto ile uyumluluk DOĞRULANMADI** (Concerto yok; MDF sürüm desteği kamuya açık kaynaklardan teyit edilemedi). asammdf ile geri okuma testi var.
* **ASC (.asc)** – ham CAN. Fiziksel sinyal içermez.
* **LOG (.log)** – iki seçenek: (a) ASC içerikli `.log` (yalnızca uzantı farkı; hedef yazılımda doğrulanmadı), (b) can-utils `candump -L` biçimi `(zaman) kanal ID#VERİ`.
* **CSV** – uzun biçim (kayıt dosyası). **MAT** – sinyal başına `{time, values, unit, name, source}`.

## Ek notlar
* Kullanıcı girişleri (Kontrol Paneli, sensör override, motor komutu) başarılıysa `input:<MESAJ.SİNYAL>` zaman serisi olarak da yazılır; kalibrasyon yazımları `cal:<ad>`.
* MIL: simülasyon zamanı `mil:sim_time` sinyali (en çok 50 ms'de bir) olarak yazılır; diğer sinyaller GUI alım zamanıyla. Analizde "Simülasyon zamanı ekseni" seçilebilir.
* Tetikleyici ile otomatik kayıt: tetik öncesi örnekler eski zaman damgalarıyla yazılır (göreli `time` negatif olabilir).
* Kısayollar: `Ctrl+Shift+R` kayıt başlat/bitir, `Ctrl+Shift+P` duraklat/sürdür, `Ctrl+Shift+M` işaret, `Ctrl+Shift+F` trend dondur.
