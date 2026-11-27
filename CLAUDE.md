# ecu-can-gui

PySide6 tabanlı ECU Test & Calibration uygulaması (`offline_paket/`). Görev kapsamı: `docs/GOREV.md`.

## Otonom mod (kullanıcı "sabaha kadar çalış" dediğinde geçerli)
- Kullanıcıya soru sorma, onay bekleme. Belirsizlikte en doğru/güvenli mühendislik kararını ver, `docs/DECISIONS.md`'ye gerekçesiyle yaz, devam et.
- Sıra: `docs/GOREV.md` bölüm 10 Aşama 1→4, sonra bölüm 11.12 MIL aşama 1→6. Her aşama: mevcut kodu incele → uygula → test yaz/çalıştır → `docs/PROGRESS.md` güncelle → commit → `git push -u origin <geçerli dal>` (ağ hatasında 4 denemeye kadar backoff).
- Mevcut testleri bozma; kırılırsa düzelt. Testi atlama/devre dışı bırakma yok. Çalışmayan şeyi "bitti" yazma; bilinen eksikleri `PROGRESS.md`'ye açıkça yaz.
- Burada doğrulanamayanlar (gerçek MATLAB/Simulink, AVL Concerto, PCAN donanımı): sahte/simüle yapıyla test et ve "gerçek ortamda doğrulanmadı" diye işaretle; uyumluluk iddia etme.
- Sinyal adı, birim, limit uydurma; DBC/A2L/mevcut koddan al. Mevcut sınıfları yeniden kullan, ikinci altyapı kurma.
- PR açma (kullanıcı istemedikçe). Sır/anahtar commit etme.
- Tüm aşamalar bitince durma: test kapsamı, hata yolları, performans (büyük kayıtlar), UX cilası, dokümantasyon ve kod sadeleştirme turları yap; her turu `PROGRESS.md`'ye yaz.
- Takılırsan alternatif yol bul, kararı kaydet, sonraki maddeye geç; sonunda geri dön.
- Her oturum başında ve context özetlendikten sonra `docs/GOREV.md`, `docs/PROGRESS.md`, `docs/DECISIONS.md` dosyalarını yeniden oku.
