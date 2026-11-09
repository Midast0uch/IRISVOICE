from calculator import char_count


def test_char_count():
    assert char_count("abc") == 3
    assert char_count("") == 0

