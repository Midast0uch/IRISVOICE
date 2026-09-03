"""TEMP debug: dump sys.path when test_chat_persistence is imported."""

import sys

_orig = sys.meta_path


class _Probe:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in ("backend", "backend.conversation_store", "backend.iris_supervisor"):
            with open(r"C:\Users\midas\AppData\Local\Temp\opencode\syspath_dump.txt", "a") as f:
                f.write(f"[{fullname}] CWD={__import__('os').getcwd()}\n")
                for i, p in enumerate(sys.path):
                    f.write(f"  {i}: {p}\n")
                f.write("---\n")
        return None


sys.meta_path.insert(0, _Probe())
