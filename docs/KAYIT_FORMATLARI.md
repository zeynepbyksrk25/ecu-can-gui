# Kayıt dosyaları ve dışa aktarma formatları

Her kayıt ayrı bir **oturumdur**; aynı kök ad (`<ad>_<tarih_saat>`) ile dosya grubu yazılır (`<veri klasörü>/oturum_kayitlari/`).

| Dosya | İçerik |
|---|---|
| `.csv` | Uzun biçim: `time,signal,value,unix_time`. `time` = kayıt başından sn, `unix_time` = epoch. Sinyal kimliği öneki kaynağı verir: `dbc:` (CAN çözülmüş), `a2l:` (CCP ölçümü), `gauge:`, `input:` (kullanıcı girişi), `cal:` (uygulanan kalibrasyon), `mil:` (Simulink). |
| `.events.csv` | `time,unix_time,kind,text`: BASLANGIC, DURAKLATMA, DEVAM, MARKER, HATA, KALIBRASYON, bağlantı olayları… |
| `.asc` | Ham CAN kareleri, Vector ASCII (python-can `ASCWriter`); Rx/Tx, standart+extended ID. İlk kare gelince oluşur. |
| `.meta.json` | Üst veri: ad, kullanıcı/rol, mod (REAL/MIL/VIRTUAL), bağlantı, DBC/A2L dosya adı+boyut+SHA-256, Simulink model, sinyal tablosu (birim/kaynak/zaman tabanı), istatistik, `status` (`recording` → çökerse `recovered`; `complete`; `error`). |
| `_girisler.csv` | Kullanıcı girişleri (mevcut `InputLog`). |

## Veri kaybı denetimi
`record()` çağıranı bloklamaz; kayıt, sınırlı kuyruk + ayrı yazma iş parçacığıyla yazılır. Kuyruk dolarsa `dropped` artar ve arayüzde (REC çipi, Veri kaydı kartı) görünür. Disk hatası `error` olarak görünür ve kayıt durur. CSV ve olay dosyası her saniye flush edilir; beklenmedik kapanışta en çok ~1 sn veri kaybolur, oturum listesinde "KURTARILDI" görünür.

## Dışa aktarma (`app/session_export.py`) — formatlar birbirinin yerine geçmez
* **MDF4 (.mf4)** – fiziksel sinyaller; her sinyal kendi zaman damgalarıyla ayrı kanal grubunda; ad, birim, kaynak/zaman tabanı açıklamada. Sürüm 4.10. **AVL Concerto ile uyumluluk DOĞRULANMADI** (Concerto yok; MDF sürüm desteği kamuya açık kaynaklardan teyit edilemedi). asammdf ile geri okuma testi var.
* **ASC (.asc)** – ham CAN. Fiziksel sinyal içermez.
* **LOG (.log)** – iki seçenek: (a) ASC içerikli `.log` (yalnızca uzantı farkı; hedef yazılımda doğrulanmadı), (b) can-utils `candump -L` biçimi `(zaman) kanal ID#VERİ`.
* **CSV** – uzun biçim (kayıt dosyası). **MAT** – sinyal başına `{time, values, unit, name, source}`.
