import time
from types import SimpleNamespace

import numpy as np
import pytest

pypdf = pytest.importorskip("pypdf")

from app import report
from app.report_charts import MAX_POINTS, build_trend_charts, decimate


def _data(t0, n=100):
    t = t0 + np.linspace(0, 10, n)
    return {"Devir": (t, np.linspace(0, 100, n), "rpm"), "Sıcaklık": (t, np.linspace(20, 90, n), "°C"),
            "Basınç": (t, np.linspace(1, 2, n), "°C")}


def test_groups_by_unit_and_filters_range():
    t0 = time.time()
    charts = build_trend_charts(_data(t0), [(t0 + 1, "Test Başlangıcı", "#00aa00")], t0, t0 + 10)
    assert len(charts) == 2                                   # rpm + °C
    assert build_trend_charts(_data(t0), [], t0 + 100, t0 + 200) == []
    assert build_trend_charts({}, [], t0, t0 + 1) == []


def test_decimate_keeps_extremes():
    t = np.arange(50000, dtype=float)
    v = np.zeros(50000)
    v[12345] = 99.0
    ts, vs = decimate(t, v)
    assert len(ts) <= MAX_POINTS + 2 and vs.max() == 99.0


def test_pdf_contains_trend_section(tmp_path):
    t0 = time.time()
    log = SimpleNamespace(entries=[])
    out = str(tmp_path / "r.pdf")
    report.build_session_report(out, "T", "O", t0, t0 + 10, log,
                                trend_data=(_data(t0), [(t0 + 1, "Test Başlangıcı", "#00aa00")]))
    text = "\n".join(p.extract_text() for p in pypdf.PdfReader(out).pages)
    assert "Canlı Trendler" in text and "Devir" in text
    out2 = str(tmp_path / "r2.pdf")
    report.build_session_report(out2, "T", "O", t0, t0 + 10, log, trend_data=({}, []))
    assert "trend verisi yok" in "\n".join(p.extract_text() for p in pypdf.PdfReader(out2).pages)
