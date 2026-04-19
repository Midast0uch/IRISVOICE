"""TemporalCoordinate — 4D routing temporal state."""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

from .constants import IMMORTUS_MOMENTUM_DECAY, IMMORTUS_VELOCITY_SMOOTHING


@dataclass
class TemporalCoordinate:
    """
    Tracks temporal state through an Immortus execution thread.

    Fields:
        momentum:         0.0-1.0 — execution energy; decays per step.
        drift:            0.0-1.0 — deviation from committed route; grows on failures.
        velocity:         smoothed EMA of step completion rate.
        identifier_depth: cumulative depth contributions from completed steps.
    """
    momentum:         float = 1.0
    drift:            float = 0.0
    velocity:         float = 0.5
    identifier_depth: int   = 0

    @classmethod
    def cold(cls) -> "TemporalCoordinate":
        """Initial coordinate at session start."""
        return cls(momentum=1.0, drift=0.0, velocity=0.5, identifier_depth=0)

    def stability_score(self, confidence: float = 1.0) -> float:
        """
        Combined stability signal used by TrailingDirector to find stable_anchor.
        Higher = more stable = better pivot anchor.

        Formula: confidence * (1 + log(identifier_depth + 1)) * (1 - drift)
        """
        depth_factor = 1.0 + math.log(self.identifier_depth + 1)
        return confidence * depth_factor * (1.0 - self.drift)

    @classmethod
    def update(
        cls,
        prev: "TemporalCoordinate",
        step_succeeded: bool,
        queue_remaining: int,
        route_score: float = 1.0,
    ) -> "TemporalCoordinate":
        """
        Produce a new TemporalCoordinate after a step completes.

        - momentum decays by MOMENTUM_DECAY; boosted if step succeeded.
        - drift increases on failure; reset toward 0 on success.
        - velocity EMA updated from route_score.
        - identifier_depth incremented by 1 per completed step.
        """
        if step_succeeded:
            new_momentum = min(1.0, prev.momentum - IMMORTUS_MOMENTUM_DECAY + 0.05)
            new_drift    = max(0.0, prev.drift - 0.05)
        else:
            new_momentum = max(0.0, prev.momentum - IMMORTUS_MOMENTUM_DECAY * 2)
            new_drift    = min(1.0, prev.drift + 0.10)

        new_velocity = (
            (1 - IMMORTUS_VELOCITY_SMOOTHING) * prev.velocity
            + IMMORTUS_VELOCITY_SMOOTHING * route_score
        )

        return cls(
            momentum         = round(new_momentum, 4),
            drift            = round(new_drift, 4),
            velocity         = round(new_velocity, 4),
            identifier_depth = prev.identifier_depth + 1,
        )
