"""Test kayıtlarını (oturum parametre kaydı, CAN kaydı, olay günlüğü, kalibrasyon yazımları) Excel'e (.xlsx)
çevirir; testlerden SONRA bilgisayarda incelemek içindir.

ÖNEMLİ: Burası yalnızca BİLGİSAYARA dosya yazar. Kayıtlar ECU'ya (RAM ya da flaş) hiçbir zaman gönderilmez;
ECU'ya yazma yalnızca kullanıcının açıkça başlattığı kalibrasyon işlemleridir ve bu modülle ilgisi yoktur.

Kaynak CSV'ler oturum sırasında SÜREKLİ yazılır (çökmede veri kaybolmasın); Excel dosyası kayıt bitince bu CSV'lerden
üretilir ve CSV'ler silinmez.
"""
from __future__ import annotations

import csv
import datetime
import math
import os
import time
from dataclasses import dataclass, field

from app.xlsx_export import XlsxWorkbook

WIDE_MAX_SIGNALS = 250          # geniş tablo: Excel'in sütun sınırı (16.384) yerine okunabilirlik sınırı
WIDE_STEP_S = 1.0               # geniş tablo: satır aralığı (saniye)


def _fmt_time(t: float | None) -> str:
    return "" if t is None else time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(t))


def _dt(t: float) -> datetime.datetime:
    """Unix zamanı -> yerel, saat dilimsiz datetime (Excel hücresi için)."""
    return datetime.datetime.fromtimestamp(t)


@dataclass
class SignalStat:
    count: int = 0
    first_t: float = math.inf
    last_t: float = -math.inf
    vmin: float = math.inf
    vmax: float = -math.inf
    total: float = 0.0

    def add(self, t: float, v: float):
        self.count += 1
        self.first_t = min(self.first_t, t)
        self.last_t = max(self.last_t, t)
        self.vmin = min(self.vmin, v)
        self.vmax = max(self.vmax, v)
        self.total += v

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else float("nan")


