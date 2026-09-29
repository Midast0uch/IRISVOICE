import math

import conftest as h


def test_public_names():
    from shapes import area_circle, area_square

    assert math.isclose(area_circle(2), math.pi * 4)
    assert area_square(3) == 9


def test_app_runs():
    proc = h.run_py("app.py")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "3.14 4"


def test_app_not_rewritten():
    assert h.unchanged("app.py")
