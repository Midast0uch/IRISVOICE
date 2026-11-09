from calculator import word_count


def test_word_count():
    assert word_count("a b c") == 3
    assert word_count("") == 0

