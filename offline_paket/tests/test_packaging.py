"""Kurulum/paketleme dosyaları için statik doğrulamalar (Windows'ta çalıştırılamayan
scriptlerin en azından yanlış sürüm/format/eksik dosya hatalarını yakalar)."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name, mode="r"):
    with open(os.path.join(ROOT, name), mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def test_batch_files_are_crlf_and_ascii():
    for n in os.listdir(ROOT):
        if n.endswith((".bat", ".cmd")):
            raw = read(n, "rb")
            raw.decode("ascii")                         # cmd.exe kod sayfası sorunu olmasın
            assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), f"{n} CRLF olmalı"


def test_install_requires_python_311_64bit_and_hashes():
    for n in ("0_wheels_indir.bat", "1_kurulum.bat"):
        s = read(n)
        assert "py -3.11" in s and "(3,11)" in s and "sys.maxsize>2**32" in s, n
        assert "py -3 " not in s.replace("py -3.11", ""), f"{n}: sürümsüz 'py -3' kalmış"
        assert "--require-hashes" in s and "requirements.lock.txt" in s
    assert "--clear" in read("1_kurulum.bat")


def test_cmd_files_are_thin_wrappers():
    for n in ("0_wheels_indir", "1_kurulum", "2_exe_olustur", "3_testleri_calistir"):
        s = read(n + ".cmd")
        assert f'call "%~dp0{n}.bat"' in s and len(s.splitlines()) <= 4


def test_exe_build_bundles_fonts_and_keeps_can_flags():
    s = read("2_exe_olustur.bat")
    for flag in ("--noconfirm", '--add-data "app\\fonts;app\\fonts"', "--collect-submodules can",
                 "--collect-submodules cantools", "--collect-all pya2l"):
        assert flag in s, flag
    assert os.path.isfile(os.path.join(ROOT, "app", "fonts", "DejaVuSans.ttf"))
    assert os.path.isfile(os.path.join(ROOT, "app", "fonts", "LICENSE-DejaVu.txt"))


def test_requirements_are_pinned_and_lock_has_hashes():
    for n in ("requirements_build.txt", "requirements-dev.txt"):
        for line in read(n).splitlines():
            if line.strip() and not line.startswith("#"):
                assert re.match(r"^[A-Za-z0-9_.\-]+==[\w.]+$", line.strip()), f"{n}: sabit değil: {line}"
    lock = read("requirements.lock.txt")
    pins = re.findall(r"^[A-Za-z0-9_.\-]+==", lock, re.M)
    hashes = re.findall(r"--hash=sha256:[0-9a-f]{64}", lock)
    assert len(pins) >= 30 and len(pins) == len(hashes)
    names = {p.rstrip("=").lower() for p in pins}
    for needed in ("pyside6", "python-can", "cantools", "pya2ldb", "pyqtgraph", "reportlab",
                   "pyinstaller", "numpy", "pywin32-ctypes", "pefile", "altgraph", "colorama"):
        assert needed in names, needed
    direct = {l.split("==")[0].lower() for l in read("requirements_build.txt").splitlines() if "==" in l}
    assert direct <= names
