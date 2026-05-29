"""Shared fixtures for memory tests."""
import os
import shutil
import sys
import tempfile
import pytest


@pytest.fixture
def temp_db_path():
    """Create a temporary database path with Windows-safe cleanup."""
    tmpdir = tempfile.mkdtemp()
    yield os.path.join(tmpdir, "test.db")
    if sys.platform == "win32":
        shutil.rmtree(tmpdir, ignore_errors=True)
    else:
        shutil.rmtree(tmpdir)


@pytest.fixture
def biometric_key():
    """Create a test biometric key."""
    return b"test_key_32_bytes_long_for_testing_"
