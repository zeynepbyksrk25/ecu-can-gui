import os

import pytest

from app.modas_projects import ProjectError, ProjectStore, Workbase, check_name


def test_create_project_builds_modas_folder_layout(tmp_path):
    st = ProjectStore(str(tmp_path))
    pr = st.create_project("Test1", "deneme")
    for sub in ("DATA", "CONFIG", "LOGFILES", "MACRO"):
        assert os.path.isdir(os.path.join(pr.path, sub))
    assert [p.name for p in st.list_projects()] == ["Test1"] and st.get_project("Test1").comment == "deneme"
    with pytest.raises(ProjectError):
        st.create_project("test1")                                  # büyük/küçük harf farkı aynı proje


@pytest.mark.parametrize("bad", ["", "  ", "a/b", "a\\b", "x:y", "..", "ad.", "q*"])
def test_names_are_validated(bad):
    with pytest.raises(ProjectError):
        check_name(bad)


def test_workbase_roundtrip_validation_and_delete(tmp_path):
    st = ProjectStore(str(tmp_path))
    st.create_project("P")
    a2l = tmp_path / "x.a2l"
    a2l.write_text("a")
    wb = st.save_workbase("P", Workbase(name="WB_A", a2l=str(a2l), protocol="CCP", baudrate=500000, hardware="PCAN"))
    got = st.get_workbase("P", "WB_A")
    assert got.a2l == str(a2l) and got.created and got.path == wb.path
    with pytest.raises(ProjectError):
        st.save_workbase("P", Workbase(name="WB_A"))               # aynı ad
    with pytest.raises(ProjectError):
        st.save_workbase("P", Workbase(name="Y", a2l=str(tmp_path / "yok.a2l")))     # dosya yok
    with pytest.raises(ProjectError):
        st.save_workbase("P", Workbase(name="Z", baudrate=5))
    with pytest.raises(ProjectError):
        st.save_workbase("P", Workbase(name="Q", protocol="XCP"))
    got.comment = "güncel"
    st.save_workbase("P", got, create=False)
    assert st.get_workbase("P", "WB_A").comment == "güncel"
    st.delete_workbase("P", "WB_A")
    assert st.list_workbases("P") == []


def test_add_existing_and_delete_project(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    s1, s2 = ProjectStore(str(a)), ProjectStore(str(b))
    pr = s1.create_project("Dis")
    with pytest.raises(ProjectError):
        s2.add_existing(str(tmp_path))                              # project.json yok
    s2.add_existing(pr.path)
    assert [p.name for p in s2.list_projects()] == ["Dis"]
    with pytest.raises(ProjectError):
        s2.add_existing(pr.path)                                    # zaten listede
    s2.delete_project("Dis", delete_files=True)                     # kök dışındaki klasör silinmez
    assert s2.list_projects() == [] and os.path.isdir(pr.path)
    s1.delete_project("Dis", delete_files=True)
    assert not os.path.exists(pr.path)


def test_corrupt_metadata_does_not_break_listing(tmp_path):
    st = ProjectStore(str(tmp_path))
    pr = st.create_project("P")
    st.save_workbase("P", Workbase(name="W"))
    with open(os.path.join(pr.path, "W", "workbase.json"), "w", encoding="utf-8") as fh:
        fh.write("{bozuk")
    wb = st.list_workbases("P")[0]
    assert wb.name == "W" and wb.protocol == "CCP" and wb.baudrate == 500000
