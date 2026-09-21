import io
import contextlib
import sys

sys.argv = ["validate_vision_browser_e2e.py", "--json"]
import scripts.validate_vision_browser_e2e as h

buf = io.StringIO()
code = 0
with contextlib.redirect_stdout(buf):
    try:
        code = h.main()
    except SystemExit as e:
        code = e.code
io.open("_harness_out.txt", "w", encoding="utf-8").write(
    buf.getvalue() + "\nEXIT=" + str(code)
)
print("done")
