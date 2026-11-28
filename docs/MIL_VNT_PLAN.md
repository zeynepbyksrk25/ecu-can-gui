# MIL – Vehicle Network Toolbox (CAN Pack/Unpack) + UDP Uygulama Planı

> Bu doküman repodaki yapay zekâ ajanı (ve geliştirici) içindir. Önce `CLAUDE.md`, `docs/GOREV.md` (bölüm 11), `docs/MIL_PROTOKOL.md`, `docs/PROGRESS.md`, `docs/DECISIONS.md` okunmalıdır. Bu plan **yeni bir altyapı kurmaz**; mevcut MIL UDP altyapısının (`app/sim_protocol.py`, `app/sim_bus.py`, `app/sim_bridge/`) Simulink tarafını tamamlar.

## 1. Amaç ve bağlam

- Kullanıcı gerçek ECU'da (OpenECU, PEAK PCAN-USB, CCP + DBC) bu GUI'yi kullanıyor. OpenECU'nun Simulink CAN blokları donanım sürücüsüne bağlı olduğundan **MIL modelinde yoktur**.
- MIL modelinde yalnızca algoritma ve giriş/çıkışlar var. MIL için **A2L ve DBC üretilmiyor**; DBC, gerçek ECU'da kullanılan dosyadır ve MIL'de de aynen kullanılır.
- MIL'de donanım yok: yalnızca MATLAB/Simulink ve GUI, aynı Windows bilgisayarda.
- **Karar:** Simulink tarafında CAN (bit) paketleme **Vehicle Network Toolbox (VNT) `CAN Pack` / `CAN Unpack`** bloklarıyla yapılır; taşıma **UDP** (mevcut protokol, `docs/MIL_PROTOKOL.md`). VNT'nin donanım bloklarına (`CAN Configuration/Transmit/Receive`) ve MathWorks sanal CAN kanalına **bağımlılık yoktur** (sanal kanal Python'dan görünmez).
- GUI tarafı değişmez: Mod = MIL, kanal `25001:127.0.0.1:25000`, aynı DBC. Temel prensip: MIL ve REAL aynı GUI/sinyal adları/kalibrasyon/kayıt altyapısı; yalnızca backend değişir.

## 2. Hedef mimari

```
GİRİŞ (GUI → model)
UDP Receive(25000) → [MATLAB Fn: paket çöz] → CAN mesajı → CAN Unpack(DBC) → sinyaller → ALGORİTMA

ÇIKIŞ (model → GUI)
ALGORİTMA → sinyaller → CAN Pack(DBC) → CAN mesajı → [MATLAB Fn: paket kur] → UDP Send(→25001)
                                         + Heartbeat (tür 2) ≤ 0,5 sn'de bir
```

- Algoritma alt sistemi OpenECU'dan ayrılır; giriş/çıkış portları aynı kalır. Tüm CAN/UDP işi bir **`MIL_IO`** sarmalayıcı alt sisteminde toplanır. Gerçek ECU'ya dönerken yalnızca `MIL_IO` OpenECU CAN bloklarıyla değiştirilir.
- Her giriş mesajı için bir `CAN Unpack`, her çıkış mesajı için bir `CAN Pack` bloğu; mesaj periyodu o bloğun örnek zamanıyla (ör. 10/20/100 ms) verilir.
- Hız: Simulink gerçek zamandan hızlı koşar; pacing için Simulink Simulation Pacing / GUI hız seçici (`matlab_ctl.py`) kullanılır. Hız yalnızca GUI timer'ı ile taklit edilmez.

## 3. Protokol özeti (kaynak doğrusu: `app/sim_protocol.py`)

