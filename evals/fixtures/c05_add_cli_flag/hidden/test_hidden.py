import conftest as h


def test_default_output_unchanged():
    proc = h.run_py("greet.py", "Ana")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "Hello, Ana!"


def test_shout_flag():
    proc = h.run_py("greet.py", "Ana", "--shout")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "HELLO, ANA!"


def test_flag_before_name():
    proc = h.run_py("greet.py", "--shout", "Bo")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "HELLO, BO!"
