"""Test senaryosu paneli: JSON senaryo aç, çalıştır, durdur, sonuç tablosu ve rapor.

Senaryo iş parçacığında koşar; GUI'ye dokunan her işlem (sinyal yazma, model komutu, işaret) ``GuiInvoker`` ile GUI
iş parçacığında yapılır, sonuçlar zamanlayıcıyla tabloya yansır. Karar kuralları: bkz. app/sim_bridge/scenario.py
(limit uydurulmaz; gereksinimsiz kontrol SKIPPED)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.sim_bridge import scenario as sc
from app.ui.dash_widgets import make_card


class GuiInvoker(QObject):
    """Başka iş parçacığından GUI iş parçacığında bir çağrılabilir çalıştırıp sonucunu bekler."""
    _call = Signal(object)

    def __init__(self):
        super().__init__()
        self._call.connect(self._run, Qt.BlockingQueuedConnection)

    def _run(self, box):
        try:
            box["r"] = box["fn"]()
        except BaseException as exc:  # noqa: BLE001 - çağıran iş parçacığında yeniden yükseltilir
            box["e"] = exc

    def invoke(self, fn):
        box = {"fn": fn}
        self._call.emit(box)
        if "e" in box:
            raise box["e"]
        return box.get("r")


class MainWindowContext:
    """ScenarioRunner bağlamı: MainWindow'un mevcut yollarını kullanır (ikinci altyapı yok)."""

    def __init__(self, win, invoker: GuiInvoker):
        self.win, self.inv = win, invoker

    def get_signal(self, name: str):
        ent = self.win.latest_signals.get(name)
        return None if ent is None else ent[0]

    def set_signal(self, name: str, value: float):
        from app.dashboard_config import SOURCE_CAN, Binding
        if "." not in name:
            raise ValueError(f"Sinyal adı MESAJ.SINYAL biçiminde olmalı: {name}")
        msg, sig = name.split(".", 1)
        ok = self.inv.invoke(lambda: self.win._write_binding(Binding(SOURCE_CAN, msg, sig), value, "Senaryo"))
        if not ok:
            raise RuntimeError(f"{name} yazılamadı (bağlantı/yetki/DBC)")

    def model_command(self, cmd: str, arg: float = 0.0):
        def go():
            ctl = self.win.model_ctl
            if ctl is None:
                raise RuntimeError("Model denetimi bağlı değil (Ana Sayfa > Simulink Model > Bağlan)")
            ok = ctl.set_speed(arg) if cmd == "speed" else ctl.command(cmd, arg)
            if not ok:
                raise RuntimeError(f"Model komutu '{cmd}' bu durumda ({ctl.state}) geçersiz")
        self.inv.invoke(go)

    def marker(self, label: str):
        self.inv.invoke(lambda: self.win._on_record_marker(label))

    def log(self, text: str):
        self.inv.invoke(lambda: self.win._log_event("SENARYO", text))


class ScenarioPanel(QWidget):
    status = Signal(str)

    def __init__(self, win_provider, parent=None):
        super().__init__(parent)
        self._win = win_provider            # callable -> MainWindow (geç bağlanır)
        self._scenario = None
        self._runner = None
        self._invoker = GuiInvoker()
        self._shown = 0
        card, v, head = make_card("Test senaryosu", "flag")
        self.name_label = QLabel("Senaryo yüklenmedi.")
        self.name_label.setWordWrap(True)
        self.open_button = QPushButton("Senaryo Aç…")
        self.open_button.clicked.connect(self.open_dialog)
        self.run_button = QPushButton("Çalıştır")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.run)
        self.abort_button = QPushButton("Durdur")
        self.abort_button.setEnabled(False)
        self.abort_button.clicked.connect(self.abort)
        self.report_button = QPushButton("Raporu Kaydet…")
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(self.save_report)
        row = QHBoxLayout()
        for w in (self.open_button, self.run_button, self.abort_button, self.report_button):
            row.addWidget(w)
        row.addStretch(1)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Adım", "Durum", "Ayrıntı"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(110)
        self.verdict_label = QLabel("")
        v.addWidget(self.name_label)
        v.addLayout(row)
        v.addWidget(self.table)
        v.addWidget(self.verdict_label)
        out = QVBoxLayout(self)
        out.setContentsMargins(0, 0, 0, 0)
        out.addWidget(card)
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._refresh)

    def load(self, scenario: sc.Scenario):
        self._scenario = scenario
        self.name_label.setText(f"<b>{scenario.name}</b> — {len(scenario.steps)} adım. {scenario.description}")
        self.table.setRowCount(len(scenario.steps))
        for i, s in enumerate(scenario.steps):
            self.table.setItem(i, 0, QTableWidgetItem(f"{i + 1}. {sc.describe(s)}"))
            self.table.setItem(i, 1, QTableWidgetItem(""))
            self.table.setItem(i, 2, QTableWidgetItem(""))
        self.run_button.setEnabled(True)
        self.verdict_label.setText("")

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self.window(), "Senaryo aç", "", "JSON (*.json)")
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        try:
            self.load(sc.load_scenario(path))
            return True
        except sc.ScenarioError as exc:
            QMessageBox.warning(self.window(), "Senaryo", str(exc))
            return False

    def run(self):
        win = self._win()
        if self._scenario is None or win is None:
            return
        win.latest_signals_enabled = True
        ctx = MainWindowContext(win, self._invoker)
        self.load(self._scenario)
        self._runner = sc.ScenarioRunner(self._scenario, ctx)
        self._shown = 0
        self.run_button.setEnabled(False)
        self.abort_button.setEnabled(True)
        self.report_button.setEnabled(False)
        win._log_event("SENARYO", f"Senaryo başladı: {self._scenario.name}")
        self._runner.start()
        self._timer.start()

    def abort(self):
        if self._runner is not None:
            self._runner.abort()

    def _refresh(self):
        r = self._runner
        if r is None:
            return
        results = list(r.results)
        for res in results[self._shown:]:
            row = res.index - 1
            if 0 <= row < self.table.rowCount():
                self.table.item(row, 1).setText(res.status)
                self.table.item(row, 2).setText(res.detail)
        self._shown = len(results)
        if r.status != "RUNNING":
            self._timer.stop()
            self.abort_button.setEnabled(False)
            self.run_button.setEnabled(True)
            self.report_button.setEnabled(True)
            self.verdict_label.setText(f"Sonuç: {r.verdict}")
            win = self._win()
            if win is not None:
                win._log_event("SENARYO", f"Senaryo bitti: {self._scenario.name} → {r.verdict}")
                win.latest_signals_enabled = False
            self.status.emit(f"Senaryo bitti: {r.verdict}")

    def save_report(self):
        if self._runner is None:
            return
        path, _ = QFileDialog.getSaveFileName(self.window(), "Test raporu", "senaryo_raporu.txt", "Metin (*.txt)")
        if path:
            self.write_report(path)

    def write_report(self, path: str):
        import json
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._runner.report_text())
        with open(path + ".json", "w", encoding="utf-8") as f:
            json.dump(self._runner.report_dict(), f, ensure_ascii=False, indent=2)
