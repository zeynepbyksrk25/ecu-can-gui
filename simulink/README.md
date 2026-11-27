# Simulink tarafı (MIL)

Protokol: `../docs/MIL_PROTOKOL.md`. Modelde **UDP Send/Receive** blokları (Instrument Control Toolbox) ya da `udpport` ile MATLAB Function bloğu kullanılır. Alıcı tarafta paketi `uint8` vektör olarak alıp 16 baytlık başlığı ve CAN yükünü ayrıştırın; gönderirken aynı yapıyı doldurun. Heartbeat'i en az 2 sn'de bir (öneri 0,5 sn) gönderin.

MATLAB tarafı örnek betikler `matlab/` altında (MATLAB'da DOĞRULANMADI).
