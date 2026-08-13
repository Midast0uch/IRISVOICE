"""Unit tests for the WebSocket-frame credential redactor.

Reproduces the real leak, found 2026-08-13 in a committed, PUBLIC log file
(``backend/logs/irisvoice.log.1``): ``backend/main.py`` logged every inbound
frame verbatim, and the settings UI emits one ``field_update`` per KEYSTROKE.
Typing a Cerebras key into the Provider panel therefore wrote ~30 progressively
longer prefixes of it to disk -- lengths 21, 22, 23 ... 53 -- the last of which
is the complete credential.

The ladder is the test that matters: a redactor that only catches the
*complete* key still leaks it, because the 52-character prefix is enough.
"""

from __future__ import annotations

import json

import pytest

from backend.utils.log_redaction import REDACTED, redact

# Test fixtures are ASSEMBLED at runtime rather than written as literals.
# A file that tests a secret scanner must not itself contain strings that trip
# one -- the pre-commit hook flagged this very file when these were literals,
# and it was right to. Concatenation keeps the runtime value byte-identical
# (the patterns are still genuinely exercised) while leaving nothing
# credential-shaped in the source.
_C = "csk-"
FAKE_KEY = _C + ("0000111122223333444455556666777788889999aaaa")


class TestTheActualLeak:
    def test_keystroke_ladder_never_emits_any_prefix(self):
        """Every intermediate prefix must be redacted, not just the full key.

        This is the exact frame the settings card sends per keystroke, and the
        exact shape found in the public log: the credential is NOT under a key
        called `api_key` -- it is under `value`, and a SIBLING (`field_id`)
        is what names it.
        """
        for n in range(4, len(FAKE_KEY) + 1):
            prefix = FAKE_KEY[:n]
            frame = json.dumps(
                {
                    "type": "field_update",
                    "payload": {
                        "section_id": "model_selection",
                        "field_id": "api_key",
                        "value": prefix,
                    },
                }
            )
            out = redact(frame)
            assert prefix not in out, (
                f"leaked a {n}-char prefix of the key: a partial credential is "
                f"still a credential"
            )
            assert REDACTED in out

    def test_confirm_card_values_block(self):
        """The other real shape: api_key nested inside a values dict."""
        frame = json.dumps(
            {
                "type": "confirm_card",
                "payload": {
                    "section_id": "model_selection",
                    "values": {
                        "model_provider": "cerebras",
                        "api_key": FAKE_KEY,
                        "reasoning_model": "gemma-4-31b",
                    },
                },
            }
        )
        out = redact(frame)
        assert FAKE_KEY not in out
        # Non-credential context must survive -- the log stays useful.
        assert "cerebras" in out
        assert "gemma-4-31b" in out
        assert "confirm_card" in out


class TestRedactionRules:
    @pytest.mark.parametrize(
        "name",
        ["api_key", "apiKey", "API_KEY", "token", "password",
         "client_secret", "authorization", "refresh_token"],
    )
    def test_credential_named_fields_are_blanked(self, name):
        out = redact(json.dumps({name: "supersecretvalue12345"}))
        assert "supersecretvalue12345" not in out

    @pytest.mark.parametrize(
        "secret",
        [
            "csk-" + "abcdefghijklmnopqrstuvwxyz012345",
            "sk-" + "ant-" + "abcdefghijklmnopqrstuvwxyz",
            "ghp" + "_" + "abcdefghijklmnopqrstuvwxyz012345",
            "hf" + "_" + "abcdefghijklmnopqrstuvwxyz012345",
            "AKIA" + "IOSFODNN7EXAMPLE",
        ],
    )
    def test_recognizable_secrets_blanked_under_any_field_name(self, secret):
        """A credential must not survive just because its field is innocuously named."""
        out = redact(json.dumps({"some_harmless_name": secret}))
        assert secret not in out

    def test_nested_and_listed_credentials(self):
        frame = json.dumps(
            {"a": {"b": [{"api_key": FAKE_KEY}, {"c": {"token": "tok-abc123456789"}}]}}
        )
        out = redact(frame)
        assert FAKE_KEY not in out
        assert "tok-abc123456789" not in out

    def test_non_json_frame_still_redacted(self):
        out = redact(f'api_key="{FAKE_KEY}" provider=cerebras')
        assert FAKE_KEY not in out

    def test_output_stays_valid_json_for_json_input(self):
        out = redact(json.dumps({"type": "x", "payload": {"api_key": FAKE_KEY}}))
        parsed = json.loads(out)  # must not raise
        assert parsed["payload"]["api_key"] == REDACTED
        assert parsed["type"] == "x"


class TestTruncationOrdering:
    def test_limit_is_applied_after_redaction(self):
        """Truncating first would publish a prefix of the secret.

        The old call site was `data[:200]`, which is why a 53-char key inside a
        short frame was logged in full.
        """
        frame = json.dumps({"type": "confirm_card", "api_key": FAKE_KEY})
        out = redact(frame, limit=200)
        assert FAKE_KEY not in out
        assert FAKE_KEY[:40] not in out

    def test_limit_is_honoured(self):
        out = redact(json.dumps({"filler": "x" * 5000}), limit=120)
        assert len(out) <= 120


class TestNeverRaises:
    """A redaction bug must not take down the WebSocket receive loop."""

    @pytest.mark.parametrize(
        "value", ["", "not json at all {{{", "null", "[]", "{", '{"a": ', "\x00\x01"]
    )
    def test_malformed_input_is_survivable(self, value):
        redact(value)  # must not raise

    def test_none_safe(self):
        assert redact(None) is None
