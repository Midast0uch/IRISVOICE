import asyncio
import json
import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import aiofiles

from .action_allowlist import ActionAllowlist, UIAction, ActionType

logger = logging.getLogger(__name__)

@dataclass
class ExecutionContext:
    """Context for sandboxed execution."""
    session_id: str
    user_id: str
    permissions: Set[str]
    restrictions: Dict[str, Any]
    execution_timeout: float = 30.0
    max_actions_per_minute: int = 60

@dataclass
class ExecutionResult:
    """Result of sandboxed execution."""
    success: bool
    actions_executed: List[Dict[str, Any]]
    errors: List[str]
    warnings: List[str]
    execution_time: float
    timestamp: datetime

class SandboxedExecutor:
    """Executes UI actions in a sandboxed environment with safety checks."""
    
    def __init__(self, allowlist: ActionAllowlist, audit_logger: Optional[Any] = None):
        self.allowlist = allowlist
        self.audit_logger = audit_logger
        self.execution_contexts: Dict[str, ExecutionContext] = {}
        self.action_history: List[Dict[str, Any]] = []
        self.rate_limiter: Dict[str, List[datetime]] = {}
        
    async def create_execution_context(self, session_id: str, user_id: str, 
                                     permissions: Set[str] = None,
                                     restrictions: Dict[str, Any] = None) -> ExecutionContext:
        """Create a new execution context for sandboxed operations."""
        context = ExecutionContext(
            session_id=session_id,
            user_id=user_id,
            permissions=permissions or set(),
            restrictions=restrictions or {},
            execution_timeout=restrictions.get("timeout", 30.0) if restrictions else 30.0,
            max_actions_per_minute=restrictions.get("max_actions_per_minute", 60) if restrictions else 60
        )
        self.execution_contexts[session_id] = context
        return context
    
    async def execute_action(self, action: UIAction, context: ExecutionContext,
                             screenshot_data: Optional[bytes] = None) -> Dict[str, Any]:
        """Execute a single UI action with safety checks."""
        start_time = datetime.now()
        
        try:
            # Validate action against allowlist
            validation_result = self.allowlist.validate_action(action)
            if not validation_result["allowed"]:
                return {
                    "success": False,
                    "error": f"Action not allowed: {validation_result['reason']}",
                    "rule_matched": validation_result["rule_matched"],
                    "execution_time": (datetime.now() - start_time).total_seconds()
                }
            
            # Check permissions
            permission_error = await self._check_permissions(action, context)
            if permission_error:
                return {
                    "success": False,
                    "error": permission_error,
                    "execution_time": (datetime.now() - start_time).total_seconds()
                }
            
            # Check rate limiting
            rate_limit_error = await self._check_rate_limit(context)
            if rate_limit_error:
                return {
                    "success": False,
                    "error": rate_limit_error,
                    "execution_time": (datetime.now() - start_time).total_seconds()
                }
            
            # Execute the action (simulated)
            execution_result = await self._simulate_action_execution(action, context, screenshot_data)
            
            # Log the action
            await self._log_action(action, context, execution_result, start_time)
            
            return execution_result
            
        except Exception as e:
            logger.error(f"Error executing action: {e}")
            return {
                "success": False,
                "error": f"Execution error: {str(e)}",
                "execution_time": (datetime.now() - start_time).total_seconds()
            }
    
    async def execute_actions(self, actions: List[UIAction], context: ExecutionContext,
                            screenshot_data: Optional[bytes] = None) -> ExecutionResult:
        """Execute multiple UI actions in sequence."""
        start_time = datetime.now()
        executed_actions = []
        errors = []
        warnings = []
        
        try:
            for i, action in enumerate(actions):
                # Check execution timeout
                current_time = datetime.now()
                if (current_time - start_time).total_seconds() > context.execution_timeout:
                    errors.append("Execution timeout exceeded")
                    break
                
                # Execute individual action
                result = await self.execute_action(action, context, screenshot_data)
                executed_actions.append({
                    "action": action,
                    "result": result,
                    "sequence": i + 1
                })
                
                if not result["success"]:
                    errors.append(f"Action {i+1} failed: {result.get('error', 'Unknown error')}")
                
                # Add warnings if any
                if result.get("warning"):
                    warnings.append(result["warning"])
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            return ExecutionResult(
                success=len(errors) == 0,
                actions_executed=executed_actions,
                errors=errors,
                warnings=warnings,
                execution_time=execution_time,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            return ExecutionResult(
                success=False,
                actions_executed=executed_actions,
                errors=[f"Batch execution error: {str(e)}"],
                warnings=warnings,
                execution_time=execution_time,
                timestamp=datetime.now()
            )
    
    async def _check_permissions(self, action: UIAction, context: ExecutionContext) -> Optional[str]:
        """Check if the action is permitted in the current context."""
        required_permissions = self._get_required_permissions(action)
        
        missing_permissions = required_permissions - context.permissions
        if missing_permissions:
            return f"Missing required permissions: {', '.join(missing_permissions)}"
        
        # Check context-specific restrictions
        if context.restrictions.get("block_all_actions", False):
            return "All actions are blocked in this context"
        
        # Check action-specific restrictions
        action_restrictions = context.restrictions.get("blocked_actions", [])
        if action.action_type.value in action_restrictions:
            return f"Action type '{action.action_type.value}' is blocked"
        
        return None
    
    async def _check_rate_limit(self, context: ExecutionContext) -> Optional[str]:
        """Check rate limiting for the execution context."""
        now = datetime.now()
        session_id = context.session_id
        
        # Initialize rate limiter for session if not exists
        if session_id not in self.rate_limiter:
            self.rate_limiter[session_id] = []
        
        # Clean up old entries (older than 1 minute)
        self.rate_limiter[session_id] = [
            timestamp for timestamp in self.rate_limiter[session_id]
            if (now - timestamp).total_seconds() < 60
        ]
        
        # Check if limit exceeded
        if len(self.rate_limiter[session_id]) >= context.max_actions_per_minute:
            return f"Rate limit exceeded: {context.max_actions_per_minute} actions per minute"
        
        # Add current timestamp
        self.rate_limiter[session_id].append(now)
        return None
    
    async def _simulate_action_execution(self, action: UIAction, context: ExecutionContext,
                                       screenshot_data: Optional[bytes] = None) -> Dict[str, Any]:
        """Simulate the execution of a UI action."""
        # This would be replaced with actual UI automation in a real implementation
        
        execution_time = 0.1  # Simulated execution time
        
        # Simulate potential warnings based on action type and target
        warning = None
        if action.action_type == ActionType.RIGHT_CLICK and action.target_role == "button":
            warning = "Right-click on button may trigger context menu"
        elif action.action_type == ActionType.DRAG and "input" in action.target_role.lower():
            warning = "Drag operation on input field may cause data loss"
        
        return {
            "success": True,
            "warning": warning,
            "execution_time": execution_time,
            "simulated": True,  # Flag to indicate this is a simulation
            "screenshot_analyzed": screenshot_data is not None
        }
    
    def _get_required_permissions(self, action: UIAction) -> Set[str]:
        """Get required permissions for an action."""
        permissions = set()
        
        # Base permissions for all actions
        permissions.add("ui_automation")
        
        # Action-specific permissions
        if action.action_type in {ActionType.TYPE, ActionType.SELECT}:
            permissions.add("text_input")
            permissions.add("form_input")  # For typing/selecting
        elif action.action_type == ActionType.CLICK:
            permissions.add("element_click")  # Changed from element_interaction to element_click
        elif action.action_type in {ActionType.RIGHT_CLICK, ActionType.DOUBLE_CLICK}:
            permissions.add("advanced_interaction")
            permissions.add("element_click")  # These are still clicks
        elif action.action_type in {ActionType.DRAG, ActionType.DROP}:
            permissions.add("drag_and_drop")
        
        # Role-specific permissions (additional requirements)
        if action.target_role in {"textbox", "combobox", "searchbox"}:
            permissions.add("form_input")
        elif action.target_role in {"button", "link"}:
            permissions.add("element_click")  # Ensure element_click for buttons/links
        elif "menu" in action.target_role.lower():
            permissions.add("menu_navigation")
        
        return permissions
    
    async def _log_action(self, action: UIAction, context: ExecutionContext,
                         result: Dict[str, Any], start_time: datetime):
        """Log the executed action for audit purposes."""
        action_log = {
            "session_id": context.session_id,
            "user_id": context.user_id,
            "action": {
                "type": action.action_type.value,
                "target_role": action.target_role,
                "target_name": action.target_name,
                "target_properties": action.target_properties
            },
            "result": result,
            "timestamp": start_time.isoformat(),
            "execution_time": result.get("execution_time", 0)
        }
        
        self.action_history.append(action_log)
        
        # Keep only recent history (last 1000 actions)
        if len(self.action_history) > 1000:
            self.action_history = self.action_history[-1000:]
        
        # Log to audit logger if available
        if self.audit_logger and hasattr(self.audit_logger, 'log_event'):
            await self.audit_logger.log_event(
                session_id=context.session_id,
                user_id=context.user_id,
                event_type="ui_action",
                details=action_log,
                severity="info" if result.get("success") else "warning"
            )
    
    async def get_execution_history(self, session_id: Optional[str] = None,
                                    limit: int = 100) -> List[Dict[str, Any]]:
        """Get execution history for audit and monitoring."""
        history = self.action_history
        
        if session_id:
            history = [entry for entry in history if entry.get("session_id") == session_id]
        
        return history[-limit:] if limit > 0 else history
    
    async def clear_execution_context(self, session_id: str):
        """Clear execution context and cleanup resources."""
        if session_id in self.execution_contexts:
            del self.execution_contexts[session_id]
        
        if session_id in self.rate_limiter:
            del self.rate_limiter[session_id]
        
        logger.info(f"Cleared execution context for session: {session_id}")
    
    async def export_execution_log(self, output_path: Path, session_id: Optional[str] = None):
        """Export execution history to a file for analysis."""
        history = await self.get_execution_history(session_id)
        
        export_data = {
            "export_timestamp": datetime.now().isoformat(),
            "session_id": session_id or "all_sessions",
            "total_actions": len(history),
            "actions": history
        }
        
        async with aiofiles.open(output_path, 'w') as f:
            await f.write(json.dumps(export_data, indent=2))
        
        logger.info(f"Exported execution log to: {output_path}")