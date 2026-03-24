"""
DER Constants
File: IRISVOICE/backend/agent/der_constants.py

All DER loop constants in one place.
Source: specs/director_mode_system.md (Req 35) + bootstrap/GOALS.md Step 1.5

Gate 1 Step 1.5
"""

# ── Trailing crystallizer gap range ──────────────────────────────────────

TRAILING_GAP_MIN = 2   # minimum completed steps between crystallizer checks
TRAILING_GAP_MAX = 4   # maximum gap before crystallizer must run

# ── Token budgets per mode (replaces cycle count limit) ──────────────────

DER_TOKEN_BUDGETS = {
    "SPEC":      60_000,
    "RESEARCH":  80_000,
    "IMPLEMENT": 40_000,
    "DEBUG":     30_000,
    "TEST":      40_000,
    "REVIEW":    20_000,
    "DEFAULT":   40_000,   # fallback when mode unknown
    # lowercase aliases — agent_kernel uses mode.value which may be lowercase
    "spec":      60_000,
    "research":  80_000,
    "implement": 40_000,
    "debug":     30_000,
    "test":      40_000,
    "review":    20_000,
    "default":   40_000,
}

# ── Safety limits ─────────────────────────────────────────────────────────

DER_EMERGENCY_STOP    = 200   # cycle count emergency brake (last resort only)
DER_MAX_VETO_PER_ITEM = 2     # max times Reviewer can veto one item before skip
DER_MAX_CYCLES        = 40    # hard cycle cap (secondary to token budget)
DER_WRITE_LOCK_TIMEOUT = 5.0  # seconds — Mycelium write lock timeout
