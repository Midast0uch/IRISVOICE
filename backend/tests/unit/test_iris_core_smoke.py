"""
Smoke test for iris_core.dll FFI — loads the DLL and exercises all 10 functions.
Run with: python -m pytest backend/tests/test_iris_core_smoke.py -v
"""
import ctypes
import json
import os
import tempfile
import unittest
from pathlib import Path


class TestIrisCoreDLL(unittest.TestCase):
    """End-to-end smoke test against the compiled C++ core."""

    @classmethod
    def setUpClass(cls):
        cls.dll_path = Path(__file__).parent.parent.parent / "backend" / "native" / "iris_core.dll"
        if not cls.dll_path.exists():
            # Try build dir
            cls.dll_path = (
                Path(__file__).parent.parent.parent
                / "src-tauri" / "src" / "iris_core" / "build" / "Release" / "iris_core.dll"
            )
        if not cls.dll_path.exists():
            raise FileNotFoundError(f"iris_core.dll not found at expected paths")

        cls.lib = ctypes.CDLL(str(cls.dll_path))

        # --- argtypes / restype ---
        cls.lib.init_core_engine.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        cls.lib.init_core_engine.restype = ctypes.c_int

        cls.lib.shutdown_core_engine.argtypes = []
        cls.lib.shutdown_core_engine.restype = ctypes.c_int

        cls.lib.core_health_check.argtypes = []
        cls.lib.core_health_check.restype = ctypes.c_int

        cls.lib.ingest_event.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p
        ]
        cls.lib.ingest_event.restype = ctypes.c_int

        cls.lib.caducean_recommend.argtypes = [ctypes.c_char_p]
        cls.lib.caducean_recommend.restype = ctypes.c_int

        cls.lib.caducean_get_xi.argtypes = [ctypes.c_char_p]
        cls.lib.caducean_get_xi.restype = ctypes.c_double

        cls.lib.caducean_update.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_double]
        cls.lib.caducean_update.restype = None

        cls.lib.calculate_eml.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double)
        ]
        cls.lib.calculate_eml.restype = ctypes.c_double

        cls.lib.immortus_chain_append.argtypes = [
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
            ctypes.c_char_p, ctypes.c_char_p
        ]
        cls.lib.immortus_chain_append.restype = ctypes.c_int

        cls.lib.immortus_chain_keep_latest.argtypes = [
            ctypes.c_char_p, ctypes.c_int
        ]
        cls.lib.immortus_chain_keep_latest.restype = ctypes.c_int

        # Create temp DB
        cls.db_fd, cls.db_path = tempfile.mkstemp(suffix=".db")
        os.close(cls.db_fd)

        rc = cls.lib.init_core_engine(
            cls.db_path.encode("utf-8"),
            b"0" * 64  # 64-char dummy hex key
        )
        if rc != 0:
            raise RuntimeError(f"init_core_engine failed with rc={rc}")

    @classmethod
    def tearDownClass(cls):
        cls.lib.shutdown_core_engine()
        try:
            os.unlink(cls.db_path)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def test_health_check(self):
        self.assertEqual(self.lib.core_health_check(), 1)

    # ------------------------------------------------------------------
    # Event Ingestion
    # ------------------------------------------------------------------

    def test_ingest_event(self):
        rc = self.lib.ingest_event(
            b"sess_smoke", b"CODE", b"file_edit",
            b"agent", b"success", b"Edited CMakeLists.txt",
            json.dumps({"file": "CMakeLists.txt", "lines": 5}).encode("utf-8")
        )
        self.assertEqual(rc, 0)

    def test_ingest_event_with_sensitive_payload(self):
        """RE2 sanitizer should scrub API keys."""
        rc = self.lib.ingest_event(
            b"sess_smoke", b"USER", b"text_message",
            b"user", b"pending", b"User sent message",
            b'{"text": "Here is my key: sk-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz567abc890def123ghi456jkl"}'
        )
        self.assertEqual(rc, 0)

    # ------------------------------------------------------------------
    # Caducean
    # ------------------------------------------------------------------

    def test_caducean_initial_state(self):
        xi = self.lib.caducean_get_xi(b"sess_cad")
        self.assertAlmostEqual(xi, 0.0, places=5)
        rec = self.lib.caducean_recommend(b"sess_cad")
        self.assertEqual(rec, 2)  # CONTINUE (no state yet)

    def test_caducean_update_and_recommend(self):
        # EXPAND action (0) with balance=1.0 → u += s*cos(0) = 0.35
        self.lib.caducean_update(b"sess_cad2", 0, 1.0)
        rec = self.lib.caducean_recommend(b"sess_cad2")
        # u=0.35, |u|>=0.2 so skip stable orbit
        # F = 2*0.35 - 2*0.35^3 = 0.7 - 0.08575 = 0.61425 > 0.05 → COMPRESS (1)
        self.assertEqual(rec, 1)

        # xi after one update: fmod(0 + 1.0*0.35, 2pi) = 0.35
        xi = self.lib.caducean_get_xi(b"sess_cad2")
        self.assertAlmostEqual(xi, 0.35, places=5)

        # Multiple COMPRESS actions (1) to push u negative (4 steps keeps u unclamped)
        for _ in range(4):
            self.lib.caducean_update(b"sess_cad2", 1, 1.0)
        rec = self.lib.caducean_recommend(b"sess_cad2")
        # u ≈ -0.64, F ≈ -0.75 < -0.05 → EXPAND (0)
        self.assertEqual(rec, 0)

    # ------------------------------------------------------------------
    # EML
    # ------------------------------------------------------------------

    def test_calculate_eml_empty(self):
        x = ctypes.c_double(0.0)
        y = ctypes.c_double(0.0)
        eml = self.lib.calculate_eml(b"sess_eml_empty", ctypes.byref(x), ctypes.byref(y))
        # Per plan formula: x=0, y=1e-5 → EML = e^0 - ln(1e-5) = 1 + 11.513 = 12.513
        self.assertAlmostEqual(eml, 12.512925, places=3)
        self.assertEqual(x.value, 0.0)
        self.assertAlmostEqual(y.value, 1e-5, places=8)

    def test_calculate_eml_with_events(self):
        # Seed some events
        for i in range(3):
            self.lib.ingest_event(
                b"sess_eml", b"CODE", b"file_edit",
                b"agent", b"success", f"Edit {i}".encode(),
                json.dumps({"file": f"file{i}.py"}).encode()
            )
        for i in range(3):
            self.lib.ingest_event(
                b"sess_eml", b"CODE", b"test_run",
                b"agent", b"success", f"Test {i}".encode(),
                json.dumps({"test": f"test_{i}"}).encode()
            )

        x = ctypes.c_double(0.0)
        y = ctypes.c_double(0.0)
        eml = self.lib.calculate_eml(b"sess_eml", ctypes.byref(x), ctypes.byref(y))
        # EML should be a non-negative finite number
        self.assertTrue(eml >= 0.0)
        self.assertTrue(x.value >= 0.0)
        self.assertTrue(y.value >= 0.0)

    # ------------------------------------------------------------------
    # Immortus
    # ------------------------------------------------------------------

    def test_immortus_chain_append(self):
        rc = self.lib.immortus_chain_append(
            b"thread_1", b"Result A",
            b"0.1,0.2,0.3", b"0.4,0.5,0.6",
            b"success", b"Insight 1",
            b"/path/to/file.py", b"landmark_1"
        )
        self.assertEqual(rc, 0)

    def test_immortus_chain_keep_latest(self):
        # Append 5 entries
        for i in range(5):
            self.lib.immortus_chain_append(
                b"thread_2", f"Result {i}".encode(),
                None, None, None, None, None, None
            )
        # Keep only latest 2
        deleted = self.lib.immortus_chain_keep_latest(b"thread_2", 2)
        self.assertEqual(deleted, 3)


if __name__ == "__main__":
    unittest.main()
