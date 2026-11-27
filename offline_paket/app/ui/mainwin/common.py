"""MainWindow parçalarının ortak sabitleri ve hata türleri."""
from app.ccp import codec as ccp_codec
from app.ccp import protocol as ccp_protocol

RX_POLL_INTERVAL_MS = 30  # UI thread'in queue'yu ne sıklıkla yokladığı
HEALTH_CHECK_INTERVAL_MS = 500  # bağlantının GERÇEKTEN sağlıklı olup olmadığı (sürekli izleme)
# Adaptör/sürücü sorunu bu kadar SANİYE boyunca KESİNTİSİZ sürerse "bağlantı
# koptu" denir (anlık/geçici hatalarda yanlış alarm vermemek için).
CONNECTION_LOSS_CONFIRM_S = 3.0
RECONNECT_INTERVAL_MS = 2000  # bağlantı koptuktan sonra otomatik yeniden bağlanma denemesi aralığı
SILENT_NOTICE_S = 3.0  # bu kadar süre mesaj gelmezse bağlantı şeridinde "Hat sessiz" uyarısı
CCP_AUTO_CONNECT_DELAY_MS = 300  # CAN bağlandıktan kaç ms sonra CCP otomatik bağlansın
# Güvenlik komutları (Acil Durdurma / Motor Durdur): CAN'da aynı kare, ilkinden sonra bu kadar kez daha ve bu
# aralıkla tekrarlanır; A2L/CCP'de iletişim hatasında bu kadar denemeye kadar yeniden yazılır.
SAFETY_REPEAT_COUNT = 4
SAFETY_REPEAT_MS = 20
SAFETY_A2L_ATTEMPTS = 3
# Uzun CCP işleri (harita/flaş/toplu yazma) arka plan iş parçacığında yürür. Bu süreden kısa sürenler
# (tek değer yazımı gibi) için iç olay döngüsüne hiç girilmez.
CCP_JOB_INLINE_S = 0.05
_CCP_IO_ERRORS = (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError, ccp_codec.UnknownDatatypeError, ValueError)


class CcpBusyError(ValueError):
    """Uzun bir CCP işlemi sürerken yenisi istendi."""
