"""
MCP Security Allowlists and Dangerous Patterns
Defines allowed operations for each MCP tool and patterns to block
"""
import re
from typing import Dict, List, Any, Set, Optional
from dataclasses import dataclass, field


# MCP Tool Operation Allowlists
# Each tool defines which operations are allowed
MCP_ALLOWLISTS: Dict[str, Dict[str, Any]] = {
    "test_tool": {
        "description": "Test tool for security validation",
        "operations": ["execute"],
        "restrictions": {}
    },
    "gateway_message": {
        "description": "Gateway message for internal processing",
        "operations": [
            "session_create",
            "session_destroy",
            "state_update",
            "heartbeat",
            "system_command",
            "automation_request",
            "vision_request",
            "audio_request",
            "security_violation",
            "error"
        ],
        "restrictions": {}
    },
    
    "file_manager": {
        "description": "File system operations with security restrictions",
        "operations": ["read", "write", "list", "create", "delete", "move", "copy"],
        "restrictions": {
            "blocked_paths": ["/system", "/etc", "/usr", "/bin", "/sbin", "C:\\Windows", "C:\\Program Files"],
            "blocked_extensions": [".exe", ".bat", ".cmd", ".sh", ".ps1", ".dll", ".so"],
            "max_file_size": 10 * 1024 * 1024,  # 10MB
            "allowed_mime_types": ["text/*", "application/json", "application/xml"],
            "allowed_sandboxes": ["user_data", "temp", "cache", "logs", "config"],
            "sandbox_paths": {
                "user_data": "/tmp/sandbox/user_data",
                "temp": "/tmp/sandbox/temp",
                "cache": "/tmp/sandbox/cache",
                "logs": "/tmp/sandbox/logs",
                "config": "/tmp/sandbox/config"
            },
            "require_sandbox": True  # Require sandbox for all file operations
        }
    },
    
    "gui_automation": {
        "description": "GUI automation with UI element restrictions",
        "operations": ["click", "type", "scroll", "hover", "select", "focus"],
        "restrictions": {
            "blocked_selectors": ["password", "credit", "ssn", "secret", "private"],
            "blocked_applications": ["taskmgr", "regedit", "cmd", "powershell"],
            "max_actions_per_minute": 60,
            "require_confirmation": ["delete", "format", "submit"]
        }
    },
    
    "system": {
        "description": "System operations with command restrictions",
        "operations": ["ping", "echo", "execute", "exec", "info", "status", "list_processes"],
        "restrictions": {
            "blocked_commands": ["format", "del", "rm -rf", "shutdown", "reboot", "sudo", "su"],
            "allowed_commands": ["ping", "echo", "hostname", "date", "time"],
            "max_execution_time": 30,  # seconds
            "readonly_operations": True
        }
    },
    
    "web_browser": {
        "description": "Web browser automation with URL restrictions",
        "operations": ["navigate", "click", "scroll", "screenshot", "get_text"],
        "restrictions": {
            "blocked_domains": ["localhost", "127.0.0.1", "0.0.0.0", "file://"],
            "blocked_protocols": ["file://", "ftp://", "ssh://"],
            "allowed_domains": ["https://*"],
            "max_page_load_time": 10,  # seconds
            "block_downloads": True
        }
    },
    
    "database": {
        "description": "Database operations with query restrictions",
        "operations": ["select", "insert", "update", "delete"],
        "restrictions": {
            "blocked_keywords": ["DROP", "TRUNCATE", "ALTER", "CREATE", "EXECUTE"],
            "max_rows": 1000,
            "readonly_operations": False,
            "require_where_clause": True
        }
    },
    
    "network": {
        "description": "Network operations with connection restrictions",
        "operations": ["get", "post", "put", "delete", "head"],
        "restrictions": {
            "blocked_ports": [22, 23, 25, 110, 143, "*"],  # Block SSH, Telnet, Email
            "allowed_ports": [80, 443, 8080, 8000, 3000],
            "max_request_size": 1 * 1024 * 1024,  # 1MB
            "timeout": 30,  # seconds
            "block_local_network": True
        }
    },
    
    "clipboard": {
        "description": "Clipboard operations with content filtering",
        "operations": ["read", "write", "clear"],
        "restrictions": {
            "max_size": 100 * 1024,  # 100KB
            "blocked_patterns": ["password", "credit", "ssn", "secret"],
            "allowed_mime_types": ["text/plain", "text/html"],
            "log_operations": True
        }
    },
    
    "screen_capture": {
        "description": "Screen capture with privacy protection",
        "operations": ["capture", "partial_capture", "list_windows"],
        "restrictions": {
            "block_password_fields": True,
            "blur_sensitive_content": True,
            "max_captures_per_minute": 10,
            "exclude_system_windows": True
        }
    }
}


@dataclass
class DangerousPattern:
    """Represents a dangerous pattern to detect in operations"""
    name: str
    pattern: str
    description: str
    severity: str = "high"  # low, medium, high, critical
    category: str = "general"
    enabled: bool = True


