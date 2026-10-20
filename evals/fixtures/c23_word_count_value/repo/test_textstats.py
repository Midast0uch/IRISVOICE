from textstats import longest_word, word_count


def test_word_count():
    assert word_count("a b c") == 3


def test_word_count_empty():
    assert word_count("") == 0


def test_longest_word():
    assert longest_word("the quicksilver brown fox") == "quicksilver"


def test_longest_word_empty():
    assert longest_word("") == ""
