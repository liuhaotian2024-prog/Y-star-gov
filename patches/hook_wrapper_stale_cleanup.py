"""
CZL-SPAWN-PPID-MARKER-FIX patch #2: Stale ppid marker cleanup.

Adds defensive pruning of ppid markers older than 1 hour.
Run: python3 /path/to/hook_wrapper_stale_cleanup.py
"""
import sys

TARGET = "/Users/haotianliu/.openclaw/workspace/ystar-company/scripts/hook_wrapper.py"

# Insert AFTER the call counter write block, BEFORE "Read stdin"
ANCHOR = '    with open(call_counter, "w") as f:\n        f.write(str(count))\n\n    # Read stdin'

INSERTION = '''    with open(call_counter, "w") as f:
        f.write(str(count))

    # -- CZL-SPAWN-PPID-MARKER-FIX (2026-04-24): Stale ppid marker cleanup --
    # Prune ppid marker files older than 1 hour to prevent unbounded accumulation.
    # Lightweight: one glob + stat per hook call, actual deletion only when stale.
    try:
        import glob as _glob_mod
        _stale_threshold = time.time() - 3600  # 1 hour
        _ppid_pattern = os.path.join(os.path.dirname(__file__), ".ystar_active_agent.ppid_*")
        for _stale_path in _glob_mod.glob(_ppid_pattern):
            try:
                if os.stat(_stale_path).st_mtime < _stale_threshold:
                    os.unlink(_stale_path)
            except (FileNotFoundError, OSError):
                pass
    except Exception:
        pass  # Non-fatal: cleanup is best-effort

    # Read stdin'''


def main():
    with open(TARGET, "r", encoding="utf-8") as f:
        content = f.read()

    if ANCHOR not in content:
        print("ERROR: Could not find anchor in target file")
        sys.exit(1)

    if "Stale ppid marker cleanup" in content:
        print("SKIP: Stale cleanup already applied")
        return

    content = content.replace(ANCHOR, INSERTION, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(content)

    print("SUCCESS: Stale ppid cleanup added to hook_wrapper.py")


if __name__ == "__main__":
    main()
