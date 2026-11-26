import json

from app.modas_dataset import DatasetStore, compare


def test_compare_scalar_grid_and_missing_labels():
    pc = {"A": 1.0, "B": [[1, 2], [3, 4]], "C": 5.0, "D": 7.0}
    ecu = {"A": 1.0, "B": [[1, 2], [3, 9]], "C": 6.0}                # D ECU'da yok
    d = compare(pc, ecu)
    assert [e.name for e in d] == ["B", "C"] and d[1].pc == 5.0 and d[1].ecu == 6.0
    assert compare(pc, {"A": 1.0 + 1e-12}) == []                      # sayısal gürültü fark sayılmaz


def test_store_roundtrip_filters_invalid_and_survives_corruption(tmp_path):
    st = DatasetStore(str(tmp_path))
    assert not st.exists() and st.load() is None
    assert st.save({"A": 1.5, "T": [[1, 2], [3, 4]], "bad": "x", "n": None, "b": True, "e": [], "nan": float("nan"),
                    "tn": [[1, float("inf")]]})
    assert st.load() == {"A": 1.5, "T": [[1, 2], [3, 4]]}
    with open(st.path, "w", encoding="utf-8") as fh:
        fh.write("{bozuk")
    assert st.load() is None                                          # bozuk dosya = veri seti yok
    with open(st.path, "w", encoding="utf-8") as fh:
        json.dump({"values": [1, 2]}, fh)
    assert st.load() is None
