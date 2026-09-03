"""
Port availability checker for IRIS-owned services.

Checks each port IRIS wants to bind to (backend, brain, vision) and,
if the configured port is in use, finds the next free port in a small
range.  The actual ports used are written back to the config so every
consumer — both frontend and internal — can discover them.

Logging is concise and actionable: one line per service, only logging
warnings when the default port couldn't be used.
"""

import logging
import socket
import sys
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# Maximum consecutive ports to try before giving up.
_MAX_PORT_RETRIES = 20


def is_port_free(host: str, port: int) -> bool:
    """Return True if *port* on *host* is available to bind to."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except (OSError, PermissionError):
            return False


def _find_free_port(host: str, preferred: int) -> int:
    """Try *preferred*, then preferred+1, …, up to _MAX_PORT_RETRIES.

    If none are free, fall back to OS-assigned ephemeral port 0.
    """
    for offset in range(_MAX_PORT_RETRIES):
        candidate = preferred + offset
        if is_port_free(host, candidate):
            return candidate
    # Last resort: let the OS pick one.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def resolve_ports(
    host: str,
    wanted: Dict[str, int],
) -> Dict[str, int]:
    """Check and resolve each entry in *wanted* to an available port.

    Parameters
    ----------
    host : str
        The hostname/interface to check (e.g. "127.0.0.1", "0.0.0.0").
    wanted : dict
        Service-name → preferred-port mapping, e.g.
        {"backend": 8090, "brain": 18182, "vision": 18181}.

    Returns
    -------
    dict
        Service-name → resolved-port mapping.  If a preferred port is
        taken, the next free port is used and a warning is logged.

    Example
    -------
    >>> resolve_ports("0.0.0.0", {"backend": 8090, "brain": 18182})
    {"backend": 8090, "brain": 18182}
    """
    resolved: Dict[str, int] = {}
    for name, preferred in wanted.items():
        if is_port_free(host, preferred):
            resolved[name] = preferred
            logger.debug("[Ports] %s → %s (%d) ✓", host, name, preferred)
        else:
            free = _find_free_port(host, preferred + 1)
            logger.warning(
                "[Ports] Port %d is already in use — %s falling back to %d",
                preferred,
                name,
                free,
            )
            resolved[name] = free
    return resolved


def ports_to_flag_list(ports: Dict[str, int]) -> List[Tuple[str, str]]:
    """Convert resolved ports to a list of (env-var, str(port)) tuples.

    These can be injected into subprocess launch commands.
    """
    return [(f"IRIS_{name.upper()}_PORT", str(port)) for name, port in ports.items()]


# Quick smoke-test when run directly
if __name__ == "__main__":
    wanted = {"backend": 8090, "brain": 18182, "vision": 18181}
    result = resolve_ports("127.0.0.1", wanted)
    for name, port in result.items():
        status = "✓" if port == wanted.get(name) else "→ {}".format(port)
        print(f"  {name:10s} {wanted.get(name, '?')} {status}")
