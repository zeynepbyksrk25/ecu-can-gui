"""Kayıtlı oturumdan test raporu (HTML): test bilgileri, DBC/A2L, süre, sinyal istatistikleri, kalibrasyon değişiklikleri,
olaylar, hata/bağlantı olayları, dosya konumları. PASS/FAIL kararı VERMEZ (limit uydurulmaz); yalnızca kayıtlı gerçekleri
özetler. Büyük kayıtlarda tek geçişli istatistik (numpy) kullanılır."""
from __future__ import annotations

import html
import math
import os
import time

import numpy as np

from app.session_export import SessionData

MAX_EVENT_ROWS = 500
ERROR_KINDS = ("HATA", "BAGLANTI")


def signal_stats(sd: SessionData) -> list[dict]:
    rows = []
    for sid in sd.signals():
        t, v = sd.arrays(sid)
        if not len(v):
            continue
        rows.append({"signal": sid, "unit": sd.unit(sid), "source": sd.source(sid), "count": int(len(v)),
                     "min": float(np.min(v)), "max": float(np.max(v)), "mean": float(np.mean(v)),
                     "first": float(v[0]), "last": float(v[-1]), "t0": float(t[0]), "t1": float(t[-1])})
    return rows


def calibration_changes(sd: SessionData) -> list[dict]:
    """``cal:`` örneklerinden + KALIBRASYON olaylarından değişim listesi (zaman sıralı)."""
    out = []
    for sid in sd.signals():
        if not sid.startswith("cal:"):
            continue
        t, v = sd.arrays(sid)
        prev = None
        for ti, vi in zip(t, v):
            out.append({"t": float(ti), "name": sid[4:], "old": prev, "new": float(vi), "unit": sd.unit(sid)})
            prev = float(vi)
    out.sort(key=lambda r: r["t"])
    return out


def _fmt(x, d=5):
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{d}g}"


