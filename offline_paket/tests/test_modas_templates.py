import os
from types import SimpleNamespace as NS

from app.modas_templates import BUILTINS, TemplateStore, build_builtin, build_specs

DATA = os.path.join(os.path.dirname(__file__), "data")


def summary(meas=(), chars=()):
    return NS(measurements=[NS(name=n) for n in meas],
              characteristics=[NS(name=n, kind=k, read_only=ro, address=0x1000) for n, k, ro in chars])


def test_monitoring_matches_performance_aliases_and_monitor_words_only():
    s = summary(meas=["N_RPM", "TIT", "Tt2_raw", "FP_bar", "clbc_fuel_flow", "NoAddr", "Zzz"])
    specs = build_builtin("İzleme", s)
    names = [x["name"] for x in specs if x["kind"] == "value"]
    assert "TIT" in names and "N_RPM" in names and "Zzz" not in names and len(names) <= 8
    scope = next(x for x in specs if x["kind"] == "scope")
    assert scope["panel"]["signals"][0].startswith("a2l:") and len(scope["panel"]["signals"]) <= 4
    assert [x for x in build_builtin("İzleme", summary()) if x["kind"] == "value"] == []


def test_calibration_picks_writable_objects_and_removed_templates_are_gone():
    s = summary(meas=["N_RPM"], chars=[("G1", "SCALAR", False), ("G2", "SCALAR", True), ("M1", "MAP", False),
                                       ("C1", "CURVE", False), ("X", "ARRAY", False)])
    assert build_builtin("Start Sequence", s) == []                                  # eski giriş pencereli şablon yok
    assert [x["kind"] for x in build_builtin("Test Tezgâhı", s)][0] == "actuator"    # yeni: Eyleyiciler penceresi
    cal = build_builtin("Kalibrasyon", s)
    assert [x["name"] for x in cal if x["kind"] == "value"] == ["G1"]           # salt-okunur ve dizi dışarıda
    assert [x["name"] for x in cal if x["kind"] == "table"] == ["M1", "C1"]
    assert build_builtin("Kalibrasyon", None) == []


def test_user_templates_roundtrip_and_cannot_shadow_builtins(tmp_path):
    st = TemplateStore(str(tmp_path / "t.json"))
    specs = [{"kind": "value", "name": "A", "geom": [1, 2, 3, 4]}, {"bad": 1}, "x"]
    assert st.save("Benim", specs) and st.names() == ["Benim"]
    assert st.get("Benim") == [{"kind": "value", "name": "A", "geom": [1, 2, 3, 4]}]     # geçersiz girdiler elenir
    assert not st.save("İzleme", specs) and not st.save("  ", specs)
    assert build_specs("Benim", None, st)[0]["name"] == "A" and build_specs("Yok", None, st) is None
    assert st.delete("Benim") and st.names() == [] and not st.delete("Benim")
    for suffix in ("", ".bak"):
        with open(st.path + suffix, "w", encoding="utf-8") as fh:
            fh.write("{bozuk")
    assert st.names() == []                                                      # bozuk dosya (ve yedeği) sessizce boş
    assert {t.name for t in BUILTINS} == {"İzleme", "Kalibrasyon", "Test Tezgâhı"}
