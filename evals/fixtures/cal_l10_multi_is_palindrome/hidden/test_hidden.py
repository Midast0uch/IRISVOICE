from calculator import is_palindrome


def test_palindrome():
    assert is_palindrome("racecar") is True
    assert is_palindrome("hello") is False

