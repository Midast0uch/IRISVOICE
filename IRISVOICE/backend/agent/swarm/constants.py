"""Swarm system constants."""

SWARM_STATUS_WORKING       = "working"
SWARM_STATUS_COMPOUND_OPEN = "compound_open"
SWARM_STATUS_COMPLETED     = "completed"
SWARM_STATUS_CANCELLED     = "cancelled"

SWARM_SIGNAL_READY_TO_JOIN  = "ready_to_join"
SWARM_SIGNAL_FINISHED_EARLY = "finished_early"
SWARM_SIGNAL_HELPER_JOINED  = "helper_joined"
SWARM_SIGNAL_HELPER_DONE    = "helper_done"

SWARM_POLL_INTERVAL_SECONDS = 10
SWARM_SIGNAL_EXPIRY_SECONDS = 300
SWARM_MAX_HELPERS_DEFAULT   = 2
SWARM_OPEN_AFTER_PCT        = 0.75
SWARM_FINISHED_EARLY_PCT    = 0.80

# Control code prefix — MCM: required to avoid collision with:
#   coordinate values (all 0.0–1.0 normalized floats, gates 1–5, DER steps max 40)
#   natural prose numbers ("999 tokens", "998 lines") — no prefix → no match
MCM_CTRL_PREFIX    = "MCM:"
MCM_CTRL_PRUNE     = "MCM:999"   # Prune tool-call history via DCP
MCM_CTRL_PIN       = "MCM:998"   # Pin artifact to mycelium_pins (permanent)
MCM_CTRL_COMPRESS  = "MCM:997"   # Condense context + MCM compress + recall
MCM_CTRL_BROADCAST = "MCM:996"   # Broadcast coordinate update to collective brain

CTRL_CODE_RE_PATTERN = r"\bMCM:(999|998|997|996)\s+(.{0,200})"
