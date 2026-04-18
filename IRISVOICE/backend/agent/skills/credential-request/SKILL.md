---
name: credential-request
description: This skill should be used when IRIS needs a credential, API key, token, or secret to proceed with a task but does not have it. Use it to notify the user via Telegram and suspend work on the blocked feature until the credential arrives.
---

# Credential Request

When IRIS is blocked on a task because it needs a credential (API key, token, password, bot token, etc.) that the user has not yet provided, follow this protocol:

## When to Use

Use this skill whenever the agent:
- Cannot proceed because an API key or secret is missing
- Needs a bot token, webhook URL, or OAuth token
- Is blocked on authentication for any external service (GitHub, OpenAI, Telegram, etc.)

## Protocol (3 steps, in order)

### Step 1 — Notify via Telegram

Call `get_telegram_bridge().notify_credential_needed(service, what_is_needed)`:

```python
from backend.channels.telegram_bridge import get_telegram_bridge
bridge = get_telegram_bridge()
result = bridge.notify_credential_needed(
    service="github",                         # service name (lowercase, no spaces)
    what_is_needed=(
        "GitHub personal access token with repo scope. "
        "Needed to create PRs and read issues. "
        "Create at: https://github.com/settings/tokens"
    )
)
```

The message will be delivered to the user's Telegram chat. If Telegram is not configured, log the need and continue.

### Step 2 — Record a gradient warning

After notifying, record the block so future sessions know not to retry this path:

```python
from bootstrap.record_event import record_event
# OR if in agent context:
# self._memory_interface.mycelium_ingest_statement(
#     statement=f"BLOCKED: need {service} credential — notified via Telegram",
#     session_id=session_id
# )
```

The warning text format: `"blocked on auth for [service] — awaiting credential via Telegram"`

### Step 3 — Pivot to other work

Do NOT retry the blocked task. Do NOT ask the user the same question repeatedly.

Instead:
1. Tell the user clearly what was needed and that you have sent them a Telegram message
2. Switch to a different task that does not require the missing credential
3. On the next session start, check if the credential has arrived before resuming

## Example Response to User

> "I need a GitHub token to create that PR. I have sent you a Telegram message with instructions. In the meantime, I will work on [alternative task]."

## When Telegram is Not Configured

If `notify_credential_needed` returns `{"success": False, "error": "Telegram not configured"}`:
1. Tell the user directly in the chat what credential is needed and where to get it
2. Record the block in memory
3. Pivot to other work

## Credential Arrival

When a credential arrives (user types it in chat or sets it in settings):
1. Store it securely using the credential store: `from backend.integrations.credential_store import CredentialStore`
2. Resume the blocked task
3. Record that the block is resolved
