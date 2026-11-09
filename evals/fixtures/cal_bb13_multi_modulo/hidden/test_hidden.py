from calculator import modulo


def test_modulo():
    assert modulo(7, 3) == 1
    assert modulo(9, 3) == 0
    assert modulo(8, 5) == 3
