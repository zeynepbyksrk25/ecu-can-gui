"""Kayıtlı oturumdan test raporu (HTML): test bilgileri, DBC/A2L, süre, sinyal istatistikleri, kalibrasyon değişiklikleri,
olaylar, hata/bağlantı olayları, dosya konumları. PASS/FAIL kararı VERMEZ (limit uydurulmaz); yalnızca kayıtlı gerçekleri
özetler. Büyük kayıtlarda tek geçişli istatistik (numpy) kullanılır."""
from __future__ import annotations

import html
import math
import os
import time

import numpy as np

from app.change_tracker import direction, format_delta
from app.session_export import SessionData
from app.session_recorder import system_time_text

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


def calibration_summary(cal: list[dict]) -> list[dict]:
    """Parametre başına özet: ilk kayıtlı değer (başlangıç referansı), son değer, net sapma, artış/azalış sayısı.
    Referans = kayıttaki İLK örnek (varsayılan uydurulmaz); ``old=None`` olan ilk örnek değişiklik sayılmaz."""
    out: dict[str, dict] = {}
    for c in cal:
        r = out.setdefault(c["name"], {"name": c["name"], "unit": c["unit"], "first": c["new"], "last": c["new"],
                                        "up": 0, "down": 0})
        r["last"] = c["new"]
        dr = direction(c["old"], c["new"])
        if dr > 0:
            r["up"] += 1
        elif dr < 0:
            r["down"] += 1
    for r in out.values():
        r["net"] = r["last"] - r["first"]
    return list(out.values())


