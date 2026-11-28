"""Kullanıcı rolü: uygulamada TEK rol vardır, **Mühendis**. Operatör ve Yönetici rolleri kaldırıldı; yetki denetimi,
rol seçimi ve "yetki yok" uyarıları yoktur. Rol adı yalnızca denetim kayıtlarına (olay günlüğü, kalibrasyon geçmişi, kayıt
üst verisi, giriş kaydı) yazılır.

Bu bir kimlik doğrulama (authentication) sistemi DEĞİLDİR: offline, tek kullanıcılı bir masaüstü aracında şifre kontrolü
anlamsızdır. Riskli işlemler (flaş yazma, override) rol yerine açık onay/anahtarla korunur.
"""

ROL_ADI = "Mühendis"
