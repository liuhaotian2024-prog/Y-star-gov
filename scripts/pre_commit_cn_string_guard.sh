#!/bin/bash
# CZL-YSTAR-HARDCODED-AVOIDANCE-PHRASES: pre-commit guard
# Detects >=5 consecutive Chinese string literals in staged files
# Prevents re-hardcoding Labs-internal keyword lists into product code
#
# Installation: append to .git/hooks/pre-commit or source from it:
#   source scripts/pre_commit_cn_string_guard.sh "$STAGED"

STAGED="${1:-$(git diff --cached --name-only --diff-filter=ACM)}"
[ -z "$STAGED" ] && exit 0

for f in $(echo "$STAGED" | grep -E '\.(py|yaml|yml|json)$'); do
  if [ -f "$f" ]; then
    python3 -c "
import re, sys
with open(sys.argv[1], encoding='utf-8') as fh:
    lines = fh.readlines()
consecutive = 0
max_consecutive = 0
cn_str_pat = re.compile(r'[\"\\x27].*[\u4e00-\u9fff].*[\"\\x27]')
for line in lines:
    if cn_str_pat.search(line):
        consecutive += 1
        max_consecutive = max(max_consecutive, consecutive)
    else:
        consecutive = 0
if max_consecutive >= 5:
    print(f'BLOCKED: {max_consecutive} consecutive Chinese string literals in {sys.argv[1]} (possible hardcoded phrase list)')
    sys.exit(1)
" "$f"
    if [ $? -ne 0 ]; then
      echo "BLOCKED: >=5 consecutive Chinese string literals detected in $f — use config yaml instead of hardcoding"
      exit 1
    fi
  fi
done
