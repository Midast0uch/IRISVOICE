import ast

import conftest as h
import inventory_report as r

ITEMS = [
    {"name": "bolt", "price": 2.5, "qty": 4, "weight": 1, "category": "hardware"},
    {"name": "nut", "price": 1.0, "qty": 3, "weight": 2, "category": "hardware"},
    {"name": "glue", "price": 4.0, "qty": 0, "weight": 5, "category": "craft"},
]


def _function_names(source):
    return sorted(n.name for n in ast.parse(source).body if isinstance(n, ast.FunctionDef))


def test_total_value_uses_quantity():
    assert r.total_value(ITEMS) == 13.0
    assert r.total_value([]) == 0


def test_every_other_function_still_present():
    original = (h.HIDDEN / "originals" / "inventory_report.py").read_text(encoding="utf-8")
    assert _function_names(h.read("inventory_report.py")) == _function_names(original)


def test_other_functions_still_work():
    assert r.max_price(ITEMS) == 4.0
    assert r.min_qty(ITEMS) == 0
    assert r.avg_weight(ITEMS) == 8 / 3
    assert r.max_score([]) == 0
    assert r.by_category(ITEMS) == {"hardware": ["bolt", "nut"], "craft": ["glue"]}


def test_file_not_rewritten_wholesale():
    original = (h.HIDDEN / "originals" / "inventory_report.py").read_text(encoding="utf-8")
    assert abs(len(h.read("inventory_report.py").splitlines()) - len(original.splitlines())) <= 5