Küçük-endian. Başlık 16 B: `magic u16=0x4543, sürüm u8=1, tür u8, sıra u32, sim_time double`. CAN paketi 30 B: başlık + `id u32, bayrak u8 (b0=extended,b1=RTR), DLC u8, veri[8]`. Heartbeat 20 B: başlık + `durum u8` + 3 B ayrılmış (1 hazır, 2 çalışıyor, 3 duraklatıldı, 4 durdu, 5 hata). Kontrol 24 B (GUI→model): `komut u8` (1 start,2 pause,3 resume,4 stop,5 reset,6 hız), `float32 arg`. Parametre paketi tür 4 (bkz. `PARAM_BODY`). Hatalı paket reddedilir ve sayılır. Mevcut örnek: `simulink/matlab/mil_send_can.m`.

## 4. Yapılacaklar (sırayla; her adım: incele → uygula → test → `PROGRESS.md` → commit → push)

### 4.1 MATLAB paket işlevleri (`simulink/matlab/`)
Simulink MATLAB Function bloğunda **kod üretimi uyumlu** (Embedded MATLAB alt kümesi; `typecast`, sabit boyutlu `uint8` vektörler; dinamik boyut/çağrı yok) yazılır:
- `mil_pack_can_packet(seq, simTime, id, extended, dlc, data8) → uint8[30]`
- `mil_unpack_can_packet(pkt, len) → valid, id, extended, rtr, dlc, data8` (magic/sürüm/tür/DLC>8/ID aralığı doğrulaması, `sim_protocol.decode` ile aynı kurallar)
- `mil_pack_heartbeat(seq, simTime, state) → uint8[20]`
- `mil_unpack_control(pkt, len) → valid, cmd, arg` (Start/Pause/Stop/hız komutlarını modele iletmek için)
- Sıra numarası ve `sim_time` (Simulink `get_param`/`Clock` bloğu girişi) bu fonksiyonların dışında üretilir.

### 4.2 Python tarafı birebir doğrulama (MATLAB'sız)
MATLAB bu ortamda yok. Bu yüzden:
- `.m` fonksiyonlarının **bayt düzenini** Python'da bağımsız yeniden üreten bir referans test yazın (`tests/test_mil_matlab_layout.py`): `sim_protocol.encode_*` çıktısı ile `.m` kaynağındaki alan ofset/tip sabitleri (örn. metin ayrıştırarak ofset tablosu) tutarlı mı. Ortak sabitler tek tabloda (`simulink/matlab/mil_protocol_spec.json` gibi) tutulup hem test hem `.m` dokümanı bu tabloya dayanır (ikinci kaynak doğruluğu oluşturma).
- Ek: örnek paket vektörleri (`simulink/matlab/testvectors.json`) — Python `encode_*` ile üretilir; MATLAB'da kullanıcı `assert(isequal(...))` ile doğrulayabilsin diye `simulink/matlab/test_mil_packets.m` yazılır (**MATLAB'da çalıştırılmadı** diye işaretlenir).

### 4.3 VNT Pack/Unpack ↔ paket köprüsü
- Bu kısım **belirsizdir** (aşağıda 6): `CAN Pack` çıkışındaki CAN mesaj veri tipinden (`ID, Extended, Length, Data`) paket kurmak; gelen bayt vektöründen `CAN Unpack` girişine uygun CAN mesajı üretmek.
- Çıkış (Pack → UDP): `Bus Selector` ile `ID/Extended/Length/Data` alanlarını ayırıp `mil_pack_can_packet`'e verme tarifi yazılır.
- Giriş (UDP → Unpack): CAN mesajı bir `Bus Creator`/MATLAB Function çıkış veri tipiyle üretme tarifi yazılır. **Çalışmazsa yedek:** giriş tarafında DBC'den **elle bit çözümleme** üreten MATLAB Function (karma kullanım; çıkışta `CAN Pack` kalır). Kararı `DECISIONS.md`'ye yaz.

