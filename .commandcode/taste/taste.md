# Taste (Continuously Learned by [CommandCode][cmd])

[cmd]: https://commandcode.ai/

# architecture
- Conversation thread identity must persist across widget lifecycle events — component unmounts, drags, and reconnects should not lose or reset the active conversation thread. Confidence: 0.85
- When a new conversation thread is started, old thread context and content must not interfere — strict conversation isolation is required, not just in-memory state that can leak across thread boundaries. Confidence: 0.85
- On WS reconnect, include `current_conversation_id` in the `initial_state` payload from the backend and have the frontend adopt it (backend authoritative as tiebreaker), so frontend/backend stay in lockstep about the active thread. Confidence: 0.72

# error-handling
- When fixing local model loading/wiring, verify end-to-end parity between local inference and API-provider inference — ensure the loaded model drives reasoning, tool calls, and streaming through the exact same call surface as the API path. Confidence: 0.72
- Test that model loading does not cause memory spikes or bloat — verify resource stability at load time alongside functional correctness. Confidence: 0.70
- Never let model loads fail or load silently — always log both start and completion (success or failure) visibly so progress and errors can be traced. Confidence: 0.88
- Ensure the audio pipeline has thorough logging at every stage so bugs and errors can be caught early. Confidence: 0.85

# configuration
- Always load `.env.local` (with override) in addition to `.env`, since real API keys live in `.env.local` and `.env` only holds placeholders. Confidence: 0.78

# python
- Always use `venv\Scripts\python.exe -m uvicorn` instead of `venv\Scripts\uvicorn` — the uvicorn.exe may resolve to a system Python that lacks project dependencies (e.g., pvporcupine). Confidence: 0.70
- When the backend must survive non-UTF-8 stdout (piped/background shells on Windows), add a `-X utf8` self-reexec check at the very top of `start-backend.py` (`if not sys.flags.utf8_mode: os.execl(sys.executable, sys.executable, "-X", "utf8", *sys.argv)`) — this is more reliable than setting `PYTHONUTF8=1` in the shell, which fails in background tasks. Without it the `→` character in `agent_kernel.py set_launcher_mode()` logger f-string causes a `UnicodeEncodeError` that crashes the lifespan context before uvicorn can bind. Confidence: 0.88

# local-model
See [local-model/taste.md](local-model/taste.md)
# workflow
# performance
- When importing pocket_tts, no-op beartype_this_package monkeypatch before the import to cut startup from ~40s to ~4s — beartype runtime type-checking is unnecessary in production and has no effect on model output quality. Confidence: 0.70

# debugging
See [debugging/taste.md](debugging/taste.md)
# python
- On Windows, httpx SSL connections to remote APIs (e.g., api.cerebras.ai) can fail with `CRYPT_E_NO_REVOCATION_CHECK` due to Windows Schannel revocation checking. Fix by passing `verify=get_ssl_context()` from a custom context that keeps CA + hostname validation but disables revocation via `ctx.verify_flags = ssl.VERIFY_DEFAULT & ~ssl.VERIFY_CRL_CHECK_CHAIN`. Confidence: 0.80
- pocket_tts `TTSModel.generate_audio_stream()` takes positional args `(voice_state, text)`, not keyword `text=`. The filler pre-synthesis must pass `self._voice_state, phrase` positionally. Confidence: 0.75

See [workflow/taste.md](workflow/taste.md)