def _iter_record_rows(csv_path: str):
    """Oturum kaydı CSV'sinden (time, signal, value, unix_time) satırları; bozuk satırlar atlanır."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)                                     # başlık
        for row in reader:
            if len(row) < 3:
                continue
            try:
                t, v = float(row[0]), float(row[2])
                u = float(row[3]) if len(row) > 3 and row[3] else None
            except ValueError:
                continue
            yield t, row[1], v, u


def record_stats(csv_path: str) -> tuple[dict, int]:
    """(sinyal -> SignalStat, toplam satır). Tek geçiş, bellekte yalnızca sinyal başına birkaç sayı."""
    stats: dict[str, SignalStat] = {}
    n = 0
    for t, sig, v, _u in _iter_record_rows(csv_path):
        stats.setdefault(sig, SignalStat()).add(t, v)
        n += 1
    return stats, n


@dataclass
class SessionInfo:
    name: str = ""
    operator: str = ""
    started: float | None = None
    ended: float | None = None
    record_csv: str | None = None
    notes: list = field(default_factory=list)


def _write_summary(wb: XlsxWorkbook, info: SessionInfo, rows: int, n_signals: int, events: list, history: list):
    errors = sum(1 for e in events if e.category == "HATA")
    ram = sum(1 for h in history if not h.persistent)
    flash = sum(1 for h in history if h.persistent)
    dur = (info.ended - info.started) if info.started and info.ended else None
    sh = wb.sheet("Özet", ["Alan", "Değer"], widths=[34, 70], formats=["bold", None], autofilter=False)
    items = [
        ("Test / oturum adı", info.name or "(adsız)"),
        ("Operatör", info.operator or "-"),
        ("Başlangıç", _fmt_time(info.started)),
        ("Bitiş", _fmt_time(info.ended)),
        ("Süre (sn)", round(dur, 1) if dur is not None else ""),
        ("Parametre kaydı: örnek sayısı", rows),
        ("Parametre kaydı: sinyal sayısı", n_signals),
        ("Olay sayısı", len(events)),
        ("  bunlardan HATA", errors),
        ("Kalibrasyon yazımı (RAM)", ram),
        ("Kalibrasyon yazımı (FLAŞ)", flash),
        ("Kaynak CSV", info.record_csv or "-"),
        ("Excel oluşturulma", _fmt_time(time.time())),
        ("", ""),
        ("NOT", "Bu dosya yalnızca bilgisayarınıza kaydedilir; kayıtlar ECU'ya (RAM/flaş) yazılmaz."),
        ("NOT", "Sayfalar: Sinyal özeti, Parametre kaydı (uzun biçim), Geniş tablo (1 sn, son değer korunur), "
                "Olay günlüğü, Kalibrasyon yazımları."),
    ]
    for note in info.notes:
        items.append(("NOT", note))
    for k, v in items:
        sh.row([k, v])


def _write_signal_summary(wb: XlsxWorkbook, stats: dict):
    sh = wb.sheet("Sinyal özeti", ["Sinyal", "Örnek", "İlk (sn)", "Son (sn)", "Min", "Maks", "Ortalama"],
                  widths=[44, 10, 12, 12, 14, 14, 14])
    for sig in sorted(stats):
        s = stats[sig]
        sh.row([sig, s.count, round(s.first_t, 4), round(s.last_t, 4), s.vmin, s.vmax, s.mean])


def _write_record_long(wb: XlsxWorkbook, csv_path: str):
    sh = wb.sheet("Parametre kaydı", ["Tarih/saat", "Süre (sn)", "Sinyal", "Değer"],
                  widths=[24, 12, 44, 16], formats=["datetime", "seconds", None, None])
    for t, sig, v, u in _iter_record_rows(csv_path):
        sh.row([_dt(u) if u is not None else None, t, sig, v])


def _write_record_wide(wb: XlsxWorkbook, csv_path: str, signals: list, step: float = WIDE_STEP_S):
    """Her satır bir zaman dilimi (step sn); sütunlar sinyaller. Dilimde örnek yoksa son bilinen değer korunur
    (sample & hold): Excel'de tek zaman ekseniyle doğrudan grafik çizilebilir."""
    cols = signals[:WIDE_MAX_SIGNALS]
    index = {s: i for i, s in enumerate(cols)}
    sh = wb.sheet("Geniş tablo", ["Süre (sn)"] + cols, widths=[12] + [max(12, min(30, len(c) + 2)) for c in cols],
                  formats=["seconds"] + [None] * len(cols))
    current: list = [None] * len(cols)
    bucket = None
    for t, sig, v, _u in _iter_record_rows(csv_path):
        i = index.get(sig)
        if i is None:
            continue
        b = int(t // step)
        if bucket is None:
            bucket = b
        while bucket < b:                                      # biten dilimleri yaz (boş dilimler de dahil)
            sh.row([round(bucket * step, 6)] + current)
            bucket += 1
        current[i] = v
    if bucket is not None:
        sh.row([round(bucket * step, 6)] + current)


def _write_events(wb: XlsxWorkbook, events: list):
    sh = wb.sheet("Olay günlüğü", ["Tarih/saat", "Kategori", "Kullanıcı", "Rol", "Mesaj"],
                  widths=[24, 16, 18, 14, 110], formats=["datetime", None, None, None, None])
    for e in events:
        sh.row([_dt(e.timestamp), e.category, e.user, e.role, e.message])


def _write_history(wb: XlsxWorkbook, history: list):
    sh = wb.sheet("Kalibrasyon yazımları",
                  ["Tarih/saat", "Tür", "Kullanıcı", "Rol", "Nesne", "Eski değer", "Yeni değer", "Birim", "Açıklama"],
                  widths=[24, 8, 18, 14, 40, 14, 14, 10, 70], formats=["datetime"] + [None] * 8)
    for h in history:
        sh.row([_dt(h.timestamp), "FLAŞ" if h.persistent else "RAM", h.user, h.role, h.object_name,
                h.old_value, h.new_value, h.unit, h.detail])


def write_session_workbook(path: str, info: SessionInfo, events: list, history: list) -> dict:
    """Oturum için tek Excel dosyası yazar. ``events``/``history``: bu oturuma ait girişler (zaman süzgeci
    çağıranda). Döner: {"rows": parametre örnek sayısı, "signals": sinyal sayısı}."""
    stats, rows = ({}, 0)
    if info.record_csv and os.path.exists(info.record_csv):
        stats, rows = record_stats(info.record_csv)
    if len(stats) > WIDE_MAX_SIGNALS:
        info.notes.append(f"Geniş tablo ilk {WIDE_MAX_SIGNALS} sinyali içerir ({len(stats)} sinyal var); "
                          "tamamı 'Parametre kaydı' sayfasındadır.")
    with XlsxWorkbook(path) as wb:
        _write_summary(wb, info, rows, len(stats), events, history)
        if stats:
            _write_signal_summary(wb, stats)
            _write_record_long(wb, info.record_csv)
            _write_record_wide(wb, info.record_csv, sorted(stats))
        _write_events(wb, events)
        _write_history(wb, history)
    return {"rows": rows, "signals": len(stats)}


def filter_by_time(entries: list, start: float | None, end: float | None) -> list:
    out = []
    for e in entries:
        if start is not None and e.timestamp < start:
            continue
        if end is not None and e.timestamp > end:
            continue
        out.append(e)
    return out


def can_csv_to_xlsx(csv_path: str, xlsx_path: str) -> int:
    """CAN kaydı CSV'sini Excel'e çevirir (milyonlarca satırda sayfalara bölünür). Döner: kare sayısı."""
    n = 0
    with XlsxWorkbook(xlsx_path) as wb, open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        sh = wb.sheet("CAN kaydı", ["Tarih/saat", "Zaman (ms)", "Yön", "CAN ID (hex)", "Mesaj", "DLC", "Veri (hex)",
                                    "Extended"],
                      widths=[24, 18, 6, 14, 28, 6, 28, 9], formats=["datetime", None, None, None, None, None, None,
                                                                       None])
        for row in reader:
            if len(row) < 7:
                continue
            try:
                ms = float(row[0])
            except ValueError:
                continue
            try:
                dlc = int(row[4])
            except ValueError:
                dlc = None
            sh.row([_dt(ms / 1000.0), ms, row[1], row[2], row[3], dlc, row[5], row[6] == "1"])
            n += 1
    return n
