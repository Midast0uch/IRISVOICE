import conftest as h


def test_no_file_changed():
    assert h.unchanged("cipher.py")
