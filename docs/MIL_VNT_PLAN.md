# MIL – Vehicle Network Toolbox (CAN Pack/Unpack) + UDP Uygulama Planı

## 0. Durum özeti (son güncelleme 2026-11-28)

| Alan | Durum |
|---|---|
| MIL UDP haberleşme altyapısı (`sim_protocol.py`, `sim_bus.py`), model paneli, kayıt/analiz, senaryo | **Yapıldı** (sahte modelle test; gerçek MATLAB'da doğrulanmadı) |
| **Kalibrasyon: `.m` (Simulink.Parameter/LookupTable) + MATLAB Engine, modelde değişiklik YOK** | **Yapıldı** (PR #37; sahte engine ile test; gerçek MATLAB'da doğrulanmadı) — bkz. bölüm 8 |
| **CAN giriş/çıkış: VNT CAN Pack/Unpack + UDP (bu planın 4.x bölümleri)** | **YAPILMADI — sıradaki iş** |

Kullanıcının kararları (yeniden sorma): kalibrasyon MATLAB Engine ile yapılır (UDP parametre kanalı gerekmez); GUI, modelin çalıştığı AÇIK MATLAB oturumuna bağlanır (`matlab.engine.shareEngine`); parametre `.m` dosyası GUI'de dosya seçiciyle verilir; parametre listesinde harita/eğri de vardır; CAN tarafı VNT Pack/Unpack ile; modelde (algoritmada) değişiklik istenmez, yalnızca OpenECU CAN blokları yerine `MIL_IO` sarmalayıcısı eklenir.

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
- Kalibrasyon bu bölümün konusu DEĞİLDİR: `.m` + MATLAB Engine ile yapıldı (bölüm 8). JSON manifest/UDP parametre kanalı (tür 4) yedek yol olarak kalır, genişletilmez.

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
- GUI/arayüz değişikliği gerekmez (Mod = MIL mevcut). ACK ile "uygulanan değer" geri bildirimi (sensör override) ayrı iştir (`PROGRESS.md` "Eksik" notlarına bak). Model tarafında UDP parametre paketlerini (tür 4) işleyen Simulink örneği artık GEREKMEZ (kalibrasyon Engine ile).

## 8. Yapılmış iş: .m + MATLAB Engine kalibrasyonu (ihtiyaç halinde bakın, yeniden yazmayın)
- Kod: `offline_paket/app/sim_bridge/engine_params.py` (`parse_listing`, `build_summary` → sentetik `A2LSummary`, `load_from_engine`, `EngineParamClient`), `simulink/matlab/mil_list_params.m` (base workspace → JSON), `matlab_ctl.MatlabEngineBackend(attach=True)` (+ `engine`, `lock`, `model`), `ui/mainwin/calibration.py` (`_on_sim_mfile_requested`, `_apply_engine_params`), `ui/connection_tab.py` ("Parametre dosyası (.m)…"), model paneli "MATLAB (açık oturuma bağlan)". Testler: `tests/test_engine_params.py`.
- Akış: model paneli MATLAB Engine ile bağlan → `.m` seç (engine'de `run`) → liste → sentetik A2L → mevcut Kalibrasyon/Harita Editörü/geçmiş; yazma `NAME.Value = …` / `NAME.Table.Value(r,c) = …` + geri okuma doğrulaması; model çalışırken `SimulationCommand=update`.
- Kurallar: çalışırken `StorageClass=Auto` yazılamaz; Min/Max dışı reddedilir; desteklenen: skaler, vektör/matris, 1B/2B tablo (Explicit values); `fixdt`/enum/struct/Reference eksen/3B+ atlanır ve listelenir; breakpoint değerleri yalnız okunur. GUI ekseni: axes[0]=sütun=`Breakpoints{2}`, axes[1]=satır=`Breakpoints{1}`.
- **Gerçek MATLAB'da doğrulanmadı:** `LookupTable.Table.Value/Breakpoints` alan adları, `jsonencode` çıktı biçimi, `update` ile çalışan modelde değerin gerçekten uygulanması, `connect_matlab`.
- Bilinen eksikler: model yeniden bağlanınca `.m` yeniden seçilmeli; yalnız base workspace (data dictionary/model workspace taranmaz); breakpoint düzenleme yok; paylaşılan oturum adı seçimi yok (ilk oturum alınır).
- Kullanıcı örneğindeki `IGN_ON_SPD.DataTpe='single'` yazım hatasıdır (`DataType`); MATLAB'da hata verir, kodda düzeltilecek bir şey yok.

## 9. Ajan çalışma kuralları (hatırlatma)
- Önce `CLAUDE.md`, `docs/GOREV.md`, `docs/PROGRESS.md`, `docs/DECISIONS.md` oku. Her adım: incele → uygula → test → `PROGRESS.md` → commit. Mevcut testleri bozma, atlama yok. PR yalnızca kullanıcı isterse. Sır commit etme.
- Test ortamı (bu bulut ortamında gerekirse): `pip install` ile `requirements.lock.txt` sürümleri (`pya2ldb`, PySide6, cantools, python-can, pyqtgraph …) ve `libegl1`; testler `QT_QPA_PLATFORM=offscreen python -m pytest …` ile çalışır.
- Bu ortamda MATLAB/Simulink/VNT/PCAN yok: sahte yapıyla test et, "gerçek ortamda doğrulanmadı" diye işaretle. Sinyal adı, birim, limit, yön uydurma.
