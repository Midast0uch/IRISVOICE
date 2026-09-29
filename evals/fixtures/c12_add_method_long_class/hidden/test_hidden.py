import ast

import conftest as h
from ledger import Ledger


def _methods(source):
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "Ledger")
    return {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}


def _ledger():
    led = Ledger()
    led.deposit("2026-01-05", 1000, "salary")
    led.withdraw("2026-01-10", 300, "rent")
    led.deposit("2026-02-05", 1000, "salary")
    led.withdraw("2026-02-01", 50, "food")
    return led


def test_balance_on():
    led = _ledger()
    assert led.balance_on("2026-01-01") == 0
    assert led.balance_on("2026-01-05") == 1000
    assert led.balance_on("2026-01-31") == 700
    assert led.balance_on("2026-02-01") == 650
    assert led.balance_on("2026-12-31") == 1650


def test_existing_methods_kept_and_working():
    original = (h.HIDDEN / "originals" / "ledger.py").read_text(encoding="utf-8")
    assert _methods(original) <= _methods(h.read("ledger.py"))
    led = _ledger()
    assert led.balance() == 1650
    assert led.total_salary() == 2000
    assert led.count_rent() == 1
    assert [e[0] for e in led.history()] == ["2026-01-05", "2026-01-10", "2026-02-01", "2026-02-05"]
