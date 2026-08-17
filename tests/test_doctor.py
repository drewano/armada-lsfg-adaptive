from lsfg.doctor import _version_lte, glibc_requirement


def test_glibc_requirement_picks_max(tmp_path):
    lib = tmp_path / "lib.so"
    lib.write_bytes(b"...GLIBC_2.34...GLIBC_2.39...GLIBC_2.17...")
    assert glibc_requirement(lib) == "2.39"


def test_glibc_requirement_missing_file(tmp_path):
    assert glibc_requirement(tmp_path / "nope.so") is None


def test_glibc_requirement_no_tokens(tmp_path):
    lib = tmp_path / "empty.so"
    lib.write_bytes(b"\x7fELF nothing here")
    assert glibc_requirement(lib) is None


def test_version_lte():
    assert _version_lte("2.39", "2.41") is True
    assert _version_lte("2.41", "2.39") is False
    assert _version_lte("2.39", "2.39") is True
    assert _version_lte(None, "2.41") is None
    assert _version_lte("2.39", None) is None
