"""Regression (eval turn 2026-09-29 18:14): the Oracle encoder caps its input.

The `done` monitor passed the whole planner prompt (every step output) as the
frame text. With no cap, one ONNX call took 28.6 s and the other consumers
timed out behind it on the single inference thread. encode() now stops adding
text tokens at _MAX_INPUT_IDS, keeping the head of the text.
"""

from backend.agent.decision_backend_onnx import _MAX_INPUT_IDS, _OnnxRunner


def _runner():
    r = _OnnxRunner.__new__(_OnnxRunner)
    r.encode_calls = 0
    r._tok_seconds = 0.0
    r._ids = lambda piece: [hash(piece) % 1000 + 1]
    r._structure = lambda task: ([7, 8, 9], [0, 1])
    return r


def test_long_text_is_capped():
    ids, positions = _runner().encode("word " * 20000, [object()])
    assert len(ids) <= _MAX_INPUT_IDS
    assert positions == [0, 1]


def test_short_text_is_untouched():
    ids, _ = _runner().encode("is the objective met", [object()])
    # structure (3) + [SEP_TEXT] (1) + 4 words + the appended "."
    assert len(ids) == 3 + 1 + 4 + 1