class DangerousPatterns:
    """Manages dangerous patterns for security validation"""
    
    def __init__(self):
        self._patterns: Dict[str, DangerousPattern] = {}
        self._compiled_patterns: Dict[str, re.Pattern] = {}
        self._initialize_default_patterns()
    
    def _initialize_default_patterns(self):
        """Initialize default dangerous patterns"""
        default_patterns = [
            # System manipulation patterns
            DangerousPattern(
                name="system_manipulation",
                pattern=r"(rm\s+-rf|format\s+[a-zA-Z]:|del\s+/f|shutdown\s+/s|reboot|ping|netsh|powershell|cmd)",
                description="System destruction commands",
                severity="critical",
                category="system"
            ),
            
            # Code injection patterns
            DangerousPattern(
                name="code_injection",
                pattern=r"(eval\s*\(|exec\s*\(|__import__|getattr|setattr|globals|locals|import\s+os|os\.system)",
                description="Python code injection attempts",
                severity="critical",
                category="injection"
            ),
            
            # Path traversal patterns
            DangerousPattern(
                name="path_traversal",
                pattern=r"(\.\./|\.\.\\|/etc/passwd|/etc/shadow|windows/system32)",
                description="Directory traversal attempts",
                severity="critical",
                category="filesystem"
            ),
            
            # Credential patterns
            DangerousPattern(
                name="credential_exposure",
                pattern=r"(password\s*=|api_key\s*=|secret\s*=|token\s*=)",
                description="Potential credential exposure",
                severity="high",
                category="credentials"
            ),
            
            # Network attack patterns
            DangerousPattern(
                name="network_attack",
                pattern=r"(nmap|metasploit|sqlmap|nikto|burp|zap)",
                description="Security testing tools",
                severity="medium",
                category="network"
            ),
            
            # Malicious URL patterns
            DangerousPattern(
                name="malicious_url",
                pattern=r"(file://|ftp://|ssh://|sftp://|localhost:22|127\.0\.0\.1:22)",
                description="Potentially malicious URL schemes",
                severity="high",
                category="web"
            ),
            
            # Privilege escalation patterns
            DangerousPattern(
                name="privilege_escalation",
                pattern=r"(sudo\s+|su\s+-|runas|administrator|root)",
                description="Privilege escalation attempts",
                severity="critical",
                category="privilege"
            ),
            
            # Data exfiltration patterns
            DangerousPattern(
                name="data_exfiltration",
                pattern=r"(curl.*http|wget.*http|scp|rsync.*:|ftp.*@)",
                description="Potential data exfiltration",
                severity="high",
                category="data"
            ),
            
            # Registry manipulation (Windows)
            DangerousPattern(
                name="registry_manipulation",
                pattern=r"(reg\s+add|reg\s+delete|hkey_|registry)",
                description="Windows registry manipulation",
                severity="high",
                category="system"
            ),
            
            # Script execution patterns
            DangerousPattern(
                name="script_execution",
                pattern=r"(powershell.*-e|bash.*-c|sh.*-c|cmd.*\/c)",
                description="Script execution attempts",
                severity="high",
                category="scripting"
            ),
            
            # Database injection patterns
            DangerousPattern(
                name="sql_injection",
                pattern=r"(union\s+select|drop\s+table|truncate\s+table|exec\s*\(|xp_cmdshell)",
                description="SQL injection attempts",
                severity="critical",
                category="injection"
            ),
            
            # Sensitive file access
            DangerousPattern(
                name="sensitive_files",
                pattern=r"(/etc/|/proc/|/sys/|\.ssh|\.gnupg|wallet\.dat)",
                description="Access to sensitive system files",
                severity="critical",
                category="filesystem"
            ),
            
            # Cryptocurrency mining
            DangerousPattern(
                name="crypto_mining",
                pattern=r"(xmrig|cpuminer|cgminer|stratum|mining_pool)",
                description="Cryptocurrency mining tools",
                severity="medium",
                category="malware"
            ),
            
            # Reverse shell patterns
            DangerousPattern(
                name="reverse_shell",
                pattern=r"(nc\s+-|netcat|bash.*-i.*>&|powershell.*-nop.*-c)",
                description="Reverse shell attempts",
                severity="critical",
                category="backdoor"
            )
        ]
        
        for pattern in default_patterns:
            self.add_pattern(pattern.name, pattern.pattern, pattern.severity, 
                           pattern.description, pattern.category, pattern.enabled)
    
    def add_pattern(
        self, 
        name: str, 
        pattern: str, 
        severity: str = "high",
        description: str = "",
        category: str = "general",
        enabled: bool = True
    ):
        """Add a new dangerous pattern"""
        dangerous_pattern = DangerousPattern(
            name=name,
            pattern=pattern,
            description=description,
            severity=severity,
            category=category,
            enabled=enabled
        )
        
        self._patterns[name] = dangerous_pattern
        
        # Compile pattern for performance
        try:
            self._compiled_patterns[name] = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern '{pattern}': {e}")
    
    def remove_pattern(self, name: str) -> bool:
        """Remove a dangerous pattern"""
        if name in self._patterns:
            del self._patterns[name]
            if name in self._compiled_patterns:
                del self._compiled_patterns[name]
            return True
        return False
    
    def get_pattern(self, name: str) -> Optional[DangerousPattern]:
        """Get a specific pattern"""
        return self._patterns.get(name)
    
    def get_all_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Get all patterns as dictionary"""
        result = {}
        for name, pattern in self._patterns.items():
            if pattern.enabled:
                result[name] = {
                    "pattern": pattern.pattern,
                    "description": pattern.description,
                    "severity": pattern.severity,
                    "category": pattern.category
                }
        return result
    
    def get_patterns_by_category(self, category: str) -> List[DangerousPattern]:
        """Get patterns by category"""
        return [p for p in self._patterns.values() if p.category == category and p.enabled]
    
    def get_patterns_by_severity(self, severity: str) -> List[DangerousPattern]:
        """Get patterns by severity level"""
        return [p for p in self._patterns.values() if p.severity == severity and p.enabled]
    
    def check_pattern(self, text: str, pattern_name: str) -> bool:
        """Check if text matches a specific pattern"""
        pattern = self._compiled_patterns.get(pattern_name)
        if pattern:
            return bool(pattern.search(text))
        return False
    
    def check_all_patterns(self, text: str) -> List[str]:
        """Check text against all enabled patterns"""
        matches = []
        for name, pattern in self._compiled_patterns.items():
            if self._patterns[name].enabled and pattern.search(text):
                matches.append(name)
        return matches

    def check_path_traversal(self, text: str) -> bool:
        """Check for path traversal patterns"""
        return self.check_pattern(text, 'path_traversal')

    def check_command_injection(self, text: str) -> bool:
        """Check for command injection patterns"""
        # This is a bit more complex as some commands are safe.
        # We will check for shell commands and dangerous commands.
        if self.check_pattern(text, 'system_manipulation'):
            return True
        if self.check_pattern(text, 'script_execution'):
            return True
        return False

    def check_code_injection(self, text: str) -> bool:
        """Check for code injection patterns"""
        return self.check_pattern(text, 'code_injection')
    
    def enable_pattern(self, name: str) -> bool:
        """Enable a pattern"""
        if name in self._patterns:
            self._patterns[name].enabled = True
            return True
        return False
    
    def disable_pattern(self, name: str) -> bool:
        """Disable a pattern"""
        if name in self._patterns:
            self._patterns[name].enabled = False
            return True
        return False
    
    def update_pattern(self, name: str, **kwargs) -> bool:
        """Update an existing pattern"""
        if name not in self._patterns:
            return False
        
        pattern = self._patterns[name]
        
        if "pattern" in kwargs:
            pattern.pattern = kwargs["pattern"]
            # Recompile the pattern
            try:
                self._compiled_patterns[name] = re.compile(pattern.pattern, re.IGNORECASE)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern '{pattern.pattern}': {e}")
        
        if "description" in kwargs:
            pattern.description = kwargs["description"]
        
        if "severity" in kwargs:
            pattern.severity = kwargs["severity"]
        
        if "category" in kwargs:
            pattern.category = kwargs["category"]
        
        if "enabled" in kwargs:
            pattern.enabled = kwargs["enabled"]
        
        return True


# Emergency security patterns (can be enabled quickly)
EMERGENCY_PATTERNS = {
    "block_all_system_commands": DangerousPattern(
        name="block_all_system_commands",
        pattern=r"(rm|del|format|shutdown|reboot|sudo|su\s)",
        description="Block all system commands (emergency)",
        severity="critical",
        category="emergency",
        enabled=False
    ),
    
    "block_all_file_writes": DangerousPattern(
        name="block_all_file_writes",
        pattern=r"(write|create|delete|move|copy)",
        description="Block all file write operations (emergency)",
        severity="high",
        category="emergency",
        enabled=False
    ),
    
    "block_all_network": DangerousPattern(
        name="block_all_network",
        pattern=r"(http|ftp|ssh|curl|wget)",
        description="Block all network operations (emergency)",
        severity="high",
        category="emergency",
        enabled=False
    )
}


def get_allowlist(tool_name: str) -> Dict[str, Any]:
    """Get allowlist configuration for a specific tool"""
    return MCP_ALLOWLISTS.get(tool_name, {})


def get_allowed_operations(tool_name: str) -> List[str]:
    """Get allowed operations for a specific tool"""
    allowlist = get_allowlist(tool_name)
    return allowlist.get("operations", [])


def is_operation_allowed(tool_name: str, operation: str) -> bool:
    """Check if an operation is allowed for a tool"""
    allowed_ops = get_allowed_operations(tool_name)
    return operation in allowed_ops


def get_tool_restrictions(tool_name: str) -> Dict[str, Any]:
    """Get restrictions for a specific tool"""
    allowlist = get_allowlist(tool_name)
    return allowlist.get("restrictions", {})