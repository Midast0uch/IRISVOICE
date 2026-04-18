"""Immortus 4D routing — tuned constants."""

# Activation gate
IMMORTUS_DEPTH_THRESHOLD        = 3      # min dependency depth to activate
IMMORTUS_CLARITY_THRESHOLD      = 0.70   # min task clarity for SYNTHETIC_TRAILS
IMMORTUS_NOVELTY_THRESHOLD      = 0.50   # novelty above this → USER_CONSULT

# Drift / stability
IMMORTUS_DRIFT_CRITICAL         = 0.40   # drift above this triggers pivot check
IMMORTUS_DRIFT_WARNING          = 0.25   # soft warning level

# Route arbitration
IMMORTUS_ROUTE_PIVOT_THRESHOLD  = 0.20   # projected - latent_current gap to trigger pivot
IMMORTUS_ROUTE_MAX_PIVOTS       = 2      # max pivots per session
IMMORTUS_ROUTE_CHECK_MIN_STEPS  = 3      # min completed steps before route check fires

# Scoring weights
IMMORTUS_DEPTH_LOG_WEIGHT       = 0.10   # log(depth+1) factor in route scoring
IMMORTUS_INTERSECTION_BOOST     = 0.15   # pheromone boost when 2+ threads share edge

# Thread condense
IMMORTUS_CONDENSE_DEPTH_THRESHOLD       = 10    # identifier_depth >= this → condense candidate
IMMORTUS_CONDENSE_CONFIDENCE_THRESHOLD  = 0.65  # confidence >= this → condense candidate

# Temporal scoring
IMMORTUS_MOMENTUM_DECAY         = 0.05   # per-step momentum decay
IMMORTUS_VELOCITY_SMOOTHING     = 0.30   # EMA weight for velocity updates
IMMORTUS_STABILITY_BASE         = 1.0    # base factor for stability_score
