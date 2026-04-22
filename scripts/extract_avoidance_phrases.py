#!/usr/bin/env python3
"""Extract avoidance phrases from hook.py and write to yaml config.

This script reads the hardcoded phrases from hook.py source and outputs
them to a yaml file, enabling the migration to config-driven enforcement.
"""
import re
import pathlib

HOOK_PATH = pathlib.Path(__file__).parent.parent / "ystar" / "adapters" / "hook.py"
OUTPUT_LABS = pathlib.Path("/Users/haotianliu/.openclaw/workspace/ystar-company/knowledge/shared/avoidance_phrases.yaml")

def extract():
    src = HOOK_PATH.read_text(encoding="utf-8")
    # Find the first AVOIDANCE_PHRASES list
    pattern = r'AVOIDANCE_PHRASES\s*=\s*\[(.*?)\]'
    match = re.search(pattern, src, re.DOTALL)
    if not match:
        raise RuntimeError("Cannot find AVOIDANCE_PHRASES in hook.py")

    block = match.group(1)
    # Extract all quoted strings
    phrases = re.findall(r'"([^"]+)"', block)

    # Write yaml
    OUTPUT_LABS.parent.mkdir(parents=True, exist_ok=True)
    lines = ["phrases:"]
    for p in phrases:
        lines.append(f'  - "{p}"')
    lines.append('status_note: "Wave 5 capstone: migrate to intent-anchor positive whitelist"')
    lines.append("")
    OUTPUT_LABS.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(phrases)} phrases to {OUTPUT_LABS}")

if __name__ == "__main__":
    extract()
