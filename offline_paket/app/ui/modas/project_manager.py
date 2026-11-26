"""Project Manager (Modas: F7) — kılavuz §2 "Creating a workbase" düzeni.

Sol: **Projects** ağacı (``Add new`` / ``Add existing``). Sağ: seçili projenin **Workbase** listesi (``New`` / ``Open`` /
``Edit`` / ``Delete``). Altta iki bilgi paneli: "Selected project information" ve "Selected workbase information".
Workbase çift tıklanınca (ya da ``Open``) ``workbase_opened`` yayılır; MainWindow A2L'yi yükler ve ECU'ya bağlanmayı dener.

Veri işleri ``app.modas_projects.ProjectStore``'dadır (Qt'den bağımsız, testli); burada yalnızca arayüz vardır.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from app import theme
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from app.modas_projects import HARDWARE, PROTOCOLS, ProjectError, ProjectStore, Workbase

BAUDRATES = [100_000, 125_000, 250_000, 500_000, 800_000, 1_000_000]


class WorkbaseDialog(QDialog):
    """"Workbase information" penceresi: ad, A2L, HEX, ECU, Seed&Key, protokol, baudrate, donanım, açıklama."""

    def __init__(self, wb: Workbase | None = None, parent=None, editing: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Workbase information")
        self.setMinimumWidth(520)
        wb = wb or Workbase(name="")
        form = QFormLayout()
        self.name = QLineEdit(wb.name)
        self.name.setEnabled(not editing)                   # ad = klasör adı: sonradan değişmez
        self.a2l = self._file_row(wb.a2l, "A2L dosyası seç", "A2L dosyaları (*.a2l)")
        self.hex = self._file_row(wb.hex, "HEX / S19 dosyası seç", "HEX dosyaları (*.hex *.s19 *.s28);;Tümü (*)")
        self.ecu = QLineEdit(wb.ecu)
        self.seedkey = self._file_row(wb.seedkey, "Seed&Key kütüphanesi seç", "Kütüphane (*.dll *.so);;Tümü (*)")
        self.protocol = QComboBox()
        self.protocol.addItems(PROTOCOLS)
        self.protocol.setCurrentText(wb.protocol)
        self.baud = QComboBox()
        for rate in BAUDRATES:
            self.baud.addItem(f"{rate / 1000:g} kbit/s", rate)
        idx = self.baud.findData(wb.baudrate)
        self.baud.setCurrentIndex(idx if idx >= 0 else BAUDRATES.index(500_000))
        self.hardware = QComboBox()
        self.hardware.addItems(HARDWARE)
        self.hardware.setCurrentText(wb.hardware)
        self.comment = QPlainTextEdit(wb.comment)
        self.comment.setFixedHeight(70)
        for label, w in (("Name:", self.name), ("A2L file:", self.a2l[0]), ("HEX file:", self.hex[0]), ("ECU:", self.ecu),
                         ("Seed&&Key library:", self.seedkey[0]), ("Communication protocol:", self.protocol),
                         ("Baudrate:", self.baud), ("Communication hardware:", self.hardware), ("Comment:", self.comment)):
            form.addRow(label, w)
        self.error = QLabel("")
        self.error.setStyleSheet(f"color:{theme.DANGER};")
        self.error.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(self.error)
        v.addWidget(buttons)
        self._base = wb

    def _file_row(self, text: str, title: str, flt: str):
        edit = QLineEdit(text)
        btn = QPushButton("…")
        btn.setFixedWidth(30)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, 1)
        h.addWidget(btn)

        def browse():
            path, _ = QFileDialog.getOpenFileName(self, title, edit.text(), flt)
            if path:
                edit.setText(path)
        btn.clicked.connect(browse)
        return row, edit

    def value(self) -> Workbase:
        wb = Workbase(name=self.name.text().strip(), created=self._base.created, a2l=self.a2l[1].text().strip(),
                      hex=self.hex[1].text().strip(), ecu=self.ecu.text().strip(), seedkey=self.seedkey[1].text().strip(),
                      protocol=self.protocol.currentText(), baudrate=int(self.baud.currentData()),
                      hardware=self.hardware.currentText(), comment=self.comment.toPlainText().strip())
        wb.path = self._base.path
        return wb


class ProjectManagerDialog(QDialog):
    workbase_opened = Signal(object, object)       # (Project, Workbase)
    settings_requested = Signal()

    def __init__(self, store: ProjectStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Project Manager")
        self.resize(940, 640)

        def tb(text, tip, fn):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            return b

        self.btn_add_new = tb("Add new", "Yeni proje oluştur (DATA / CONFIG / LOGFILES / MACRO klasörleriyle)", self._add_project)
        self.btn_add_existing = tb("Add existing", "Başka bir yerdeki Modas proje klasörünü listeye ekle", self._add_existing)
        self.btn_remove = tb("Remove project", "Projeyi listeden çıkar (dosyaları silmez)", self._remove_project)
        self.btn_new = tb("New", "Seçili projede yeni workbase oluştur", self._new_workbase)
        self.btn_open = tb("Open", "Workbase'i aç: A2L yüklenir, ECU'ya bağlanılır   (çift tık)", self._open_workbase)
        self.btn_edit = tb("Edit", "Seçili workbase'in ayarlarını düzenle", self._edit_workbase)
        self.btn_delete = tb("Delete", "Seçili workbase'i sil", self._delete_workbase)
        self.btn_settings = tb("Settings / Users…", "Kullanıcı, rol ve profiller", self.settings_requested.emit)

        bar = QHBoxLayout()
        for lab, btns in (("Project", (self.btn_add_new, self.btn_add_existing, self.btn_remove)),
                          ("Workbase", (self.btn_new, self.btn_open, self.btn_edit, self.btn_delete))):
            box = QGroupBox(lab)
            h = QHBoxLayout(box)
            for b in btns:
                h.addWidget(b)
            bar.addWidget(box)
        bar.addStretch(1)
        bar.addWidget(self.btn_settings)

        self.projects = QTreeWidget()
        self.projects.setHeaderLabel("Projects")
        self.projects.itemSelectionChanged.connect(self._on_project_selected)
        self.workbases = QTreeWidget()
        self.workbases.setHeaderLabel("Workbases")
        self.workbases.itemSelectionChanged.connect(self._on_workbase_selected)
        self.workbases.itemDoubleClicked.connect(lambda *_: self._open_workbase())

        self.project_info = self._info_panel("Selected project information", ("Path", "Name", "Created", "Comment"))
        self.workbase_info = self._info_panel(
            "Selected workbase information",
            ("Name", "Created", "A2L file", "HEX file", "ECU", "Seed&Key library", "Communication protocol",
             "Baudrate", "Communication hardware", "Comment"))
        self.status = QLabel("")
        self.status.setWordWrap(True)

        grid = QGridLayout()
        grid.addWidget(self.projects, 0, 0)
        grid.addWidget(self.workbases, 0, 1)
        grid.addWidget(self.project_info[0], 1, 0)
        grid.addWidget(self.workbase_info[0], 1, 1)
        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 2)
        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addLayout(grid, 1)
        v.addWidget(self.status)
        self.refresh()

    # ---- yardımcılar ----------------------------------------------------------------
    @staticmethod
    def _info_panel(title: str, keys: tuple):
        box = QGroupBox(title)
        form = QFormLayout(box)
        labels = {}
        for k in keys:
            lab = QLabel("—")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lab.setWordWrap(True)
            form.addRow(f"{k.replace('&', '&&')}:", lab)
            labels[k] = lab
        return box, labels

    @staticmethod
    def _fill(panel, values: dict):
        for k, lab in panel[1].items():
            v = values.get(k, "")
            lab.setText(str(v) if v not in ("", None) else "—")

    def _msg(self, text: str, error: bool = False):
        self.status.setStyleSheet(f"color:{theme.DANGER};" if error else "")
        self.status.setText(text)

    def selected_project(self):
        items = self.projects.selectedItems()
        return items[0].data(0, Qt.UserRole) if items else None

    def selected_workbase(self):
        items = self.workbases.selectedItems()
        return items[0].data(0, Qt.UserRole) if items else None

    def refresh(self, select_project: str | None = None, select_workbase: str | None = None):
        keep = select_project or (self.selected_project().name if self.selected_project() else None)
        self.projects.clear()
        for pr in self.store.list_projects():
            it = QTreeWidgetItem([pr.name])
            it.setData(0, Qt.UserRole, pr)
            it.setToolTip(0, pr.path)
            self.projects.addTopLevelItem(it)
            if pr.name == keep:
                it.setSelected(True)
        if not self.projects.selectedItems() and self.projects.topLevelItemCount():
            self.projects.topLevelItem(0).setSelected(True)
        self._on_project_selected(select_workbase)

    def _on_project_selected(self, select_workbase: str | None = None):
        pr = self.selected_project()
        self.workbases.clear()
        if pr is None:
            self._fill(self.project_info, {})
        else:
            self._fill(self.project_info, {"Path": pr.path, "Name": pr.name, "Created": pr.created, "Comment": pr.comment})
            try:
                wbs = self.store.list_workbases(pr.name)
            except ProjectError as exc:
                wbs = []
                self._msg(str(exc), True)
            for wb in wbs:
                it = QTreeWidgetItem([wb.name])
                it.setData(0, Qt.UserRole, wb)
                self.workbases.addTopLevelItem(it)
                if wb.name == select_workbase:
                    it.setSelected(True)
        self._on_workbase_selected()

    def _on_workbase_selected(self):
        wb = self.selected_workbase()
        has_pr, has_wb = self.selected_project() is not None, wb is not None
        for b, on in ((self.btn_remove, has_pr), (self.btn_new, has_pr), (self.btn_open, has_wb),
                      (self.btn_edit, has_wb), (self.btn_delete, has_wb)):
            b.setEnabled(on)
        if wb is None:
            self._fill(self.workbase_info, {})
            return
        self._fill(self.workbase_info, {
            "Name": wb.name, "Created": wb.created, "A2L file": wb.a2l, "HEX file": wb.hex, "ECU": wb.ecu,
            "Seed&Key library": wb.seedkey, "Communication protocol": wb.protocol,
            "Baudrate": f"{wb.baudrate / 1000:g} kbit/s", "Communication hardware": wb.hardware, "Comment": wb.comment})

    # ---- projeler -------------------------------------------------------------------
    def _add_project(self):
        name, ok = QInputDialog.getText(self, "New project", "Project name:")
        if not ok:
            return
        try:
            pr = self.store.create_project(name)
        except (ProjectError, OSError) as exc:
            QMessageBox.warning(self, "Project", str(exc))
            return
        self._msg(f"Proje oluşturuldu: {pr.path}")
        self.refresh(select_project=pr.name)

    def _add_existing(self):
        path = QFileDialog.getExistingDirectory(self, "Mevcut proje klasörünü seç")
        if not path:
            return
        try:
            pr = self.store.add_existing(path)
        except (ProjectError, OSError) as exc:
            QMessageBox.warning(self, "Project", str(exc))
            return
        self.refresh(select_project=pr.name)

    def _remove_project(self):
        pr = self.selected_project()
        if pr is None:
            return
        if QMessageBox.question(self, "Remove project", f"'{pr.name}' listeden çıkarılsın mı?\n(Dosyalar silinmez.)") != QMessageBox.Yes:
            return
        self.store.delete_project(pr.name, delete_files=False)
        self.refresh()

    # ---- workbase'ler ---------------------------------------------------------------
    def _new_workbase(self):
        pr = self.selected_project()
        if pr is None:
            return
        self._edit_dialog(pr, Workbase(name=""), create=True)

    def _edit_workbase(self):
        pr, wb = self.selected_project(), self.selected_workbase()
        if pr is not None and wb is not None:
            self._edit_dialog(pr, wb, create=False)

    def _edit_dialog(self, pr, wb: Workbase, create: bool):
        dlg = WorkbaseDialog(wb, self, editing=not create)
        while dlg.exec() == QDialog.Accepted:
            try:
                saved = self.store.save_workbase(pr.name, dlg.value(), create=create)
            except (ProjectError, OSError, ValueError) as exc:
                dlg.error.setText(str(exc))                  # pencere açık kalır, kullanıcı düzeltir
                continue
            self._msg(f"Workbase kaydedildi: {saved.path}")
            self.refresh(select_project=pr.name, select_workbase=saved.name)
            return

    def _delete_workbase(self):
        pr, wb = self.selected_project(), self.selected_workbase()
        if pr is None or wb is None:
            return
        if QMessageBox.question(self, "Delete workbase", f"'{wb.name}' ve klasörü silinsin mi?") != QMessageBox.Yes:
            return
        self.store.delete_workbase(pr.name, wb.name)
        self.refresh(select_project=pr.name)

    def _open_workbase(self):
        pr, wb = self.selected_project(), self.selected_workbase()
        if pr is None or wb is None:
            return
        self.workbase_opened.emit(pr, wb)
        self.accept()
