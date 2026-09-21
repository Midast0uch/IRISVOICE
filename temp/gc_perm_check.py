"""Probe: does the permission layer match the spec's consent contract?

Spec (design.md KD-12 / consent decision, requirements REQ-9 AC9.4):
  Toggle ON : reads, writes, shell, GUI -> auto-approve.
  Toggle OFF: writes and shell ASK; reads stay auto.
  DESTRUCTIVE + deletion/removal -> always ask, toggle or not.

Also checks REQ-19 AC2: a SESSION_APPROVABLE tool approved once must not
prompt again in the SAME session.
"""
import sys
sys.path.insert(0, r"C:\dev\IRISVOICE")
from backend.agent import permissions as P

print("=== 1. action by tier x toggle ===")
for tier, name in [
    (P.PermissionTier.READ_ONLY, "read_file"),
    (P.PermissionTier.SIDE_EFFECT, "write_file"),
    (P.PermissionTier.SIDE_EFFECT, "run_command"),
    (P.PermissionTier.DESTRUCTIVE, "delete_file"),
]:
    off = P.get_permission_action(tier, auto_approve=False).value
    on = P.get_permission_action(tier, auto_approve=True).value
    print(f"  {name:14} OFF={off:18} ON={on}")

print()
print("=== 2. approval_class vs tier (the bypass table) ===")
for t in ["read_file", "write_file", "create_directory", "run_command", "delete_file"]:
    print(f"  {t:18} tier={P.classify_tool(t).value:12} class={P.approval_class(t).value}")

print()
print("=== 3. does the SAME tool ask again in the SAME session? ===")
ps = P.get_permission_system()
for tool in ["write_file", "create_directory", "run_command"]:
    tier = P.classify_tool(tool)
    sid = "sess-" + tool
    r1 = ps.request_permission(tool_name=tool, tier=tier, params={"x": 1},
                               session_id=sid, auto_approve=False)
    first = r1.status
    if first == "pending":
        ps.respond_to_permission(r1.request_id, approved=True)
    r2 = ps.request_permission(tool_name=tool, tier=tier, params={"x": 2},
                               session_id=sid, auto_approve=False)
    print(f"  {tool:18} 1st={first:8} 2nd={r2.status:8} "
          f"session_approved={getattr(r2, 'session_approved', None)}")

print()
print("=== 4. membership ===")
print("  run_command in _REPO_TOOLS          :", "run_command" in P.CapabilitySet._REPO_TOOLS)
print("  run_command in _SESSION_APPROVABLE  :", "run_command" in P._SESSION_APPROVABLE_TOOLS)
print("  run_command in _ALWAYS_ASK          :", "run_command" in P._ALWAYS_ASK_TOOLS)
print("  write_file in _REPO_TOOLS           :", "write_file" in P.CapabilitySet._REPO_TOOLS)
print("  write_file in _SESSION_APPROVABLE   :", "write_file" in P._SESSION_APPROVABLE_TOOLS)
