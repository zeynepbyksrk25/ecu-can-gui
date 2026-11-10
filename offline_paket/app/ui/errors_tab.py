"""CAN bağlantı sağlığı: bağlantının GERÇEK zamanlı durumu tek bakışta görünür.

Hata günlüğü artık ayrı bir tablo değildir: kaynağı ne olursa olsun her hata zaten
``app.eventlog.EventLog``'a "HATA" kategorisiyle düşer (bkz. MainWindow._log_event) ve
Tanılama ve Oturum sayfasındaki tek olay günlüğünde "Yalnız hatalar" süzgeciyle görünür.
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.dash_widgets import make_card


class ErrorsTab(QWidget):
    def __init__(self):
        super().__init__()
        health_card, hv, _h = make_card("CAN bağlantı durumu", "plane")
        self.health_label = QLabel("● Bağlı değil")
        self.health_label.setObjectName("chipBad")
        self.health_label.setWordWrap(True)
        hv.addWidget(self.health_label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(health_card)

    # ---- MainWindow'un çağırdığı erişimci ----------------------------
    def set_health(self, ok: bool, message: str):
        self.health_label.setText(f"● {message}")
        self.health_label.setObjectName("chipGreen" if ok else "chipBad")
        self.health_label.style().unpolish(self.health_label)
        self.health_label.style().polish(self.health_label)
