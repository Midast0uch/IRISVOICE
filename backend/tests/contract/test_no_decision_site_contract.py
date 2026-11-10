"""An earned bar changes nothing without a decision site - and the log says so.

Found 2026-11-09: route_v2 earned the bar on d1-2B and the enforcement line
read "deciding=['route_v2@0.6148']", while the kernel only ever calls
eng.shadow() for it. Nothing in the app reads decides("route_v2"), so the
"deciding" consumer decided nothing. `decision_engine.NO_DECISION_SITE` names
the switchable consumers that only write shadow rows; this pins that set
against the source in both directions, and pins the log wording.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from backend.agent import decision_engine as de

_ROOT = Path(__file__).resolve().parents[3]
_SITE = re.compile(r"\b(?:decides|oracle_acts|sampled_consult_ok)\(\s*([\"']?)(\w+)\1")
_IN_ENFORCED = re.compile(r"[\"'](\w+)[\"']\s+in\s+enforced_consumers\(\)")
_CONST = re.compile(r"^(\w+_CONSUMER)\s*(?::\s*\w+\s*)?=\s*[\"'](\w+)[\"']", re.M)


def _decision_sites() -> set:
    sources = [p for p in (_ROOT / "backend").rglob("*.py")
               if "tests" not in p.parts and p.name != "decision_engine.py"]
    texts = [p.read_text(encoding="utf-8", errors="replace") for p in sources]
    consts = {}
    for t in texts:
        consts.update(dict(_CONST.findall(t)))
    sites = set()
    for t in texts:
        for quote, name in _SITE.findall(t):
            sites.add(name if quote else consts.get(name, name))
        sites.update(_IN_ENFORCED.findall(t))
    return sites


def test_no_decision_site_matches_the_source():
    sites = _decision_sites()
    assert not (de.NO_DECISION_SITE & sites), (
        f"{sorted(de.NO_DECISION_SITE & sites)} now HAS a decision site: "
        "remove it from NO_DECISION_SITE")
    should_act = set(de.CONSUMERS) - set(de.REFUSED_CONSUMERS) - de.NO_DECISION_SITE
    assert should_act <= sites, (
        f"{sorted(should_act - sites)} has no decides()/oracle_acts() site: "
        "add it to NO_DECISION_SITE or wire its decision")
    assert de.NO_DECISION_SITE <= set(de.CONSUMERS)


def test_the_log_never_calls_a_shadow_only_consumer_deciding(monkeypatch, caplog):
    monkeypatch.setattr(de, "_owner_allow_list", lambda: {"route_v2", "tool_choice"})
    monkeypatch.setattr(de, "_enforcement", lambda c: (0.61, ""))
    monkeypatch.setattr(de, "_ENFORCEMENT_LOGGED", False)
    monkeypatch.setattr(de, "get_decision_engine", lambda: None)
    with caplog.at_level(logging.INFO, logger=de.logger.name):
        de._log_enforcement_once()
    line = next(r.getMessage() for r in caplog.records if "enforcement:" in r.getMessage())
    deciding = line.split("deciding=")[1].split(";")[0]
    assert "route_v2" not in deciding and "tool_choice@0.61" in deciding, line
    assert "route_v2 (earned @0.61, but no decision site: shadow only)" in line, line
