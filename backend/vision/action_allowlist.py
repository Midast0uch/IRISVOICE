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