def _arrow_html(old, new, unit: str = "") -> str:
    """Kırmızı yön oku + fark (arayüzdeki ok diliyle aynı: ↑ artış, ↓ azalış); değişim yoksa ``—``."""
    dr = direction(old, new)
    if dr == 0:
        return "—"
    return f"<span class='chg'>{format_delta(old, new, unit)}</span>"


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
             "h2{margin-top:24px}.warn{color:#C22A1D}.chg{color:#C22A1D;font-weight:600;white-space:nowrap}</style>",
             f"<h1>Test raporu: {e(str(m.get('name') or os.path.basename(sd.path)))}</h1>",
             "<h2>Test bilgileri</h2><table>"]
    info = [("Durum", status),
            ("Başlangıç", time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(start)) if start else "—"),
            ("Süre", f"{dur:.1f} sn" if isinstance(dur, (int, float)) else "—"),
            ("Kullanıcı / rol", f"{m.get('user', '—')} / {m.get('role', '—')}"), ("Operatör", m.get("operator", "—")),
            ("Zaman tabanı (time sütunu)", "gerçek zaman: monotonik, oturum başından sn" if m.get("time_source") == "monotonic"
             else "sistem saatinden türetilmiş (eski kayıt)"),
            ("Sistem saati", f"UTC{m.get('utc_offset_min', 0) / 60:+g} ({m.get('timezone', '—')}), ms çözünürlük"),
            ("Mod", m.get("mode", "—")), ("Bağlantı", (m.get("connection") or {}).get("interface", "—")),
            ("Simulink modeli", m.get("simulink_model") or "—"), ("Zaman tabanı", m.get("timebase", "—")),
            ("DBC", ver(dbc)), ("A2L", ver(a2l)),
            ("Örnek / olay / ham CAN kare", f"{m.get('rows', '—')} / {m.get('events', '—')} / {m.get('frames', '—')}"),
            ("Düşen veri", m.get("dropped", 0)), ("Yazma hatası", m.get("error") or "yok")]
    for k, v in info:
        cls = " class='warn'" if k in ("Düşen veri", "Yazma hatası") and v not in (0, "yok", None) else ""
        parts.append(f"<tr><th>{e(k)}</th><td{cls}>{v if k in ('DBC', 'A2L') else e(str(v))}</td></tr>")
    parts.append("</table>")
    parts.append("<h2>Kayıt bütünlüğü</h2><ul>")
    cls = {"ok": "", "warn": " class='warn'", "error": " class='warn'"}
    for lv, txt in sd.integrity():
        parts.append(f"<li{cls[lv]}>{e(txt)}</li>")
    parts.append("</ul>")
    gaps = sd.data_gaps()
    if gaps:
        parts.append(f"<h3>CAN veri boşlukları ({len(gaps)})</h3><table><tr><th>Başlangıç (sn)</th><th>Bitiş (sn)</th>"
                     "<th>Süre (sn)</th><th>Neden (olaydan)</th></tr>")
        for g in gaps[:MAX_EVENT_ROWS]:
            parts.append(f"<tr><td>{g['start_s']:.3f}</td><td>{g['end_s']:.3f}</td><td>{g['duration_s']:.3f}</td>"
                         f"<td>{e(g['cause']) or '<b class=warn>AÇIKLANAMAYAN</b>'}</td></tr>")
        parts.append("</table>")
    parts.append("<h2>Sinyal istatistikleri</h2><table><tr><th>Sinyal</th><th>Birim</th><th>Kaynak</th><th>Örnek</th>"
                 "<th>Min</th><th>Max</th><th>Ort.</th><th>İlk</th><th>Son</th></tr>")
    for r in stats:
        parts.append(f"<tr><td>{e(r['signal'])}</td><td>{e(r['unit'])}</td><td>{e(r['source'])}</td><td>{r['count']}</td>"
                     f"<td>{_fmt(r['min'])}</td><td>{_fmt(r['max'])}</td><td>{_fmt(r['mean'])}</td>"
                     f"<td>{_fmt(r['first'])}</td><td>{_fmt(r['last'])}</td></tr>")
    parts.append("</table>")
    summ = calibration_summary(cal)
    parts.append(f"<h2>Kalibrasyon değişiklikleri ({len(cal)})</h2>")
    parts.append("<p>Yön: <span class='chg'>↑ artış</span>, <span class='chg'>↓ azalış</span> (ECU'ya yazılan değerler; "
                 "referans = kayıttaki ilk değer, A2L varsayılanı değil).</p>")
    if summ:
        parts.append("<table><tr><th>Parametre</th><th>İlk (başlangıç)</th><th>Son</th><th>Başlangıca göre</th>"
                     "<th>↑ sayısı</th><th>↓ sayısı</th><th>Birim</th></tr>")
        for r in summ:
            parts.append(f"<tr><td>{e(r['name'])}</td><td>{_fmt(r['first'])}</td><td>{_fmt(r['last'])}</td>"
                         f"<td>{_arrow_html(r['first'], r['last'], r['unit'])}</td><td>{r['up']}</td><td>{r['down']}</td>"
                         f"<td>{e(r['unit'])}</td></tr>")
        parts.append("</table>")
    parts.append("<table><tr><th>t (sn)</th><th>Parametre</th><th>Eski</th><th>Yeni</th><th>Değişim</th><th>Birim</th></tr>")
    for c in cal[:MAX_EVENT_ROWS]:
        parts.append(f"<tr><td>{c['t']:.2f}</td><td>{e(c['name'])}</td><td>{_fmt(c['old'])}</td><td>{_fmt(c['new'])}</td>"
                     f"<td>{_arrow_html(c['old'], c['new'], c['unit'])}</td><td>{e(c['unit'])}</td></tr>")
    parts.append("</table>")
    parts.append(f"<h2>Hata ve bağlantı olayları ({len(errs)})</h2><table><tr><th>Gerçek zaman (sn)</th><th>Sistem saati</th><th>Tür</th><th>Metin</th></tr>")
    for t, u, k, text in errs[:MAX_EVENT_ROWS]:
        parts.append(f"<tr><td>{t:.3f}</td><td>{system_time_text(u)}</td><td>{e(k)}</td><td>{e(text)}</td></tr>")
    parts.append("</table>")
    parts.append(f"<h2>Tüm olaylar ve işaretler ({len(sd.events)})</h2><table><tr><th>Gerçek zaman (sn)</th><th>Sistem saati</th><th>Tür</th><th>Metin</th></tr>")
    for t, u, k, text in sd.events[:MAX_EVENT_ROWS]:
        parts.append(f"<tr><td>{t:.3f}</td><td>{system_time_text(u)}</td><td>{e(k)}</td><td>{e(text)}</td></tr>")
    if len(sd.events) > MAX_EVENT_ROWS:
        parts.append(f"<tr><td colspan=4>… {len(sd.events) - MAX_EVENT_ROWS} olay daha (olay dosyasında)</td></tr>")
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
