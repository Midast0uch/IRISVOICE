from calculator import is_empty


def test_is_empty():
    assert is_empty("") is True
    assert is_empty(" ") is False
    assert is_empty("a") is False

