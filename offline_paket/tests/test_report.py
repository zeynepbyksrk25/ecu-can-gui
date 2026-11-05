import os
import time
from types import SimpleNamespace

import pytest

pypdf = pytest.importorskip("pypdf")

from app import report

TR = "şğıİŞĞçöüÇÖÜ"


def ev(ts, msg, cat="TEST"):
    return SimpleNamespace(timestamp=ts, user="kullanıcı", role="Yönetici", category=cat, message=msg)


def log(*entries):
    return SimpleNamespace(entries=list(entries))


def text_of(path):
    r = pypdf.PdfReader(path)
    return "\n".join(p.extract_text() for p in r.pages), r


def test_turkish_characters_and_long_words(tmp_path):
    t0 = time.time()
    out = str(tmp_path / "r.pdf")
    long_word = "X" * 400
    report.build_session_report(out, f"Test {TR}", "Operatör Şükrü", t0 - 10, t0 + 10,
                                log(ev(t0, f"Başlangıç {TR} <b>&", "ÇIKIŞ"), ev(t0 + 1, long_word)))
    text, r = text_of(out)
    flat = text.replace("\n", "")
    for ch in TR:
        assert ch in flat, f"{ch!r} PDF'te yok"
    assert "<b>&" in flat                       # XML kaçışı: etiket olarak yorumlanmadı
    assert long_word.replace("\n", "") in flat or flat.count("X") >= 400    # uzun kelime kesilmeden sarıldı
    assert "Sayfa 1" in text
    fonts = {f for p in r.pages for f in (p["/Resources"]["/Font"] or {})}
    assert fonts and not os.path.exists(out + ".tmp")


def test_only_events_inside_session_range(tmp_path):
    t0 = time.time()
    out = str(tmp_path / "r.pdf")
    report.build_session_report(out, "T", "O", t0, t0 + 5,
                                log(ev(t0 - 100, "ONCE"), ev(t0 + 1, "ICERDE"), ev(t0 + 100, "SONRA")))
    text, _ = text_of(out)
    assert "ICERDE" in text and "ONCE" not in text and "SONRA" not in text
    assert "2 olay rapora dahil edilmedi" in text.replace("\n", " ")


def test_requires_started_session(tmp_path):
    with pytest.raises(ValueError):
        report.build_session_report(str(tmp_path / "r.pdf"), "T", "O", None, None, log())


def test_unwritable_path_raises_reporterror(tmp_path):
    with pytest.raises(report.ReportError):
        report.build_session_report(str(tmp_path / "yok" / "r.pdf"), "T", "O", time.time() - 1, None, log())


def test_missing_font_is_explicit_error(monkeypatch, tmp_path):
    from reportlab.pdfbase import pdfmetrics
    monkeypatch.setattr(report, "_font_candidates", lambda: [("/yok/a.ttf", "/yok/b.ttf")])
    monkeypatch.setattr(pdfmetrics, "getRegisteredFontNames", lambda: [])
    with pytest.raises(report.ReportError, match="yazı tipi"):
        report.build_session_report(str(tmp_path / "r.pdf"), "T", "O", time.time() - 1, None, log())
    assert not (tmp_path / "r.pdf").exists()


def test_many_events_paginate(tmp_path):
    t0 = time.time()
    out = str(tmp_path / "r.pdf")
    report.build_session_report(out, "T", "O", t0 - 1, t0 + 1000, log(*[ev(t0 + i / 10, f"olay {i} {TR}") for i in range(400)]))
    _, r = text_of(out)
    assert len(r.pages) > 3
