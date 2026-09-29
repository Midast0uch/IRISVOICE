"""Per-consumer enforcement bar record (REQ-31 AC31.5/AC31.6, T52).

The EVIDENCE TRAIL behind every enforcement decision: for each consumer, the
measured bar (rows, precision, ECE) that justified its flip OR its continued
shadow status.

Two things this exists to make impossible:
  * "why is this consumer enforced?" being unanswerable — the record names the
    rows, precision and ECE behind each decision; and
  * a flip measured at a SUPERSEDED configuration quietly surviving — the
    record stores the configuration it was measured at, so AC31.6's
    "no flip measured at a superseded configuration shall stand" is checkable
    rather than assumed.

The bar itself is TG-7's (authoritative per Decision C): >= 100 rows AND
precision >= 0.90 AND ECE within bound. A consumer that fails ANY clause stays
in SHADOW with the gap recorded — never a partial flip (AC18.4, AC22.4).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("consumer_bar")

# The repo-relative record. A temp path would be invisible to the next run.
BAR_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "benchmarks" / "consumer_bar_record.json"
)

# TG-7's bar (Decision C: the authoritative enforcement gate).
MIN_ROWS = 100
MIN_PRECISION = 0.90
# REQ-18 AC18.4: the ECE bound a flip must ALSO clear. A consumer with no
# measured ECE cannot be flipped on precision alone.
MAX_ECE = 0.05


@dataclass(frozen=True)
class ConsumerBar:
    consumer_id: str
    rows: int
    precision: float
    ece: Optional[float]
    status: str          # "enforced" | "shadow"
    gap: str = ""        # why it is NOT enforced ("" when enforced)
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def flipped(self) -> bool:
        return self.status == "enforced"


def derive_status(
    rows: int,
    precision: float,
    ece: Optional[float],
    *,
    min_rows: int = MIN_ROWS,
    min_precision: float = MIN_PRECISION,
    max_ece: float = MAX_ECE,
) -> Tuple[str, str]:
    """``(status, gap)`` for one consumer's measurements.

    Returns ``("enforced", "")`` only when EVERY clause holds. Otherwise
    ``("shadow", <the first missing clause>)`` — the gap is recorded, never
    rounded up into a flip (AC22.4: no enforcement below the bar).
    """
    if rows < min_rows:
        return "shadow", f"rows {rows} < {min_rows}"
    if precision < min_precision:
        return "shadow", f"precision {precision:.3f} < {min_precision:.2f}"
    if ece is None:
        # AC18.4: precision alone is NOT enough — an uncalibrated distribution
        # may not be enforced on.
        return "shadow", "ECE not measured (precision alone cannot flip)"
    if ece > max_ece:
        return "shadow", f"ECE {ece:.3f} > {max_ece:.2f}"
    return "enforced", ""


def build_bar(
    consumer_id: str,
    measured: Dict[str, Any],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> ConsumerBar:
    """One consumer's bar record from its measured numbers."""
    rows = int(measured.get("rows") or 0)
    precision = float(measured.get("precision") or 0.0)
    ece_raw = measured.get("ece")
    ece = None if ece_raw is None else float(ece_raw)
    status, gap = derive_status(rows, precision, ece)
    return ConsumerBar(
        consumer_id=consumer_id, rows=rows, precision=round(precision, 4),
        ece=None if ece is None else round(ece, 4), status=status, gap=gap,
        config=dict(config or {}),
    )


def record_bars(
    measured: Dict[str, Dict[str, Any]],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, ConsumerBar]:
    """Build and persist the bar record for every measured consumer."""
    record = {
        cid: build_bar(cid, m, config=config)
        for cid, m in (measured or {}).items()
    }
    save_bar_record(record)
    return record


def save_bar_record(record: Dict[str, ConsumerBar], path: Optional[Path] = None) -> None:
    """Persist the record. Best-effort — never raises."""
    target = Path(path) if path else BAR_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {cid: asdict(bar) for cid, bar in record.items()},
                indent=2, sort_keys=True,
            ),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001 — recording is best-effort
        logger.warning("consumer_bar: write failed (%r)", e)


def load_bar_record(path: Optional[Path] = None) -> Dict[str, ConsumerBar]:
    """Read the record. An absent/unreadable file is EMPTY, never fatal."""
    target = Path(path) if path else BAR_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, ConsumerBar] = {}
    for cid, payload in (raw or {}).items():
        try:
            out[cid] = ConsumerBar(**payload)
        except Exception:  # noqa: BLE001 — a malformed row is skipped
            continue
    return out


def superseded_flips(
    record: Dict[str, ConsumerBar],
    deployed: Dict[str, Any],
) -> list:
    """AC31.6: consumers ENFORCED on a configuration that has since moved.

    Returns their ids. A flip is only valid for the configuration it was
    measured at; when the deployed backend/cap/variant differs, the flip must
    be re-validated (or reverted to shadow) rather than silently standing.
    """
    out: list = []
    for cid, bar in (record or {}).items():
        if not bar.flipped:
            continue
        measured_at = bar.config or {}
        for key in ("candidate_cap", "backend_id", "variant"):
            if key in measured_at and key in deployed:
                if measured_at[key] != deployed[key]:
                    out.append(cid)
                    break
    return sorted(out)
