import json
import os

import pytest

from app.modas_datafiles import (DataFileError, ParameterFolder, compare_with_file, export_values, load_values,
                                 safe_file_name)
from app.modas_macros import MacroError, MacroRecorder, MacroStore, check_step, describe, missing_labels


def test_export_load_roundtrip_filters_invalid_and_rejects_empty(tmp_path):
    p = str(tmp_path / "a.json")
    assert export_values(p, {"A": 1.5, "T": [[1, 2], [3, 4]], "bad": "x", "n": None}, "P", "W") == 2
    assert load_values(p) == {"A": 1.5, "T": [[1, 2], [3, 4]]}
    with pytest.raises(DataFileError):
        export_values(str(tmp_path / "b.json"), {"bad": "x"})
    assert not os.path.exists(tmp_path / "b.json")                     # boş dosya üretilmez


def test_load_values_validates_format_version_and_content(tmp_path):
    def write(obj, name="x.json"):
        p = tmp_path / name
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
        return str(p)

    for bad in ("{bozuk", [1], {"format": "baska"}, {"format": "openecu-parameters", "version": 99, "values": {"A": 1}},
                {"format": "openecu-parameters", "version": 1}, {"format": "openecu-parameters", "version": 1, "values": {"A": "x"}}):
        with pytest.raises(DataFileError):
            load_values(write(bad))
    with pytest.raises(DataFileError):
        load_values(str(tmp_path / "yok.json"))


def test_compare_with_file_reports_diffs_and_unmatched_labels():
    wp = {"A": 1.0, "B": 2.0, "T": [[1, 2]]}
    f = {"A": 1.0, "B": 5.0, "C": 3.0, "T": [[1, 9]]}
    diffs, only_file, only_wp = compare_with_file(wp, f)
    assert [(d.name, d.pc, d.ecu) for d in diffs] == [("B", 2.0, 5.0), ("T", [[1, 2]], [[1, 9]])]
    assert only_file == ["C"] and only_wp == []


def test_parameter_folder_save_list_delete_and_name_safety(tmp_path):
    pf = ParameterFolder(str(tmp_path / "par"))
    assert pf.list() == []
    path = pf.save("Soğutma: test/1", {"A": 1.0})
    assert os.path.basename(path) == "Soğutma_ test_1.json" and [n for n, _p, _t in pf.list()] == ["Soğutma_ test_1"]
    with pytest.raises(DataFileError):
        pf.save("Soğutma: test/1", {"A": 2.0})                          # üzerine yazma yalnızca açıkça
    pf.save("Soğutma: test/1", {"A": 2.0}, overwrite=True)
    assert load_values(path) == {"A": 2.0}
    (tmp_path / "par" / "yabanci.json").write_text('{"x": 1}', encoding="utf-8")
    assert [n for n, _p, _t in pf.list()] == ["Soğutma_ test_1"]        # geçersiz dosya listede yok
    assert pf.delete("Soğutma: test/1") and not pf.delete("Soğutma: test/1")
    with pytest.raises(DataFileError):
        safe_file_name("  . ")


def test_macro_recorder_collapses_repeats_and_validates_steps():
    r = MacroRecorder()
    r.add("value", "A", 1.0)                                            # kayıt yokken eklenmez
    assert r.steps == []
    r.start()
    r.add("value", "A", 1.0)
    r.add("value", "A", 2.0)                                            # art arda aynı etiket: son değer
    r.add("table", "T", [[1, 2], [3, 4]])
    steps = r.stop()
    assert [describe(s) for s in steps] == ["A = 2", "T = 2×2 tablo"]
    with pytest.raises(MacroError, match="kaldırılmış"):                # eski macro'lardaki "input" adımı artık reddedilir
        check_step({"kind": "input", "label": "Input: Altitude", "value": 8.0})
    for bad in ({"kind": "x", "label": "A", "value": 1}, {"kind": "value", "label": "", "value": 1},
                {"kind": "value", "label": "A", "value": [[1]]}, {"kind": "table", "label": "T", "value": 1},
                {"kind": "value", "label": "A", "value": float("nan") if False else "x"}):
        with pytest.raises(MacroError):
            check_step(bad)


def test_macro_store_roundtrip_overwrite_and_missing_labels(tmp_path):
    st = MacroStore(str(tmp_path / "m"))
    steps = [{"kind": "value", "label": "A", "value": 1.0}, {"kind": "table", "label": "T", "value": [[1, 2]]}]
    assert st.names() == []
    st.save("Çalıştırma 1", steps)
    assert st.names() == ["Çalıştırma 1"] and st.load("Çalıştırma 1") == steps
    with pytest.raises(MacroError):
        st.save("Çalıştırma 1", steps)
    with pytest.raises(MacroError):
        st.save("Boş", [])
    assert missing_labels(steps, {"A"}) == ["T"]
    p = st.path_for("Çalıştırma 1")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("{bozuk")
    with pytest.raises(MacroError):
        st.load("Çalıştırma 1")
    assert st.delete("Çalıştırma 1") and not st.delete("Çalıştırma 1")
