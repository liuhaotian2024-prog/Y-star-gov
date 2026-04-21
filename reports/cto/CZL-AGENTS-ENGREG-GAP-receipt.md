Audience: CEO (Aiden) for dispatch board completion + Board (Haotian) for AMENDMENT-020 authorization
Research basis: AGENTS.md lines 639-931 (existing agent blocks), hook.py lines 496-499 (eng-* fallback), Ryan CZL-BOOT-INJ-FIX discovery that eng-* roles lack AGENTS.md registration
Synthesis: 4 eng-* agent blocks prepared for AGENTS.md insertion but blocked by immutable path governance hook; hook.py fallback is safe and defensive; Board ack needed to land
Purpose: Enable Board to authorize AGENTS.md modification so eng-* roles get explicit write scope instead of inheriting cto fallback

---

# CZL-AGENTS-ENGREG-GAP Receipt

## 5-Tuple

- **Y***: eng-kernel / eng-governance / eng-platform / eng-domains have explicit write scope in AGENTS.md; receipts land in `reports/receipts/` without cto fallback workaround.
- **Xt**: eng-* absent from AGENTS.md policy; hook.py line 498 falls back to `cto` scope; receipts currently go to `docs/receipts/` as workaround.
- **U**: Prepared AGENTS.md diff adding 4 eng-* agent registration blocks (AMENDMENT-020). Edit blocked by immutable path governance hook -- requires Board sign-off per Escalation Matrix line 941.
- **Yt+1**: AGENTS.md contains 14 agent rule sets (CEO + CTO + CMO + CSO + CFO + Secretary + 4 eng-*); hook.py fallback preserved as defensive layer for unknown eng-* variants.
- **Rt+1**: 1 -- edit prepared and validated but blocked by immutable path hook. Requires Board break_glass or explicit ack to land.

## Status: BLOCKED (governance immutable path)

## Prepared Diff Summary

4 new agent blocks to insert between CFO Agent (line 931) and Escalation Matrix (line 933) in AGENTS.md:

### eng-kernel Agent (Kernel Engineer)
- Write: Y-star-gov/ystar/kernel/, Y-star-gov/ystar/session.py, Y-star-gov/tests/kernel/, ./reports/kernel/, ./reports/receipts/
- Forbidden: ./finance/, ./sales/, .env
- Obligations: test gate, CIEU-first debugging, source-first fixes, no git ops

### eng-governance Agent (Governance Engineer)
- Write: Y-star-gov/ystar/governance/, Y-star-gov/ystar/path_a/, Y-star-gov/ystar/path_b/, Y-star-gov/tests/governance/, ./reports/governance/, ./reports/receipts/
- Forbidden: ./finance/, ./sales/, .env
- Obligations: test gate, CIEU-first debugging, source-first fixes, no git ops

### eng-platform Agent (Platform Engineer)
- Write: Y-star-gov/ystar/adapters/, Y-star-gov/ystar/cli/, Y-star-gov/ystar/integrations/, Y-star-gov/tests/platform/, Y-star-gov/tests/adapters/, ./reports/platform/, ./reports/receipts/, ./scripts/ (hook/daemon only)
- Forbidden: ./finance/, ./sales/, .env
- Obligations: test gate, CIEU-first debugging, source-first fixes, no git ops, cross-platform compat

### eng-domains Agent (Domains Engineer)
- Write: Y-star-gov/ystar/domains/, Y-star-gov/ystar/templates/, Y-star-gov/tests/domains/, ./reports/domains/, ./reports/receipts/
- Forbidden: ./finance/, ./sales/, .env
- Obligations: test gate, CIEU-first debugging, source-first fixes, no git ops

### Amendment Marker
AMENDMENT-020 (eng-* explicit registration, 2026-04-19, proposed by CTO, awaiting Board ack). Uses 020 because AMENDMENT-019 already exists in AGENTS.md.

## hook.py Fallback Verification

Line 496-499 in `/Users/haotianliu/.openclaw/workspace/Y-star-gov/ystar/adapters/hook.py`:
```python
if who not in policy:
    if who.startswith("eng-") and "cto" in policy:
        who = "cto"
```
This fallback remains correct and defensive. After registration, known eng-* roles will match their own policy directly. Unknown eng-* variants (e.g., eng-security, eng-ml) will still fall back to cto. No code change needed.

## Next Step
Board must authorize AGENTS.md modification (break_glass or explicit ack). Once authorized, the prepared edit can be applied verbatim.