### 4.4 DBC'den kurulum listesi/otomasyon
- `simulink/matlab/mil_make_io_plan.py` (veya `app/` altında küçük CLI): DBC'yi `app/dbc.py` ile okuyup (yeni DBC ayrıştırıcı yazma) hangi mesaj ID/ad/periyot/sinyaller **giriş (Unpack)** ve **çıkış (Pack)** olur, bir tablo (Markdown/CSV) çıkarır. Yön ayrımı için node/gönderici bilgisi DBC'de varsa onu kullan; yoksa kullanıcıdan gelen bir yön listesi (JSON) kabul et — **yön tahmini uydurma**.
- Kalibrasyon: algoritma sabitleri Simulink'te **tunable** (`Simulink.Parameter`) yapılır; JSON manifest şablonu (`app/sim_bridge/parameters.py` biçimi) DBC/A2L'den üretilemeyen kısımlar için elle doldurulacak alanlarla boş şablon olarak üretilir.

### 4.5 Kılavuz
- `simulink/README.md` genişletilir: blok blok kurulum (Library Browser yolu, `CAN Pack/Unpack` parametreleri, `UDP Send/Receive`, örnek zamanları, heartbeat, pacing, MIL_IO sarmalayıcı, gerçek ECU'ya dönüş).
- UDP blok sağlayıcısı (DSP System Toolbox veya Instrument Control Toolbox `UDP Send/Receive`) **sürüme göre değişebilir**; kullanıcıdaki kurulu toolbox'a göre iki yol da anlatılır.

### 4.6 Sahte model ile uçtan uca test
- `tests/fake_simulink.py` zaten var; VNT'nin yaptığı işi (DBC ile kodlama) `app/dbc.py` ile yapıp aynı bayt düzeniyle gönderdiği mevcut testler korunur. Yeni test: 4.1'deki paket sözleşmesini kullanan model-benzeri akış (girişler → algoritma stub → çıkışlar) ile GUI Dashboard/Kontrol Paneli/kayıt zinciri çalışır (mevcut `test_mil_integration.py` genişletilir).
- **Mevcut testleri bozma; atlama/devre dışı bırakma yok.**

## 5. Kabul ölçütleri
1. `.m` paket işlevleri ile Python `sim_protocol` arasındaki bayt düzeni uyumu testle kanıtlı (yukarıdaki 4.2).
2. DBC'den giriş/çıkış mesaj tablosu üretilir (yön yoksa açıkça "belirsiz" der).
3. `simulink/README.md` ile kullanıcı MATLAB'da modeli sıfırdan kurabilir (adımlar tutarlı, belirsiz noktalar işaretli).
4. Tüm testler geçer; `PROGRESS.md` ve `DECISIONS.md` güncel.

## 6. DOĞRULANMAMIŞ / belirsiz noktalar (uydurma, açıkça işaretle)
- Bu ortamda **MATLAB/Simulink/VNT yok**; hiçbir `.m` veya blok yapılandırması gerçek ortamda doğrulanmadı. Dokümanlarda "gerçek MATLAB'da doğrulanmadı" yaz.
- `CAN Pack/Unpack` blokları **donanım/`CAN Configuration` olmadan** çalışıyor mu — varsayım; çalışmazsa yedek = elle bit paketleme (`DECISIONS.md`'ye yaz).
- CAN mesaj veri tipinin (Bus) alan adları ve bayt vektöründen CAN mesajı üretme yolu sürüme göre değişir; adları "kontrol edin" notuyla yaz, kesin parametre adı uydurma.
- Sinyal veri tipleri (genelde `double`), mesaj periyotları ve yönler DBC/kullanıcıdan alınır; **sinyal adı, birim, limit uydurma**.

## 7. Dışarıda kalanlar
- GUI/arayüz değişikliği gerekmez (Mod = MIL mevcut). ACK ile "uygulanan değer" geri bildirimi (sensör override) ve model tarafında parametre paketlerini (tür 4) işleyen Simulink örneği ayrı iştir (`PROGRESS.md` "Eksik" notlarına bak); bu plan bittikten sonra ele alınır.
