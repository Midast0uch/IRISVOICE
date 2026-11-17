"""Round 4 / D3 contract: `ground(workdir, text)` is the bounded folder listing a code node
starts with. Numbered runs collapse, sizes read B / KB / MB, a few text files show their
first lines (a file NAMED in the task first), skipped folders never appear, a huge folder
returns fast and small, and it never raises. The shapes are the context eval fixtures x01
(service-logs/svc-01..14.txt) and x04 (data/{orders,zones,classes}.csv + tax.txt), built small.

The package under test is WORKBENCH_PKG / WORKBENCH_PKG_PATH (a broken copy for the failure
demonstrations)."""
import time

from backend.tests.contract._wb_common import mod

ground = mod("ground")

HEADER = "PROJECT FILES (the current folder; already listed - do not list it again):"


def _x01(root):
    d = root / "service-logs"
    d.mkdir()
    for n in range(1, 15):
        lines = [f"2026-03-14 06:12:{n:02d} svc-{n:02d} INFO  request id={n}0001 status=200"] * 60
        (d / f"svc-{n:02d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _x04(root):
    d = root / "data"
    d.mkdir()
    (d / "orders.csv").write_text("order_id,zone,weight_kg,class\n" + "ORD-0001,Z-19,17.5,standard\n" * 200, encoding="utf-8")
    (d / "zones.csv").write_text("zone,region,base_cents,per_kg_cents\nZ-01,south,716,156\n" * 20, encoding="utf-8")
    (d / "classes.csv").write_text("class,multiplier_percent\nstandard,100\n", encoding="utf-8")
    (d / "tax.txt").write_text("SHIPPING TAX RULES 2026\n" + "Tax depends on the region.\n" * 250, encoding="utf-8")


def test_x01_numbered_run_collapses_with_count_and_size_range(tmp_path):
    _x01(tmp_path)
    out = ground.ground(str(tmp_path))
    lines = out.splitlines()
    assert lines[0] == HEADER
    assert lines[1].startswith("service-logs/  14 files  svc-01.txt .. svc-14.txt  ")
    assert lines[1].endswith(" KB each")
    assert out.count("svc-02.txt") == 0 and out.count("svc-13.txt") == 0     # the run is one line
    assert lines[2].startswith("  svc-01.txt starts: 2026-03-14 06:12:01 svc-01 INFO  request id=")


def test_x04_folder_line_and_head_lines(tmp_path):
    _x04(tmp_path)
    out = ground.ground(str(tmp_path), "Read data/orders.csv and data/tax.txt")
    lines = out.splitlines()
    assert lines[0] == HEADER and lines[1].startswith("data/  ")
    for name in ("orders.csv", "zones.csv", "classes.csv", "tax.txt"):
        assert name in lines[1]
    assert " | " in lines[1] and " KB" in lines[1]
    assert "  orders.csv starts: order_id,zone,weight_kg,class" in lines
    assert "  tax.txt starts: SHIPPING TAX RULES 2026" in lines


def test_sizes_use_b_kb_mb_with_one_decimal(tmp_path):
    (tmp_path / "tiny.txt").write_bytes(b"x" * 40)
    (tmp_path / "mid.bin").write_bytes(b"x" * 1536)
    (tmp_path / "big.bin").write_bytes(b"x" * (3 * 1024 * 1024 + 512 * 1024))
    out = ground.ground(str(tmp_path))
    assert "tiny.txt 40 B" in out and "mid.bin 1.5 KB" in out and "big.bin 3.5 MB" in out


def test_total_is_bounded_and_cut_on_a_whole_line(tmp_path):
    for i in range(40):
        d = tmp_path / f"folder{i:02d}x"
        d.mkdir()
        (d / "alpha.txt").write_text("first line of this file\nsecond line\n", encoding="utf-8")
    out = ground.ground(str(tmp_path))
    assert len(out) <= 1200 and out.splitlines()[-1] == "(more files not shown)"
    assert all(len(l) <= 300 for l in out.splitlines())
    small = ground.ground(str(tmp_path), max_chars=300)
    assert len(small) <= 300 and small.splitlines()[0] == HEADER


def test_five_thousand_files_return_fast_and_small(tmp_path):
    for i in range(5000):
        (tmp_path / f"file_{i:04d}.dat").write_bytes(b"x")
    for i in range(200):
        (tmp_path / f"name{i}x.txt").write_text("a\n", encoding="utf-8")
    t0 = time.perf_counter()
    out = ground.ground(str(tmp_path))
    ms = (time.perf_counter() - t0) * 1000
    assert len(out) <= 1200 and out.startswith(HEADER)
    assert "(listing cut)" in out                       # 2,000 entries is the cap
    assert ms < 250, f"{ms:.0f} ms"                      # ~100 ms on this machine; a loose bound for CI noise


def test_skipped_folders_never_appear(tmp_path):
    for d in (".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".pytest_cache",
              ".iris-worktree", ".hidden"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "inside.txt").write_text("x", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text("print(1)\n", encoding="utf-8")
    out = ground.ground(str(tmp_path))
    assert "keep.py" in out and "inside.txt" not in out
    assert not any(d in out for d in (".git", "__pycache__", "node_modules", "venv", ".hidden", ".iris-worktree"))
    assert "inside.txt" not in " ".join(ground.ground_files(str(tmp_path)))


def test_binary_file_is_skipped_for_heads(tmp_path):
    (tmp_path / "blob.txt").write_bytes(b"\x00\x01\x02binary" * 50)
    (tmp_path / "bad.csv").write_bytes(b"\xff\xfe\xfa" * 50)
    (tmp_path / "ok.txt").write_text("hello world\n", encoding="utf-8")
    out = ground.ground(str(tmp_path), "blob.txt bad.csv")
    assert "blob.txt" in out and "bad.csv" in out            # listed...
    assert "blob.txt starts" not in out and "bad.csv starts" not in out   # ...but no head
    assert "  ok.txt starts: hello world" in out


def test_a_named_file_gets_its_head_before_others(tmp_path):
    for i in range(10):
        (tmp_path / f"a{i:02d}_note_{'x' * i}.txt").write_text(f"head of a{i}\n", encoding="utf-8")
    (tmp_path / "zzz_target.csv").write_text("target_col,other\n", encoding="utf-8")
    plain = ground.ground(str(tmp_path), max_chars=6000)
    named = ground.ground(str(tmp_path), "please open zzz_target.csv", max_chars=6000)
    assert "zzz_target.csv starts" not in plain                 # 6 heads go to the first files
    assert "  zzz_target.csv starts: target_col,other" in named
    assert named.count(" starts: ") == 6                        # at most 6 files get heads


def test_head_lines_are_two_and_cut_to_160_chars_and_read_at_most_2kb(tmp_path):
    (tmp_path / "wide.txt").write_text(("W" * 500 + "\n") + ("second\n") + "third\n", encoding="utf-8")
    out = ground.ground(str(tmp_path), max_chars=6000)
    heads = [l for l in out.splitlines() if l.startswith("  wide.txt starts: ")]
    assert len(heads) == 2 and len(heads[0]) == len("  wide.txt starts: ") + 160 and heads[1].endswith("second")
    (tmp_path / "huge.txt").write_text("a" * 100_000, encoding="utf-8")
    assert len(ground.ground(str(tmp_path), max_chars=6000)) < 6000


def test_missing_folder_never_raises_and_files_are_relative(tmp_path):
    assert ground.ground(str(tmp_path / "nope")) == ""
    assert ground.ground_files(str(tmp_path / "nope")) == []
    _x01(tmp_path)
    files = ground.ground_files(str(tmp_path))
    assert files[0] == "service-logs/svc-01.txt" and len(files) == 14


def test_an_error_inside_is_counted_not_raised(tmp_path, monkeypatch):
    _x01(tmp_path)
    before = ground.failures()
    monkeypatch.setattr(ground, "_walk", lambda *a, **k: 1 / 0)
    assert ground.ground(str(tmp_path)) == "" and ground.ground_files(str(tmp_path)) == []
    assert ground.failures() == before + 2


def test_ground_files_is_capped_at_200(tmp_path):
    for i in range(300):
        (tmp_path / f"f{i}.dat").write_bytes(b"x")
    assert len(ground.ground_files(str(tmp_path))) == 200


# ---- R2: profile=True (code nodes) - the data shows in the ground, no "look at it" script ----

_X01_HEAD = (HEADER + "\nservice-logs/  14 files  svc-01.txt .. svc-14.txt  3.6-3.7 KB each"
             "\n  svc-01.txt starts: 2026-03-14 06:12:01 svc-01 INFO  request id=10001 status=200"
             "\n  svc-01.txt starts: 2026-03-14 06:12:01 svc-01 INFO  request id=10001 status=200")
_X04_HEAD = (HEADER + "\ndata/  classes.csv 40 B | orders.csv 5.7 KB | tax.txt 6.9 KB | zones.csv 1.1 KB"
             "\n  classes.csv starts: class,multiplier_percent\n  classes.csv starts: standard,100"
             "\n  orders.csv starts: order_id,zone,weight_kg,class\n  orders.csv starts: ORD-0001,Z-19,17.5,standard"
             "\n  tax.txt starts: SHIPPING TAX RULES 2026\n  tax.txt starts: Tax depends on the region."
             "\n  zones.csv starts: zone,region,base_cents,per_kg_cents\n  zones.csv starts: Z-01,south,716,156")


def _x01_errors(root):
    d = root / "service-logs"
    d.mkdir()
    for n in range(1, 15):
        lines = [f"2026-03-14 06:{n:02d}:31 svc-{n:02d} INFO  request id={n}0001 status=200"] * 60
        lines += [f"2026-03-14 06:09:{k:02d} svc-{n:02d} ERROR [E-{3300 + k * 7}] queue overflow" for k in range(5)]
        lines += [f"2026-03-14 06:10:{k:02d} svc-{n:02d} WARN  slow call {k}ms" for k in range(3)]
        (d / f"svc-{n:02d}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _x04_rules(root):
    _x04(root)
    d = root / "data"
    (d / "tax.txt").write_text(
        "SHIPPING TAX RULES 2026\n"
        "Tax depends on the region.\n"
        "North and south regions pay 8 percent tax.\n"
        "East and west regions pay 12 percent tax.\n"
        "Round the tax to whole cents using banker's rounding (half to even).\n"
        "Apply tax after the class multiplier.\n" * 30, encoding="utf-8")
    (d / "classes.csv").write_text("class,multiplier_percent\nstandard,100\nexpress,150\n", encoding="utf-8")


def test_r2_profile_false_is_byte_equal_to_the_listing_of_today(tmp_path):
    _x01(tmp_path)
    assert ground.ground(str(tmp_path)) == _X01_HEAD
    assert ground.ground(str(tmp_path), "svc-01.txt", profile=False) == ground.ground(str(tmp_path), "svc-01.txt")
    d = tmp_path / "x"
    d.mkdir()
    _x04(d)
    assert ground.ground(str(d)) == _X04_HEAD
    assert ground.ground(str(d), "read data/classes.csv and tax.txt", profile=False) == _X04_HEAD


def test_r2_x01_profile_shows_the_error_line_shape_with_its_code_pattern(tmp_path):
    _x01_errors(tmp_path)
    out = ground.ground(str(tmp_path), "count the ERROR lines in svc-03.txt and svc-04.txt", profile=True, max_chars=4000)
    assert "svc-03.txt" in out and "svc-04.txt" in out and "svc-05.txt (" not in out
    assert "(68 lines)" in out
    assert "5x  #-#-# #:#:# svc-# ERROR [E-#] ..." in out
    assert "e.g. 2026-03-14 06:09:00 svc-03 ERROR [E-3300] queue overflow" in out
    assert "WARN" in out and "starts:" not in out


def test_r2_x04_profile_small_csv_whole_big_csv_header_rows_prose_shapes(tmp_path):
    _x04_rules(tmp_path)
    out = ground.ground(str(tmp_path), "use data/orders.csv, classes.csv and tax.txt", profile=True, max_chars=4000)
    assert "  data/classes.csv (whole file):\n    class,multiplier_percent\n    standard,100\n    express,150\n" in out
    assert ("  data/orders.csv (200 rows):\n    order_id,zone,weight_kg,class\n"
            "    ORD-0001,Z-19,17.5,standard\n    ORD-0001,Z-19,17.5,standard\n") in out
    assert "ORD-0001" not in out.split("(200 rows):")[1].split("data/")[0].split("standard\n")[2]
    assert "zones.csv (" not in out
    assert "tax.txt (180 lines):" in out
    assert "30x  Round the tax to whole ..." in out and "e.g. Round the tax to whole cents using banker's rounding (half to even)." in out
    assert out.count("30x") == 6          # the whole file repeats 6 lines x 30: all 6 shapes shown


def test_r2_a_file_of_2000_bytes_is_shown_whole(tmp_path):
    body = "[core]\nname = demo\n" + "key_%02d = value\n" % 1
    body = (body + "# pad\n" * 400)[:2000]
    (tmp_path / "settings.ini").write_bytes(body.encode())
    assert len(body.encode()) == 2000
    out = ground.ground(str(tmp_path), "edit settings.ini", profile=True, max_chars=4000)
    assert "settings.ini (whole file):\n    [core]\n    name = demo\n    key_01 = value\n    # pad" in out
    (tmp_path / "settings.ini").write_bytes((body + "x").encode())        # 2001 bytes: shapes, not whole
    assert "(whole file)" not in ground.ground(str(tmp_path), "edit settings.ini", profile=True, max_chars=4000)


def test_r2_profile_bounds_read_output_and_time(tmp_path, monkeypatch):
    big = tmp_path / "big.log"
    chunk = "2026-03-14 06:09:31 svc-14 ERROR [E-3369] queue overflow\n" * 1000
    with open(big, "w", encoding="utf-8") as fh:
        for _ in range(50 * 1024 * 1024 // len(chunk) + 1):
            fh.write(chunk)
    assert big.stat().st_size >= 50 * 1024 * 1024
    for n in range(8):
        (tmp_path / f"n{n}.txt").write_text("alpha beta gamma delta epsilon zeta %d\n" % n * 80, encoding="utf-8")
    read = []
    real_open = open

    def spy(path, mode="r", *a, **k):
        fh = real_open(path, mode, *a, **k)
        if "b" in mode and str(path).endswith("big.log"):
            real_read = fh.read
            fh.read = lambda n=-1: read.append(n) or real_read(n)
            read.append(("opened", n))
        return fh
    monkeypatch.setattr(ground, "open", spy, raising=False)
    text = "big.log " + " ".join(f"n{n}.txt" for n in range(8))
    t0 = time.perf_counter()
    out = ground.ground(str(tmp_path), text, profile=True, max_chars=1200)
    took = time.perf_counter() - t0
    reads = [r for r in read if isinstance(r, int)]
    assert reads and all(0 < r <= 256 * 1024 for r in reads)       # never more than 256 KB asked of it
    assert "big.log (~" in out and "lines):" in out                # a partial read says "~"
    assert len(out) <= 1200
    assert out.count("lines):") + out.count("whole file") <= 6      # at most 6 files
    assert took < 0.5                                                # 150 ms profile budget + walk, with slack for the disk


def test_r2_profile_time_bound_marks_the_cut(tmp_path, monkeypatch):
    for n in range(6):
        (tmp_path / f"f{n}.txt").write_text("a b c %d\n" % n * 400, encoding="utf-8")
    ticks = iter(range(0, 10_000))
    monkeypatch.setattr(ground.time, "perf_counter", lambda: next(ticks) * 0.1)   # every call = 100 ms
    out = ground.ground(str(tmp_path), "f0.txt f1.txt f2.txt f3.txt", profile=True, max_chars=4000, budget_ms=10**9)
    assert out.splitlines()[-1] == "(profile cut)"


def test_r2_profile_output_is_whole_lines_within_max_chars_and_never_raises(tmp_path, monkeypatch):
    _x04_rules(tmp_path)
    full = ground.ground(str(tmp_path), "orders.csv classes.csv tax.txt", profile=True, max_chars=4000)
    small = ground.ground(str(tmp_path), "orders.csv classes.csv tax.txt", profile=True, max_chars=500)
    assert len(small) <= 500 and len(full) > 500
    assert all(ln in full.splitlines() for ln in small.splitlines() if not ln.startswith("("))
    before = ground.failures()
    monkeypatch.setattr(ground, "_profile", lambda *a, **k: 1 / 0)
    assert ground.ground(str(tmp_path), "tax.txt", profile=True) == ""
    assert ground.failures() == before + 1
