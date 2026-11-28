"""Kayıtların Excel'e (.xlsx) aktarılması: oturum bitince, CAN kaydı bitince ve elle.

Excel dosyaları YALNIZCA bilgisayara yazılır (``<veri klasörü>/oturum_kayitlari`` ya da ``can_loglari``); ECU'ya
(RAM/flaş) hiçbir şey gönderilmez. Üretim arka plan iş parçacığında yürür (ilerleme penceresiyle); kaynak CSV'ler
silinmez, Excel üretimi başarısız olsa da veri CSV'de kalır.
"""
from app.user_roles import ROL_ADI
import logging
import os
import time

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.log_export import SessionInfo, can_csv_to_xlsx, filter_by_time, write_session_workbook
from app.paths import data_path
from app.ui.background import run_with_progress

log = logging.getLogger(__name__)


class ExportMixin:
    _last_record_csv: str | None = None
    _last_excel: str | None = None
    _can_log_path: str | None = None

    def _session_info(self, record_csv: str | None) -> SessionInfo:
        st = self.session_tab
        return SessionInfo(name=st._session_name, operator=st._operator, started=st._started_at,
                           ended=st._ended_at, record_csv=record_csv)

    def _write_workbook(self, path: str, info: SessionInfo, events: list, history: list, inputs: list) -> bool:
        """Çalışma kitabını arka planda yazar. Başarısızlıkta olay günlüğüne HATA yazar, False döner."""
        try:
            stats = run_with_progress(self, "Excel dosyası hazırlanıyor…",
                                      lambda: write_session_workbook(path, info, events, history, inputs))
        except Exception as exc:  # noqa: BLE001 - disk dolu, dosya Excel'de açık (Windows kilidi) vb.
            log.exception("Excel dosyası yazılamadı: %s", path)
            self._log_event("HATA", f"Excel dosyası yazılamadı ({path}): {exc}. Veri CSV dosyasında duruyor.")
            return False
        self._last_excel = path
        self._log_event("OTURUM", f"Excel dosyası kaydedildi: {path} "
                                  f"({stats['rows']} parametre örneği, {stats['signals']} sinyal)")
        return True

    # ---- giriş kaydı (tüm sayfalar)
    def _record_input(self, page: str, kind: str, source: str, target: str, new_value, *, ok: bool = True,
                      detail: str = "", unit: str = "", **kw):
        """Bir kullanıcı girişini yapılandırılmış kayda ekler (kullanıcı/rol otomatik). Kayıt hatası asıl işlemi
        ASLA bozmaz."""
        try:
            self.input_log.add(page, kind, source, target, new_value, ok=ok, detail=detail, unit=unit,
                               user=self.current_user, role=ROL_ADI, **kw)
        except Exception:  # noqa: BLE001
            log.exception("giriş kaydı eklenemedi")
        # Başarılı sayısal CAN girişleri (Kontrol Paneli, sensör override, motor komutu) kayıtta da zaman serisi olarak görünür
        # (input:<MESAJ.SİNYAL>); kalibrasyon yazımları ayrıca cal: olarak yazıldığından burada tekrarlanmaz.
        rec = getattr(self, "session_recorder", None)
        if ok and rec is not None and rec.is_active and source == "CAN" and not page.startswith("Kalibrasyon"):
            try:
                v = float(new_value)
            except (TypeError, ValueError):
                return
            sid = f"input:{target}"
            rec.register_signal(sid, unit or "", "Kullanıcı girişi", "wall_clock")
            rec.record(sid, v)

    # ---- oturum bitince (otomatik)
    def _export_session_excel(self, record_csv: str | None) -> str:
        st = self.session_tab
        info = self._session_info(record_csv)
        events = filter_by_time(list(self.event_log.entries), st._started_at, None)
        history = filter_by_time(list(self.calibration_history.entries), st._started_at, None)
        inputs = self.input_log.since(st._started_at)
        if record_csv:
            path = os.path.splitext(record_csv)[0] + ".xlsx"
        else:
            path = os.path.join(data_path("oturum_kayitlari"), f"oturum_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
        return path if self._write_workbook(path, info, events, history, inputs) else ""

    # ---- elle: tüm olay günlüğü + kalibrasyon yazımları + son parametre kaydı
    def _on_excel_export_requested(self):
        default = os.path.join(data_path("oturum_kayitlari"), f"rapor_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "Excel'e aktar", default, "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        info = self._session_info(self._last_record_csv)
        info.notes.append("Elle dışa aktarma: TÜM sayfalardaki girişler, olay günlüğü ve kalibrasyon yazımları "
                          "(oturumla sınırlı değil).")
        if self._write_workbook(path, info, list(self.event_log.entries), list(self.calibration_history.entries),
                                self.input_log.since(None)):
            self.session_tab.set_record_info(f"Excel dosyası kaydedildi: {path}")
            QMessageBox.information(self, "Excel dosyası kaydedildi", f"Bilgisayara kaydedildi:\n{path}")

    # ---- CAN kaydı bitince
    def _export_can_excel(self, csv_path: str):
        if not csv_path or not os.path.exists(csv_path):
            return
        xlsx = os.path.splitext(csv_path)[0] + ".xlsx"
        try:
            n = run_with_progress(self, "CAN kaydı Excel'e çevriliyor…", lambda: can_csv_to_xlsx(csv_path, xlsx))
        except Exception as exc:  # noqa: BLE001
            log.exception("CAN kaydı Excel'e çevrilemedi")
            self._log_event("HATA", f"CAN kaydı Excel'e çevrilemedi: {exc}. Veri CSV dosyasında duruyor ({csv_path}).")
            return
        self._last_excel = xlsx
        self._log_event("BILGI", f"CAN kaydı Excel olarak kaydedildi: {xlsx} ({n} kare)")

    def _open_folder_of(self, path: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(path))))
