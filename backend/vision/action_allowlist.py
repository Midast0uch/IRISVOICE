"""
UI action allowlist validation for secure automation.
"""
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path

class ActionType(Enum):
    """Types of UI actions that can be performed."""
    CLICK = "click"
    TYPE = "type"
    HOVER = "hover"
    SCROLL = "scroll"
    DRAG = "drag"
    KEY_PRESS = "key_press"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    FOCUS = "focus"
    SELECT = "select"

@dataclass
class UIAction:
    """Represents a UI action that can be validated."""
    action_type: ActionType
    target_role: str
    target_name: str = ""
    target_properties: Dict[str, Any] = None
    allowed_properties: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.allowed_properties is None:
            self.allowed_properties = {}

@dataclass
class ActionRule:
    """Rule for validating UI actions."""
    name: str
    description: str
    action_types: Set[ActionType]
    allowed_roles: Set[str]
    denied_roles: Set[str] = None
    required_properties: Dict[str, Any] = None
    denied_properties: Dict[str, Any] = None
    priority: int = 0
    
    def __post_init__(self):
        if self.denied_roles is None:
            self.denied_roles = set()
        if self.required_properties is None:
            self.required_properties = {}
        if self.denied_properties is None:
            self.denied_properties = {}

class ActionAllowlist:
    """Manages allowlist of permitted UI actions."""
    
    def __init__(self, config_path: Path = None):
        self.config_path = config_path or Path("config/ui_actions.json")
        self.rules: List[ActionRule] = []
        self._load_default_rules()
        self._load_config()
    
    def _load_default_rules(self):
        """Load default action rules."""
        # Safe actions that are generally allowed
        safe_rule = ActionRule(
            name="safe_interactions",
            description="Safe UI interactions",
            action_types={ActionType.CLICK, ActionType.HOVER, ActionType.FOCUS},
            allowed_roles={
                "button", "link", "menuitem", "tab", "menuitemcheckbox",
                "menuitemradio", "treeitem", "listitem"
            },
            denied_roles={
                "alert", "dialog", "tooltip", "window"  # Don't interact with system UI
            },
            priority=100
        )
        self.rules.append(safe_rule)
        
        # Text input actions
        text_rule = ActionRule(
            name="text_input",
            description="Text input interactions",
            action_types={ActionType.TYPE, ActionType.SELECT},
            allowed_roles={
                "textbox", "combobox", "searchbox", "textarea", "spinbutton"
            },
            required_properties={"readonly": False},  # Only editable fields
            priority=90
        )
        self.rules.append(text_rule)
        
        # Navigation actions
        nav_rule = ActionRule(
            name="navigation",
            description="Navigation and scrolling",
            action_types={ActionType.SCROLL},
            allowed_roles={
                "document", "application", "main", "article", "section",
                "scrollbar", "slider"
            },
            priority=80
        )
        self.rules.append(nav_rule)
        
        # Dangerous actions that should be blocked by default
        dangerous_rule = ActionRule(
            name="dangerous_actions",
            description="Potentially dangerous actions",
            action_types={
                ActionType.RIGHT_CLICK, ActionType.DRAG, ActionType.DOUBLE_CLICK
            },
            allowed_roles=set(),
            denied_roles={"button", "link", "text_input", "checkbox", "radio_button", "menu_item"},
            priority=900
        )
        self.rules.append(dangerous_rule)
        
        # System UI protection
        system_rule = ActionRule(
            name="system_ui_protection",
            description="Protect system UI elements",
            action_types=set(ActionType),  # All action types
            allowed_roles=set(), # Allow all roles by default, but deny specific ones
            denied_roles={
                "alert", "dialog", "tooltip", "window", "frame", "iframe",
                "browser", "desktop", "notification"
            },
            priority=1000  # Highest priority
        )
        self.rules.append(system_rule)
    
    def _load_config(self):
        """Load configuration from file if it exists."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    self._parse_config(config)
            except Exception as e:
                print(f"Warning: Could not load UI action config: {e}")
    
    def _parse_config(self, config: Dict[str, Any]):
        """Parse configuration dictionary."""
        for rule_config in config.get("rules", []):
            rule = ActionRule(
                name=rule_config["name"],
                description=rule_config["description"],
                action_types={ActionType(t) for t in rule_config.get("action_types", [])},
                allowed_roles=set(rule_config.get("allowed_roles", [])),
                denied_roles=set(rule_config.get("denied_roles", [])),
                required_properties=rule_config.get("required_properties", {}),
                denied_properties=rule_config.get("denied_properties", {}),
                priority=rule_config.get("priority", 0)
            )
            self.rules.append(rule)
        
        # Sort by priority (higher priority first)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
    
    def validate_action(self, action: UIAction) -> Dict[str, Any]:
        """Validate a UI action against the allowlist."""
        validation_result = {
            "allowed": False,
            "rule_matched": None,
            "reason": "No matching rule found",
            "warnings": []
        }
        
        # Sort rules by priority (highest first)
        sorted_rules = sorted(self.rules, key=lambda r: r.priority, reverse=True)

        for rule in sorted_rules:
            # Check if action type matches
            if action.action_type not in rule.action_types:
                continue

            # Check denied roles
            if rule.denied_roles and action.target_role in rule.denied_roles:
                return {"allowed": False, "rule_matched": rule.name, "reason": "Denied role"}

            # Check allowed roles
            if rule.allowed_roles and action.target_role in rule.allowed_roles:
                return {"allowed": True, "rule_matched": rule.name, "reason": "Allowed by rule"}

            # Check required properties
            if rule.required_properties:
                if not action.target_properties or not all(item in action.target_properties.items() for item in rule.required_properties.items()):
                    continue
            
            # Check denied properties
            if rule.denied_properties:
                if action.target_properties and any(item in action.target_properties.items() for item in rule.denied_properties.items()):
                    return {"allowed": False, "rule_matched": rule.name, "reason": "Denied property"}

        # Default deny if no rule matches
        return {"allowed": False, "rule_matched": "default_deny", "reason": "No matching allow rule"}
    
    def _check_rule(self, action: UIAction, rule: ActionRule) -> Dict[str, Any]:
        """Check if an action matches a rule."""
        result = {
            "matches": False,
            "allowed": False,
            "reason": "",
            "warnings": []
        }
        
        # Check action type
        if rule.action_types and action.action_type not in rule.action_types:
            return result  # Rule doesn't match
        
        # Check denied roles first (highest priority check)
        if rule.denied_roles and action.target_role in rule.denied_roles:
            result["matches"] = True
            result["allowed"] = False
            result["reason"] = f"Role '{action.target_role}' is denied by rule '{rule.name}'"
            return result
        
        # Check allowed roles
        if rule.allowed_roles and action.target_role not in rule.allowed_roles:
            # Special case: if allowed_roles is empty, it means "deny all" for this rule
            if not rule.allowed_roles:
                result["matches"] = True
                result["allowed"] = False
                result["reason"] = f"No roles are allowed by rule '{rule.name}'"
                return result
            return result  # Rule doesn't match
        
        # Check required properties
        for prop_name, required_value in rule.required_properties.items():
            if prop_name not in action.allowed_properties:
                return result  # Rule doesn't match
            if action.allowed_properties[prop_name] != required_value:
                return result  # Rule doesn't match
        
        # Check denied properties
        for prop_name, denied_value in rule.denied_properties.items():
            if prop_name in action.allowed_properties:
                if action.allowed_properties[prop_name] == denied_value:
                    result["matches"] = True
                    result["allowed"] = False
                    result["reason"] = f"Property '{prop_name}' with value '{denied_value}' is denied"
                    return result
        
        # If we get here, the rule matches and allows the action
        result["matches"] = True
        result["allowed"] = True
        result["reason"] = f"Action allowed by rule '{rule.name}'"
        
        # Add warnings for potentially risky actions
        if action.action_type in {ActionType.RIGHT_CLICK, ActionType.DRAG}:
            result["warnings"].append(f"Action type '{action.action_type.value}' may have unintended consequences")
        
        return result
    
    def add_rule(self, rule: ActionRule):
        """Add a new rule to the allowlist."""
        self.rules.append(rule)
        # Re-sort by priority
        self.rules.sort(key=lambda r: r.priority, reverse=True)
    
    def remove_rule(self, rule_name: str) -> bool:
        """Remove a rule by name."""
        initial_count = len(self.rules)
        self.rules = [rule for rule in self.rules if rule.name != rule_name]
        return len(self.rules) < initial_count
    
    def list_rules(self) -> List[Dict[str, Any]]:
        """List all rules in the allowlist."""
        return [
            {
                "name": rule.name,
                "description": rule.description,
                "priority": rule.priority,
                "action_types": [t.value for t in rule.action_types],
                "allowed_roles": list(rule.allowed_roles),
                "denied_roles": list(rule.denied_roles)
            }
            for rule in self.rules
        ]
    
    def save_config(self, path: Path = None):
        """Save current configuration to file."""
        save_path = path or self.config_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        config = {
            "rules": [
                {
                    "name": rule.name,
                    "description": rule.description,
                    "action_types": [t.value for t in rule.action_types],
                    "allowed_roles": list(rule.allowed_roles),
                    "denied_roles": list(rule.denied_roles),
                    "required_properties": rule.required_properties,
                    "denied_properties": rule.denied_properties,
                    "priority": rule.priority
                }
                for rule in self.rules
            ]
        }
        
        with open(save_path, 'w') as f:
            json.dump(config, f, indent=2)

# Predefined action templates for common scenarios
ACTION_TEMPLATES = {
    "safe_navigation": UIAction(
        action_type=ActionType.CLICK,
        target_role="link",
        target_name="Navigation Link"
    ),
    "form_input": UIAction(
        action_type=ActionType.TYPE,
        target_role="textbox",
        target_name="Form Input Field",
        allowed_properties={"readonly": False}
    ),
    "button_click": UIAction(
        action_type=ActionType.CLICK,
        target_role="button",
        target_name="Action Button"
    ),
    "menu_selection": UIAction(
        action_type=ActionType.CLICK,
        target_role="menuitem",
        target_name="Menu Item"
    )
}


# ---------------------------------------------------------------------------
# Task-level semantic guardrails (vision-goal-directed-search REQ-20, T4).
# Evaluated BEFORE ActionAllowlist.validate_action (AC20.1): semantic
# task constraints (don't buy things, stay on domain) outrank element-role
# checks. Duck-typed inputs (Mappings or UIAction) — this module stays free
# of backend imports; GoalAnatomy.guardrails plugs in as plain strings.
# ---------------------------------------------------------------------------

class TaskGuardrail(str, Enum):
    """Declarative semantic guardrails (REQ-20 AC20.2)."""
    NO_PURCHASE      = "NO_PURCHASE"
    DOMAIN_BOUND     = "DOMAIN_BOUND"
    MAX_DEPTH        = "MAX_DEPTH"
    NO_EXTERNAL_AUTH = "NO_EXTERNAL_AUTH"


@dataclass
class GuardrailResult:
    """Outcome of semantic guardrail evaluation (AC20.3)."""
    allowed: bool
    violated: Optional[str] = None
    reason: str = ""


# Substring signals, matched case-insensitively against target name / role / URL.
_PURCHASE_SIGNALS = (
    "buy", "purchase", "checkout", "check out", "pay now", "place order",
    "add to cart", "add to bag", "add to basket", "subscribe", "billing",
)
_AUTH_SIGNALS = (
    "login", "log in", "log-in", "sign in", "signin", "password",
    "auth", "2fa", "two-factor", "otp", "one-time pass",
)


def _action_field(action: Any, name: str, default: Any = "") -> Any:
    """Read a field from a Mapping or an object (UIAction); Enum -> value."""
    if isinstance(action, dict):
        value = action.get(name, default)
    else:
        value = getattr(action, name, default)
    if isinstance(value, Enum):
        return value.value
    return value if value is not None else default


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def _mentions(haystack: str, signals: tuple) -> Optional[str]:
    lowered = (haystack or "").lower()
    for signal in signals:
        if signal in lowered:
            return signal
    return None


def evaluate_task_guardrails(
    guardrails: Any,
    action: Any,
    context: Optional[Dict[str, Any]] = None,
) -> GuardrailResult:
    """Evaluate semantic task guardrails for a proposed action (REQ-20 AC20.1/20.2).

    `guardrails` is an iterable of guardrail NAME strings (e.g.
    GoalAnatomy.guardrails). `action` is a UIAction or a mapping with
    action_type / target_name / target_role / url. `context` carries
    url, allowed_domains, depth, max_depth.

    Unconfigured dimensions pass (nothing to enforce); UNKNOWN guardrail
    names fail CLOSED — silently passing a security control is worse than
    blocking on a typo, and the reason names the offender (AC20.3).
    """
    ctx = context or {}
    names = list(guardrails or [])
    target_name = str(_action_field(action, "target_name"))
    target_role = str(_action_field(action, "target_role"))
    action_type = str(_action_field(action, "action_type"))
    # The action's own URL (the click target) governs when present;
    # the context page URL is the fallback.
    url = str(_action_field(action, "url") or ctx.get("url") or "")

    for raw in names:
        try:
            guard = TaskGuardrail(str(raw))
        except ValueError:
            return GuardrailResult(
                allowed=False, violated=str(raw),
                reason=f"unknown task guardrail {raw!r}; failing closed",
            )
        if guard is TaskGuardrail.NO_PURCHASE:
            hit = (_mentions(target_name, _PURCHASE_SIGNALS)
                   or _mentions(url, _PURCHASE_SIGNALS))
            if hit:
                return GuardrailResult(
                    allowed=False, violated=guard.value,
                    reason=f"purchase signal {hit!r} in target/URL; NO_PURCHASE blocks it",
                )
        elif guard is TaskGuardrail.DOMAIN_BOUND:
            allowed_domains = [d.lower() for d in (ctx.get("allowed_domains") or [])]
            host = _host_of(url)
            if allowed_domains and host and not any(
                host == d or host.endswith("." + d) for d in allowed_domains
            ):
                return GuardrailResult(
                    allowed=False, violated=guard.value,
                    reason=f"host {host!r} outside DOMAIN_BOUND {allowed_domains}",
                )
        elif guard is TaskGuardrail.MAX_DEPTH:
            max_depth = ctx.get("max_depth")
            depth = ctx.get("depth")
            if max_depth is not None and depth is not None and depth > max_depth:
                return GuardrailResult(
                    allowed=False, violated=guard.value,
                    reason=f"depth {depth} exceeds MAX_DEPTH {max_depth}",
                )
        elif guard is TaskGuardrail.NO_EXTERNAL_AUTH:
            hit = (_mentions(target_name, _AUTH_SIGNALS)
                   or _mentions(target_role, _AUTH_SIGNALS)
                   or _mentions(url, _AUTH_SIGNALS))
            if hit is None and action_type == "type" and target_role.lower() == "password":
                hit = "password field"
            if hit:
                return GuardrailResult(
                    allowed=False, violated=guard.value,
                    reason=f"auth signal {hit!r}; NO_EXTERNAL_AUTH blocks it",
                )
    return GuardrailResult(allowed=True, reason="task guardrails satisfied")


def validate_with_guardrails(
    allowlist: "ActionAllowlist",
    guardrails: Any,
    action: UIAction,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Guardrails FIRST, element-role allowlist second (REQ-20 AC20.1).

    Returns the allowlist-style result dict so callers keep one shape:
    a guardrail block surfaces as rule_matched="task_guardrail:<NAME>"
    (the trajectory hook records `rejected_guardrail`, AC20.3).
    """
    gate = evaluate_task_guardrails(guardrails, action, context)
    if not gate.allowed:
        return {
            "allowed": False,
            "rule_matched": f"task_guardrail:{gate.violated}",
            "reason": gate.reason,
            "warnings": [],
        }
    return allowlist.validate_action(action)