"""
CZL-SPAWN-PPID-MARKER-FIX patch applier (2026-04-24)

Applies the ppid marker write-side fix to hook_wrapper.py.
Run: python3 /path/to/hook_wrapper_ppid_fix.py
"""
import os
import sys

TARGET = "/Users/haotianliu/.openclaw/workspace/ystar-company/scripts/hook_wrapper.py"

OLD_BLOCK = (
    '    try:\n'
    '        _marker_content = _read_session_marker()\n'
    '        if _marker_content and _marker_content != "agent":\n'
    '            payload["agent_id"] = _marker_content\n'
    '            # Clear agent_type to prevent priority 1.5 from returning "agent"\n'
    '            if payload.get("agent_type") in ("", "agent", None):\n'
    '                payload.pop("agent_type", None)\n'
    "            log(f\"[P1-a] Payload agent_id overridden to '{_marker_content}' from marker fallback chain\")\n"
    '    except FileNotFoundError:\n'
    '        pass  # No marker file — identity_detector will use its own fallbacks\n'
    '    except Exception as _marker_exc:\n'
    '        log(f"[P1-a] Failed to read marker file: {_marker_exc}")'
)

NEW_BLOCK = r"""    # -- CZL-SPAWN-PPID-MARKER-FIX (2026-04-24): Subagent identity from payload --
    # When Claude Code spawns a subagent, payload.agent_type is set to the
    # subagent definition name (e.g. "Leo-Kernel", "Samantha-Secretary").
    # PREVIOUSLY: marker override below would clobber payload.agent_id with
    # stale ppid marker content ("ceo") because the parent wrote ITS OWN ppid
    # marker, not the child's. The child's ppid marker never existed.
    # FIX: If payload.agent_type is informative (non-empty, non-"agent"),
    # map it to canonical governance ID and use that as agent_id. Also write
    # the child's own ppid marker so subsequent hook calls within this
    # subagent session resolve correctly. Skip stale marker override entirely.
    _subagent_resolved_id = None
    if _original_agent_type and _original_agent_type not in ("", "agent", None):
        try:
            from ystar.adapters.identity_detector import _map_agent_type
            _resolved = _map_agent_type(_original_agent_type)
            if _resolved and _resolved not in ("agent", "guest"):
                _subagent_resolved_id = _resolved
                payload["agent_id"] = _resolved
                # Write the child's own ppid marker so downstream reads
                # within this subagent's hook invocations are consistent.
                try:
                    _child_ppid = os.environ.get("PPID", "")
                    if not _child_ppid:
                        _child_ppid = str(os.getppid())
                    if _child_ppid and _child_ppid != "1":
                        _child_marker = os.path.join(
                            _MARKER_DIR,
                            ".ystar_active_agent.ppid_" + _child_ppid,
                        )
                        with open(_child_marker, "w", encoding="utf-8") as _pf:
                            _pf.write(_resolved)
                        log("[PPID-FIX] Wrote child ppid marker ppid_"
                            + _child_ppid + " = '" + _resolved + "'")
                except Exception as _ppid_write_exc:
                    log("[PPID-FIX] Failed to write child ppid marker: "
                        + str(_ppid_write_exc))
                log("[PPID-FIX] Subagent identity from payload.agent_type='"
                    + _original_agent_type + "' -> '" + _resolved
                    + "' (skipping marker override)")
        except Exception as _map_exc:
            log("[PPID-FIX] Failed to map agent_type: " + str(_map_exc))

    # Only fall back to marker-based resolution if subagent was not resolved
    if _subagent_resolved_id is None:
        try:
            _marker_content = _read_session_marker()
            if _marker_content and _marker_content != "agent":
                payload["agent_id"] = _marker_content
                # Clear agent_type to prevent priority 1.5 from returning "agent"
                if payload.get("agent_type") in ("", "agent", None):
                    payload.pop("agent_type", None)
                log(f"[P1-a] Payload agent_id overridden to '{_marker_content}' from marker fallback chain")
        except FileNotFoundError:
            pass  # No marker file -- identity_detector will use its own fallbacks
        except Exception as _marker_exc:
            log(f"[P1-a] Failed to read marker file: {_marker_exc}")"""


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        content = f.read()

    if OLD_BLOCK not in content:
        print("ERROR: Could not find old block in target file")
        print("Searching for anchor line...")
        for i, line in enumerate(content.split("\n")):
            if "_marker_content = _read_session_marker()" in line:
                print(f"  Found anchor at line {i+1}: {repr(line)}")
        sys.exit(1)

    content = content.replace(OLD_BLOCK, NEW_BLOCK, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(content)

    print("SUCCESS: hook_wrapper.py patched with CZL-SPAWN-PPID-MARKER-FIX")


if __name__ == "__main__":
    main()
