# MIL – Simulink UDP protokolü

GUI (PySide6) ve Simulink aynı Windows bilgisayarda. CAN çerçeveleri UDP datagram olarak taşınır; DBC iki tarafta ortak kaynaktır (kodlama/çözme Python'da `app/dbc.py`, Simulink'te Vehicle Network Toolbox / `canpack`-`canunpack` ya da elle bit paketleme).
**Bu fiziksel CAN hattı değildir:** bitrate, bus-off, PCAN durumu yoktur. Bağlantı sağlığı heartbeat + veri akışıyla izlenir.

Tüm alanlar küçük-endian. Ayrıntı ve kod: `offline_paket/app/sim_protocol.py`.

| Ofset | Boyut | Alan |
|---|---|---|
| 0 | 2 | magic `0x4543` |
| 2 | 1 | sürüm = 1 |
| 3 | 1 | tür: 1=CAN, 2=heartbeat, 3=kontrol |
| 4 | 4 | sıra no (uint32) — kayıp tespiti |
| 8 | 8 | **simülasyon zamanı** (double, sn) |

CAN (toplam 30 B): `16 u32 id`, `20 u8 bayrak (b0=extended, b1=RTR)`, `21 u8 DLC (0..8)`, `22 8B veri`.
Heartbeat (20 B): `16 u8 durum (0 bilinmiyor,1 hazır,2 çalışıyor,3 duraklatıldı,4 durdu,5 hata)`, 3 B ayrılmış.
Kontrol (24 B, GUI→model): `16 u8 komut (1 start,2 pause,3 resume,4 stop,5 reset,6 hız)`, 3 B ayrılmış, `20 float32 argüman`.

Alıcı kuralları: boyut/magic/sürüm/tür/DLC>8/ID aralığı/NaN zaman hatalı ise paket **reddedilir ve sayılır** (`bad_packets`). Standart ID ≤ 0x7FF, extended ≤ 0x1FFFFFFF.
Varsayılan portlar: GUI dinler `25001`, model dinler `25000` (kanal dizesi `yerel_port:uzak_host:uzak_port`).

## Sağlık durumları
`waiting` (henüz paket yok; model başlamamış olabilir) → `ok` → `timeout` (2 sn veri yok: model durdu / UDP kaybı). Model sonradan başlar ya da yeniden başlarsa bağlantı kendiliğinden `ok` olur. Sıra numarasındaki boşluklar `lost_packets` olarak sayılır.

## Zaman tabanları
* MIL = paketteki **simülasyon zamanı** (`sim_time`).
* REAL = GUI'nin monotonik/wall alım zamanı. Kullanıcı kayıtları = wall-clock.
Kayıt dosyasında CAN/çözülmüş sinyaller GUI alım zamanıyla (unix_time) yazılır; simülasyon zamanı ayrı `mil:sim_time` sinyali olarak tutulur — karıştırılmaz.

## Doğrulama durumu
Bu protokol yalnızca sahte model (`tests/fake_simulink.py`) ile test edilmiştir; **gerçek MATLAB/Simulink ile doğrulanmadı**.
