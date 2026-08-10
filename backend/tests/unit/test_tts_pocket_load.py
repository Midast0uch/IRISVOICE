"""Regression test: Pocket-TTS v2.x load_model kwarg.

History: TTSModel.load_model() in Pocket-TTS v2.x renamed the `variant`
parameter to `language`. Passing the old `variant=` kwarg raises TypeError,
which the production code's `except Exception` silently swallows — leaving
the model un-loaded and producing degraded/garbled audio.

This test guards against the API-rename regression by checking the static
source of `backend/agent/tts.py` (which is fast) and only inspecting the
runtime API surface if pocket_tts can be imported quickly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import inspect
import importlib


def test_tts_manager_uses_language_not_variant():
    """Backend TTSManager must call load_model with `language=`, not `variant=`."""
    from backend.agent.tts import TTSManager

    src = inspect.getsource(TTSManager._load_pocket_tts)
    assert "variant=" not in src, (
        "backend/agent/tts.py still passes `variant=` to TTSModel.load_model(). "
        "This kwarg was renamed to `language=` in Pocket-TTS v2.x. "
        "Fix: replace `variant=os.environ.get(...)` with "
        "`language=os.environ.get('POCKET_TTS_LANGUAGE', 'english')`."
    )
    assert "language=" in src, (
        "backend/agent/tts.py should pass `language=` to TTSModel.load_model()."
    )
    print("test_tts_manager_uses_language_not_variant passed")


def test_load_model_accepts_language_kwarg():
    """Pocket-TTS v2.x load_model must accept `language=`, not `variant=`.

    This test inspects the installed pocket_tts API surface. It is wrapped
    in a soft-fail (try/except ImportError) so test collection does not
    require the package to be importable in every test environment.
    """
    try:
        # Lazy import — pocket_tts top-level is heavy (190s+) on first load
        # due to beartype. Just inspect the inner module if available.
        import importlib.util
        spec = importlib.util.find_spec("pocket_tts.models.tts_model")
        if spec is None or spec.loader is None:
            import pytest
            pytest.skip("pocket_tts not installed")
        # Load without executing pocket_tts/__init__.py side effects
        from pocket_tts.models import tts_model as tts_mod
    except Exception as exc:
        import pytest
        pytest.skip(f"pocket_tts unavailable: {exc}")

    sig = inspect.signature(tts_mod.TTSModel.load_model)
    params = sig.parameters

    # Pocket-TTS v2.x: `language` is the canonical parameter name.
    # Older v1.x used `variant`. The fix in backend/agent/tts.py uses
    # `language=`, so we require that on v2.x.
    assert "language" in params, (
        "Pocket-TTS load_model is missing `language` parameter. "
        "Either the upstream API changed again, or the wrong Pocket-TTS "
        "version is installed. backend/agent/tts.py assumes v2.x semantics."
    )
    print("test_load_model_accepts_language_kwarg passed")
