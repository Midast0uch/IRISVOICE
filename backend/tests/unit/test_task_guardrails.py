"""Unit tests for task-level semantic guardrails (REQ-20, T4).

Guardrails evaluate BEFORE element-role checks (AC20.1) and cover the four
declarative constraints (AC20.2); violations carry the rejecting guardrail
for trajectory recording (AC20.3).
"""

from backend.vision.action_allowlist import (
    ActionAllowlist,
    ActionType,
    TaskGuardrail,
    UIAction,
    evaluate_task_guardrails,
    validate_with_guardrails,
)


def _click(name="Read more", role="button", url="https://example.com/a"):
    return {"action_type": "click", "target_name": name,
            "target_role": role, "url": url}


def test_no_guardrails_configured_passes():
    assert evaluate_task_guardrails([], _click()).allowed
    assert evaluate_task_guardrails(None, _click()).allowed


def test_no_purchase_blocks_buy_signals():
    for name in ("Buy now", "Add to Cart", "Proceed to checkout"):
        res = evaluate_task_guardrails(["NO_PURCHASE"], _click(name=name))
        assert not res.allowed and res.violated == "NO_PURCHASE", name
    assert evaluate_task_guardrails(["NO_PURCHASE"], _click()).allowed


def test_domain_bound_blocks_off_domain_only_when_configured():
    page_action = {"action_type": "click", "target_name": "Read more",
                   "target_role": "button"}  # no own URL: context page governs
    ctx = {"allowed_domains": ["example.com"], "url": "https://evil.test/x"}
    res = evaluate_task_guardrails(["DOMAIN_BOUND"], page_action, ctx)
    assert not res.allowed and res.violated == "DOMAIN_BOUND"
    # Subdomains of an allowed domain pass; unconfigured bounds pass.
    ok = {"allowed_domains": ["example.com"], "url": "https://docs.example.com/x"}
    assert evaluate_task_guardrails(["DOMAIN_BOUND"], _click(), ok).allowed
    assert evaluate_task_guardrails(["DOMAIN_BOUND"], _click()).allowed


def test_max_depth_blocks_beyond_limit():
    res = evaluate_task_guardrails(["MAX_DEPTH"], _click(),
                                   {"depth": 4, "max_depth": 3})
    assert not res.allowed and res.violated == "MAX_DEPTH"
    assert evaluate_task_guardrails(["MAX_DEPTH"], _click(),
                                    {"depth": 3, "max_depth": 3}).allowed
    assert evaluate_task_guardrails(["MAX_DEPTH"], _click()).allowed


def test_no_external_auth_blocks_login_and_password_fields():
    res = evaluate_task_guardrails(["NO_EXTERNAL_AUTH"],
                                   _click(name="Log in to continue"))
    assert not res.allowed and res.violated == "NO_EXTERNAL_AUTH"
    pw = {"action_type": "type", "target_name": "", "target_role": "password"}
    assert not evaluate_task_guardrails(["NO_EXTERNAL_AUTH"], pw).allowed
    assert evaluate_task_guardrails(["NO_EXTERNAL_AUTH"], _click()).allowed


def test_unknown_guardrail_fails_closed():
    res = evaluate_task_guardrails(["NO_LAUNCH_MISSILES"], _click())
    assert not res.allowed and res.violated == "NO_LAUNCH_MISSILES"


def test_guardrails_run_before_allowlist():
    """AC20.1: a purchase click on an allowed button role is blocked by the
    guardrail layer even though the element-role layer would allow it."""
    allowlist = ActionAllowlist()
    buy_button = UIAction(action_type=ActionType.CLICK, target_role="button",
                          target_name="Buy now")
    assert allowlist.validate_action(buy_button)["allowed"]  # role layer allows
    gated = validate_with_guardrails(allowlist, ["NO_PURCHASE"], buy_button)
    assert not gated["allowed"]
    assert gated["rule_matched"] == "task_guardrail:NO_PURCHASE"  # AC20.3 hook
    # And a clean action still flows through to the allowlist verdict.
    clean = UIAction(action_type=ActionType.CLICK, target_role="button",
                     target_name="Read more")
    assert validate_with_guardrails(allowlist, ["NO_PURCHASE"], clean)["allowed"]


def test_guardrail_names_match_goal_anatomy_defaults():
    """The GoalAnatomy guardrail floor must name real guardrails."""
    from backend.core_models import GoalAnatomy
    names = {g.value for g in TaskGuardrail}
    for default in GoalAnatomy(objective="x").guardrails:
        assert default in names, default
