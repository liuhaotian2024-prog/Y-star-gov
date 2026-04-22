"""
Audience: Board empirical verification of D8 boundary redirect REWRITE.
Research basis: Leo shipped write_boundary_redirect transform into boundary_enforcer.py:630.
Synthesis: probe confirms deny reason now contains actionable 'Suggested redirect' hint.
Purpose: close ARCH-14 REWRITE gap empirically with live CEO-side trigger.
"""
import sys
sys.path.insert(0, "/Users/haotianliu/.openclaw/workspace/Y-star-gov")
from ystar.adapters.boundary_enforcer import BoundaryEnforcer

be = BoundaryEnforcer()
result = be.check_tool_use(
    agent_id="ceo",
    tool_name="Write",
    tool_input={"file_path": "/tmp/hacked.py", "content": "x"},
)
print("DECISION:", getattr(result, "decision", result))
reason = getattr(result, "reason", "") or ""
print("REASON:", reason[:500])
print("HAS_REDIRECT:", "Suggested redirect" in reason or "Redirect" in reason)