def build_report_html(sd: SessionData, extra_files: dict | None = None) -> str:
    m = sd.meta
    e = html.escape
    start = m.get("start_unix")
    dur = m.get("duration_s")
    stats = signal_stats(sd)
    cal = calibration_changes(sd)
    errs = [x for x in sd.events if x[2].startswith(ERROR_KINDS)]
    status = {"complete": "tamamlandı", "recovered": "KURTARILDI (beklenmedik kapanış)", "error": "HATA ile bitti",
              "recording": "KURTARILDI (beklenmedik kapanış)"}.get(m.get("status", ""), "bilinmiyor")
    dbc, a2l = m.get("dbc") or {}, m.get("a2l") or {}

    def ver(d):
        return e(f"{d.get('file', '—')} (SHA-256 {d.get('sha256', '—')}, {d.get('size', '—')} B)") if d else "—"

    parts = [f"<!doctype html><meta charset='utf-8'><title>Test raporu – {e(str(m.get('name') or ''))}</title>",
             "<style>body{font:14px Segoe UI,Arial;margin:24px;color:#121A22}table{border-collapse:collapse;margin:8px 0}"
             "td,th{border:1px solid #C9D3DC;padding:3px 8px;text-align:left}th{background:#EEF2F6}"
             "h2{margin-top:24px}.warn{color:#C22A1D}</style>",
             f"<h1>Test raporu: {e(str(m.get('name') or os.path.basename(sd.path)))}</h1>",
             "<h2>Test bilgileri</h2><table>"]
    info = [("Durum", status),
            ("Başlangıç", time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(start)) if start else "—"),
            ("Süre", f"{dur:.1f} sn" if isinstance(dur, (int, float)) else "—"),
            ("Kullanıcı / rol", f"{m.get('user', '—')} / {m.get('role', '—')}"), ("Operatör", m.get("operator", "—")),
            ("Mod", m.get("mode", "—")), ("Bağlantı", (m.get("connection") or {}).get("interface", "—")),
            ("Simulink modeli", m.get("simulink_model") or "—"), ("Zaman tabanı", m.get("timebase", "—")),
            ("DBC", ver(dbc)), ("A2L", ver(a2l)),
            ("Örnek / olay / ham CAN kare", f"{m.get('rows', '—')} / {m.get('events', '—')} / {m.get('frames', '—')}"),
            ("Düşen veri", m.get("dropped", 0)), ("Yazma hatası", m.get("error") or "yok")]
    for k, v in info:
        cls = " class='warn'" if k in ("Düşen veri", "Yazma hatası") and v not in (0, "yok", None) else ""
        parts.append(f"<tr><th>{e(k)}</th><td{cls}>{v if k in ('DBC', 'A2L') else e(str(v))}</td></tr>")
    parts.append("</table>")
    parts.append("<h2>Sinyal istatistikleri</h2><table><tr><th>Sinyal</th><th>Birim</th><th>Kaynak</th><th>Örnek</th>"
                 "<th>Min</th><th>Max</th><th>Ort.</th><th>İlk</th><th>Son</th></tr>")
    for r in stats:
        parts.append(f"<tr><td>{e(r['signal'])}</td><td>{e(r['unit'])}</td><td>{e(r['source'])}</td><td>{r['count']}</td>"
                     f"<td>{_fmt(r['min'])}</td><td>{_fmt(r['max'])}</td><td>{_fmt(r['mean'])}</td>"
                     f"<td>{_fmt(r['first'])}</td><td>{_fmt(r['last'])}</td></tr>")
    parts.append("</table>")
    parts.append(f"<h2>Kalibrasyon değişiklikleri ({len(cal)})</h2><table><tr><th>t (sn)</th><th>Parametre</th>"
                 "<th>Eski</th><th>Yeni</th><th>Birim</th></tr>")
    for c in cal[:MAX_EVENT_ROWS]:
        parts.append(f"<tr><td>{c['t']:.2f}</td><td>{e(c['name'])}</td><td>{_fmt(c['old'])}</td><td>{_fmt(c['new'])}</td>"
                     f"<td>{e(c['unit'])}</td></tr>")
    parts.append("</table>")
    parts.append(f"<h2>Hata ve bağlantı olayları ({len(errs)})</h2><table><tr><th>t (sn)</th><th>Tür</th><th>Metin</th></tr>")
    for t, _u, k, text in errs[:MAX_EVENT_ROWS]:
        parts.append(f"<tr><td>{t:.2f}</td><td>{e(k)}</td><td>{e(text)}</td></tr>")
    parts.append("</table>")
    parts.append(f"<h2>Tüm olaylar ve işaretler ({len(sd.events)})</h2><table><tr><th>t (sn)</th><th>Tür</th><th>Metin</th></tr>")
    for t, _u, k, text in sd.events[:MAX_EVENT_ROWS]:
        parts.append(f"<tr><td>{t:.2f}</td><td>{e(k)}</td><td>{e(text)}</td></tr>")
    if len(sd.events) > MAX_EVENT_ROWS:
        parts.append(f"<tr><td colspan=3>… {len(sd.events) - MAX_EVENT_ROWS} olay daha (olay dosyasında)</td></tr>")
    parts.append("</table><h2>Dosyalar</h2><ul>")
    files = dict(m.get("files") or {})
    files.update(extra_files or {})
    base = os.path.dirname(sd.path)
    for k, v in files.items():
        parts.append(f"<li>{e(k)}: {e(os.path.join(base, v) if not os.path.isabs(str(v)) else str(v))}</li>")
    parts.append("</ul><p><i>Bu rapor kayıtlı verileri özetler; PASS/FAIL kararı içermez.</i></p>")
    if sd.skipped_rows:
        parts.append(f"<p class='warn'>{sd.skipped_rows} bozuk/sonlu olmayan satır atlandı.</p>")
    return "".join(parts)


def write_report(sd: SessionData, path: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_report_html(sd))
    return path
