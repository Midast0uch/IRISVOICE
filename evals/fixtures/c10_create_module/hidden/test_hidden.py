import pytest
from inventory import Inventory


def test_add_and_count():
    inv = Inventory()
    inv.add("apple", 3)
    inv.add("apple", 2)
    assert inv.count("apple") == 5


def test_unknown_item_counts_zero():
    assert Inventory().count("pear") == 0


def test_remove():
    inv = Inventory()
    inv.add("apple", 5)
    inv.remove("apple", 2)
    assert inv.count("apple") == 3


def test_remove_too_many_raises_and_keeps_stock():
    inv = Inventory()
    inv.add("apple", 1)
    with pytest.raises(ValueError):
        inv.remove("apple", 2)
    assert inv.count("apple") == 1


def test_remove_unknown_raises():
    with pytest.raises(ValueError):
        Inventory().remove("pear", 1)


@pytest.mark.parametrize("qty", [0, -1])
def test_non_positive_quantities_rejected(qty):
    inv = Inventory()
    with pytest.raises(ValueError):
        inv.add("apple", qty)
    inv.add("apple", 1)
    with pytest.raises(ValueError):
        inv.remove("apple", qty)


def test_instances_are_independent():
    a, b = Inventory(), Inventory()
    a.add("apple", 1)
    assert b.count("apple") == 0
