import conftest as h


def test_new_name_works():
    from billing import core
    from billing.report import report

    assert core.compute_total([(2.5, 2), (1, 3)]) == 8.0
    assert report([(2.5, 2), (1, 3)]) == "Total: 8.00"


def test_old_name_gone_everywhere():
    from billing import core

    assert not hasattr(core, "calc_total")
    offenders = [str(p) for p in h.py_files() if "calc_total" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_main_still_runs():
    proc = h.run_py("main.py")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "Total: 5.00"
