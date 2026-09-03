import asyncio
import json
import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import aiofiles

logger = logging.getLogger(__name__)

@dataclass
class PermissionRequest:
    """Represents a permission request from automation."""
    request_id: str
    session_id: str
    user_id: str
    permission_type: str
    requested_actions: List[str]
    justification: str
    timestamp: datetime
    expires_at: datetime
    status: str = "pending"  # pending, approved, denied, expired

@dataclass
class PermissionResponse:
    """Response to a permission request."""
    request_id: str
    approved: bool
    approved_actions: List[str]
    denied_actions: List[str]
    reason: str
    response_timestamp: datetime
    expires_at: Optional[datetime] = None

class PermissionRequestSystem:
    """Manages permission requests for UI automation actions."""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path("config/permissions.json")
        self.pending_requests: Dict[str, PermissionRequest] = {}
        self.approved_permissions: Dict[str, Dict[str, Any]] = {}
        self.permission_templates: Dict[str, Dict[str, Any]] = {}
        self.load_permission_templates()
        
    def load_permission_templates(self):
        """Load permission request templates."""
        self.permission_templates = {
            "basic_automation": {
                "name": "Basic UI Automation",
                "description": "Basic click, hover, and focus actions",
                "allowed_actions": ["click", "hover", "focus"],
                "auto_approve": True,
                "expires_minutes": 60
            },
            "text_input": {
                "name": "Text Input Automation",
                "description": "Typing and text selection",
                "allowed_actions": ["type", "select", "clear"],
                "auto_approve": False,
                "requires_justification": True,
                "expires_minutes": 30
            },
            "form_filling": {
                "name": "Form Filling",
                "description": "Complete form automation including text input and selection",
                "allowed_actions": ["click", "type", "select", "focus"],
                "auto_approve": False,
                "requires_justification": True,
                "expires_minutes": 45
            },
            "navigation": {
                "name": "Navigation",
                "description": "Scrolling and navigation actions",
                "allowed_actions": ["scroll", "navigate"],
                "auto_approve": True,
                "expires_minutes": 120
            },
            "advanced_interaction": {
                "name": "Advanced Interactions",
                "description": "Right-click, double-click, drag and drop",
                "allowed_actions": ["right_click", "double_click", "drag", "drop"],
                "auto_approve": False,
                "requires_justification": True,
                "expires_minutes": 15,
                "requires_explicit_approval": True
            },
            "system_ui": {
                "name": "System UI Access",
                "description": "Access to system UI elements like dialogs and alerts",
                "allowed_actions": ["click", "type", "select"],
                "auto_approve": False,
                "requires_justification": True,
                "expires_minutes": 10,
                "requires_explicit_approval": True,
                "high_risk": True
            }
        }
    
    async def create_permission_request(self, session_id: str, user_id: str,
                                      permission_type: str, requested_actions: List[str],
                                      justification: str = "") -> PermissionRequest:
        """Create a new permission request."""
        
        # Validate permission type
        if permission_type not in self.permission_templates:
            raise ValueError(f"Unknown permission type: {permission_type}")
        
        template = self.permission_templates[permission_type]
        
        # Validate requested actions against template
        allowed_actions = set(template["allowed_actions"])
        invalid_actions = set(requested_actions) - allowed_actions
        if invalid_actions:
            raise ValueError(f"Invalid actions for permission type: {invalid_actions}")
        
        # Check if justification is required
        if template.get("requires_justification", False) and not justification.strip():
            raise ValueError("Justification is required for this permission type")
        
        # Create request
        request_id = f"perm_{session_id}_{int(datetime.now().timestamp())}"
        expires_at = datetime.now() + timedelta(minutes=template["expires_minutes"])
        
        request = PermissionRequest(
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            permission_type=permission_type,
            requested_actions=requested_actions,
            justification=justification,
            timestamp=datetime.now(),
            expires_at=expires_at
        )
        
        # Auto-approve if configured
        if template.get("auto_approve", False):
            self.pending_requests[request_id] = request  # Add to pending first
            await self.approve_permission_request(request_id, approved_actions=requested_actions)
        else:
            self.pending_requests[request_id] = request
        
        logger.info(f"Created permission request: {request_id} for {permission_type}")
        return request
    
    async def approve_permission_request(self, request_id: str, 
                                        approved_actions: List[str] = None,
                                        denied_actions: List[str] = None,
                                        reason: str = "Approved by system") -> PermissionResponse:
        """Approve a permission request."""
        
        if request_id not in self.pending_requests:
            raise ValueError(f"Request not found: {request_id}")
        
        request = self.pending_requests[request_id]
        
        # Check if request has expired
        if datetime.now() > request.expires_at:
            request.status = "expired"
            return PermissionResponse(
                request_id=request_id,
                approved=False,
                approved_actions=[],
                denied_actions=request.requested_actions,
                reason="Request expired",
                response_timestamp=datetime.now()
            )
        
        # Determine approved/denied actions
        if approved_actions is None:
            approved_actions = request.requested_actions
        if denied_actions is None:
            denied_actions = []
        
        # Store approved permissions
        permission_key = f"{request.session_id}:{request.permission_type}"
        expires_at = datetime.now() + timedelta(minutes=30)  # 30 minute default
        
        self.approved_permissions[permission_key] = {
            "session_id": request.session_id,
            "user_id": request.user_id,
            "permission_type": request.permission_type,
            "approved_actions": approved_actions,
            "denied_actions": denied_actions,
            "expires_at": expires_at,
            "request_id": request_id,
            "approval_timestamp": datetime.now()
        }
        
        # Update request status
        request.status = "approved"
        del self.pending_requests[request_id]
        
        response = PermissionResponse(
            request_id=request_id,
            approved=True,
            approved_actions=approved_actions,
            denied_actions=denied_actions,
            reason=reason,
            response_timestamp=datetime.now(),
            expires_at=expires_at
        )
        
        logger.info(f"Approved permission request: {request_id}")
        return response
    
    async def deny_permission_request(self, request_id: str, reason: str = "Denied by system") -> PermissionResponse:
        """Deny a permission request."""
        
        if request_id not in self.pending_requests:
            raise ValueError(f"Request not found: {request_id}")
        
        request = self.pending_requests[request_id]
        request.status = "denied"
        
        response = PermissionResponse(
            request_id=request_id,
            approved=False,
            approved_actions=[],
            denied_actions=request.requested_actions,
            reason=reason,
            response_timestamp=datetime.now()
        )
        
        del self.pending_requests[request_id]
        
        logger.info(f"Denied permission request: {request_id}")
        return response
    
    async def check_permission(self, session_id: str, permission_type: str, 
                           action: str) -> Dict[str, Any]:
        """Check if a specific action is permitted for a session."""
        
        permission_key = f"{session_id}:{permission_type}"
        
        if permission_key not in self.approved_permissions:
            return {
                "allowed": False,
                "reason": "No active permission for this type",
                "requires_request": True
            }
        
        permission = self.approved_permissions[permission_key]
        
        # Check if permission has expired
        if datetime.now() > permission["expires_at"]:
            del self.approved_permissions[permission_key]
            return {
                "allowed": False,
                "reason": "Permission expired",
                "requires_request": True
            }
        
        # Check if action is in approved list
        if action in permission["approved_actions"]:
            return {
                "allowed": True,
                "reason": "Action approved",
                "permission_type": permission_type,
                "expires_at": permission["expires_at"]
            }
        
        # Check if action is explicitly denied
        if action in permission["denied_actions"]:
            return {
                "allowed": False,
                "reason": "Action explicitly denied",
                "permission_type": permission_type
            }
        
        # Action not in approved list
        return {
            "allowed": False,
            "reason": "Action not in approved list",
            "permission_type": permission_type,
            "requires_request": True
        }
    
    async def get_pending_requests(self, session_id: Optional[str] = None) -> List[PermissionRequest]:
        """Get pending permission requests."""
        if session_id:
            return [req for req in self.pending_requests.values() if req.session_id == session_id]
        return list(self.pending_requests.values())
    
    async def get_active_permissions(self, session_id: str) -> List[Dict[str, Any]]:
        """Get active permissions for a session."""
        active = []
        now = datetime.now()
        
        for key, permission in list(self.approved_permissions.items()):
            if key.startswith(f"{session_id}:"):
                # Check if expired
                if now > permission["expires_at"]:
                    del self.approved_permissions[key]
                    continue
                
                active.append(permission)
        
        return active
    
    async def revoke_permission(self, session_id: str, permission_type: str) -> bool:
        """Revoke a specific permission."""
        permission_key = f"{session_id}:{permission_type}"
        
        if permission_key in self.approved_permissions:
            del self.approved_permissions[permission_key]
            logger.info(f"Revoked permission: {permission_key}")
            return True
        
        return False
    
    async def revoke_all_permissions(self, session_id: str) -> int:
        """Revoke all permissions for a session."""
        revoked_count = 0
        
        # Remove from approved permissions
        keys_to_remove = [key for key in self.approved_permissions.keys() 
                         if key.startswith(f"{session_id}:")]
        
        for key in keys_to_remove:
            del self.approved_permissions[key]
            revoked_count += 1
        
        # Cancel pending requests
        pending_to_remove = [req_id for req_id, req in self.pending_requests.items() 
                           if req.session_id == session_id]
        
        for req_id in pending_to_remove:
            del self.pending_requests[req_id]
            revoked_count += 1
        
        logger.info(f"Revoked {revoked_count} permissions for session: {session_id}")
        return revoked_count
    
    async def export_permission_log(self, output_path: Path, session_id: Optional[str] = None):
        """Export permission history to a file."""
        
        # Get active permissions
        if session_id:
            active_permissions = await self.get_active_permissions(session_id)
        else:
            active_permissions = list(self.approved_permissions.values())
        
        # Get pending requests
        if session_id:
            pending_requests = await self.get_pending_requests(session_id)
        else:
            pending_requests = list(self.pending_requests.values())
        
        export_data = {
            "export_timestamp": datetime.now().isoformat(),
            "session_id": session_id or "all_sessions",
            "active_permissions_count": len(active_permissions),
            "pending_requests_count": len(pending_requests),
            "permission_templates": self.permission_templates,
            "active_permissions": active_permissions,
            "pending_requests": [
                {
                    "request_id": req.request_id,
                    "session_id": req.session_id,
                    "user_id": req.user_id,
                    "permission_type": req.permission_type,
                    "requested_actions": req.requested_actions,
                    "justification": req.justification,
                    "timestamp": req.timestamp.isoformat(),
                    "expires_at": req.expires_at.isoformat(),
                    "status": req.status
                }
                for req in pending_requests
            ]
        }
        
        async with aiofiles.open(output_path, 'w') as f:
            await f.write(json.dumps(export_data, indent=2))
        
        logger.info(f"Exported permission log to: {output_path}")

# Import needed for timedelta
from datetime import timedelta