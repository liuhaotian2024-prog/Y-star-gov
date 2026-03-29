# EXP-001 Reproducible Code Reference

This document contains verbatim code extracts from Y*gov v0.2.0 source for independent verification of the EXP-001 experiment results.

All code is extracted with line numbers. Security fixes FIX-1 through FIX-4 are included.

---

## 1. check() — Permission Enforcement (engine.py)

**Location:** `ystar/kernel/engine.py:310-628`

### 1.1 Function Signature and Entry Point

```python
# Line 310-331
def check(
    params:   Dict[str, Any],
    result:   Any,
    contract: IntentContract,
) -> CheckResult:
    """
    Check whether a function call satisfies an IntentContract.

    Args:
        params:   the actual function parameters {param_name: value}
        result:   the actual function return value (for postcondition checks)
        contract: the intent contract to check against

    Returns:
        CheckResult with passed=True if all constraints hold, False otherwise.

    v0.2.0 security changes vs v0.1.0:
        FIX-1: only_paths uses os.path.abspath+normpath (blocks ../ traversal)
        FIX-2: invariant/postcondition use AST-whitelisted _safe_eval() (blocks RCE)
        FIX-3: only_domains uses _domain_is_allowed() (blocks multi-part subdomain spoof)
        FIX-4: non-primitive params produce type_safety violations
    """
    violations: List[Violation] = []
```

### 1.2 FIX-4: Type Safety Pre-Check

```python
# Line 334-344
    # ── FIX-4: type safety pre-check ─────────────────────────────────────
    for k in _validate_param_types(params):
        violations.append(Violation(
            dimension  = "type_safety",
            field      = k,
            message    = (f"Parameter '{k}' has non-primitive type "
                          f"'{type(params[k]).__name__}' — string checks may be evaded"),
            actual     = type(params[k]).__name__,
            constraint = "primitive types only (str, int, float, bool, None, bytes)",
            severity   = 0.7,
        ))
```

### 1.3 FIX-1: only_paths Path Traversal Protection

```python
# Line 368-394
    if contract.only_paths:
        for p_name, p_value in params.items():
            # 明示的な非パスパラメータは除外
            if p_name.lower() in _NON_PATH_PARAM_NAMES:
                continue
            is_path = _is_path_param(p_name)
            if not is_path and isinstance(p_value, str):
                is_path = _classify_by_value(p_value) == "path"
            if not is_path:
                continue
            v_str = str(p_value)
            allowed = False
            for allowed_path in contract.only_paths:
                norm_path    = os.path.normpath(os.path.abspath(v_str))
                norm_allowed = os.path.normpath(os.path.abspath(allowed_path))
                if norm_path == norm_allowed or norm_path.startswith(norm_allowed + os.sep):
                    allowed = True
                    break
            if not allowed:
                violations.append(Violation(
                    dimension  = "only_paths",
                    field      = p_name,
                    message    = f"Path '{p_value}' is not in allowed paths {contract.only_paths}",
                    actual     = p_value,
                    constraint = f"only_paths={contract.only_paths}",
                    severity   = 0.9,
                ))
```

### 1.4 FIX-3: only_domains Strict Domain Matching

```python
# Line 192-219
def _domain_is_allowed(domain: str, allowed_domains: List[str]) -> bool:
    """
    Strict domain allowlist check (FIX-3).

    Permits:
      - Exact match:          domain == allowed
      - Single-label subdomain: x.allowed where x contains no dots

    Rejects (was accepted in v0.1.0):
      - Multi-part prefix:    a.b.allowed  (e.g. evil.com.api.github.com)
      - Suffix spoof:         allowed.evil.com
    """
    domain = domain.lower()
    for ad in allowed_domains:
        ad = ad.lower()
        if domain == ad:
            return True
        suffix = "." + ad
        if domain.endswith(suffix):
            prefix = domain[: -len(suffix)]
            # FIX-3: reject if prefix itself contains a dot.
            # "sub.api.github.com"      → prefix="sub"      → no dot → allow
            # "evil.com.api.github.com" → prefix="evil.com" → has dot → reject
            if "." not in prefix:
                return True
    return False
```

### 1.5 FIX-2: AST-Whitelisted Safe Eval

```python
# Line 245-286
def _safe_eval(expr: str, namespace: dict):
    """
    AST-whitelisted expression evaluator (FIX-2).

    Replaces bare eval() + {"__builtins__": {}} which is bypassable via
    Python's class hierarchy (__class__.__bases__[0].__subclasses__() ...).
    See CVE-equivalent analysis in ystar_paper.md Appendix A.3.

    The whitelist permits arithmetic, comparison, simple attribute access
    (result.get(...)), and dict subscript (result['key']) — all patterns
    that appear in typical invariant/postcondition expressions.
    All dunder attributes and free function calls are blocked at the AST
    level before any bytecode is executed.

    Returns: (result_value, error_message_or_None)
      If error_message is not None, the expression was rejected or failed.
    """
    try:
        tree = _ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return None, f"SyntaxError: {e}"

    for node in _ast.walk(tree):
        if type(node) not in _SAFE_AST_NODES:
            return None, f"Blocked AST node type: {type(node).__name__}"
        if isinstance(node, _ast.Attribute) and node.attr in _BLOCKED_ATTRS:
            return None, f"Blocked attribute access: '{node.attr}'"
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name):
            # Allow method calls (result.get(...)) but not free function calls.
            # Free function calls require a Name node as the func — e.g. open(),
            # eval(), __import__(). Method calls use an Attribute node.
            return None, f"Blocked free function call: '{node.func.id}'"

    try:
        return eval(
            compile(tree, "<invariant>", "eval"),
            {"__builtins__": {}},
            namespace,
        ), None
    except Exception as e:
        return None, str(e)
```

### 1.6 Invariant Evaluation with Safe Eval

```python
# Line 454-504
    # ── 5. invariant: Python expressions on input params ─────────────────
    # FIX-2: replaced eval()+{__builtins__:{}} with _safe_eval() (AST whitelist).
    for expr in contract.invariant:
        if not expr.strip():
            continue
        namespace = dict(params)
        namespace["params"] = params
        result_val, eval_err = _safe_eval(expr, namespace)
        if eval_err:
            if "is not defined" in str(eval_err):
                # FIX-C1: NameError means the invariant references a variable
                # that doesn't match any actual parameter name.
                # Previously silently skipped — now surfaced as phantom_variable
                # so the user knows the invariant is NOT being enforced.
                import re as _re
                m = _re.search(r"name '(\w+)' is not defined", str(eval_err))
                phantom = m.group(1) if m else "unknown"
                actual_names = list(params.keys())
                violations.append(Violation(
                    dimension  = "phantom_variable",
                    field      = "params",
                    message    = (
                        f"Invariant '{expr}' was skipped — "
                        f"'{phantom}' is not present in this call's parameters "
                        f"(got: {actual_names}).\n"
                        f"  Tip: use optional_invariant=['{expr}'] to check only "
                        f"when '{phantom}' is present, or fix the parameter name."
                    ),
                    actual     = phantom,
                    constraint = f"invariant: {expr}",
                    severity   = 0.6,  # warning-level: not blocked, but not enforced
                ))
            else:
                # Blocked by AST whitelist or other error — hard violation
                violations.append(Violation(
                    dimension  = "invariant",
                    field      = "params",
                    message    = f"Invariant expression rejected: '{expr}' — {eval_err}",
                    actual     = expr,
                    constraint = f"invariant: {expr}",
                    severity   = 1.0,
                ))
        elif not result_val:
            violations.append(Violation(
                dimension  = "invariant",
                field      = "params",
                message    = f"Invariant violated: '{expr}'",
                actual     = {k: v for k, v in params.items()},
                constraint = f"invariant: {expr}",
                severity   = 0.9,
            ))
```

### 1.7 Return Decision

```python
# Line 624-628
    return CheckResult(
        passed     = len(violations) == 0,
        violations = violations,
        contract   = contract,
    )
```

---

## 2. OmissionEngine — Obligation Tracking (omission_engine.py)

**Location:** `ystar/governance/omission_engine.py:138-284`

### 2.1 scan() Method Signature

```python
# Line 138-144
    def scan(self, now: Optional[float] = None) -> EngineResult:
        """
        扫描所有 pending obligations，检测过期，产出 violations / reminders / escalations。
        同时扫描已 EXPIRED 但未升级的 obligations，补充升级动作。
        幂等：对已有 violation 的 obligation 不重复创建。
        """
        now = now or self._now()
        result = EngineResult()
```

### 2.2 SOFT_OVERDUE → HARD_OVERDUE State Machine

```python
# Line 148-209
        pending = self.store.pending_obligations()

        for ob in pending:
            # 检查是否应发 reminder
            if self._should_remind(ob, now):
                ob.reminder_sent_at = now
                self.store.update_obligation(ob)
                result.reminders.append(ob)

            if not ob.is_overdue(now):
                continue

            # ── v0.33 Aging: Soft → Hard 双阶段超时 ──────────────────────
            # 阶段 1: SOFT_OVERDUE（首次越过 due_at）
            if ob.status == ObligationStatus.PENDING:
                ob.status           = ObligationStatus.SOFT_OVERDUE
                ob.soft_violation_at = now
                ob.soft_count       += 1
                # soft severity 升级：每次 soft_count +1 时提升
                if ob.soft_count >= 3 and ob.severity == Severity.LOW:
                    ob.severity = Severity.MEDIUM
                elif ob.soft_count >= 2 and ob.severity == Severity.MEDIUM:
                    ob.severity = Severity.HIGH
                self.store.update_obligation(ob)
                # 创建 soft violation（幂等）
                if not self.store.violation_exists_for_obligation(ob.obligation_id):
                    overdue_secs = now - (ob.effective_due_at or now)
                    v = self._create_violation(ob, now, overdue_secs)
                    self.store.add_violation(v)
                    self._write_to_cieu(ob, v)
                    result.violations.append(v)
                result.expired.append(ob)  # 兼容性：expired 列表仍包含 soft overdue
                self._update_entity_on_violation(ob)

            # 阶段 2: HARD_OVERDUE（超过 due_at + hard_overdue_secs）
            elif ob.status == ObligationStatus.SOFT_OVERDUE:
                hard_threshold = (ob.effective_due_at or now) + ob.hard_overdue_secs
                if now >= hard_threshold:
                    ob.status          = ObligationStatus.HARD_OVERDUE
                    ob.hard_violation_at = now
                    # hard overdue 强制提升到 HIGH/CRITICAL
                    if ob.severity == Severity.LOW:
                        ob.severity = Severity.MEDIUM
                    elif ob.severity == Severity.MEDIUM:
                        ob.severity = Severity.HIGH
                    self.store.update_obligation(ob)
                    # hard violation（独立幂等 key = obligation_id + "_hard"）
                    if not self._hard_violation_exists(ob.obligation_id):
                        overdue_secs = now - (ob.effective_due_at or now)
                        v = self._create_violation(ob, now, overdue_secs)
                        v.details["stage"] = "hard_overdue"
                        self.store.add_violation(v)
                        self._write_to_cieu(ob, v)
                        result.violations.append(v)
                    # 升级处理
                    if self._should_escalate(ob, now):
                        viols = self.store.list_violations(entity_id=ob.entity_id)
                        v = next((x for x in viols if x.obligation_id == ob.obligation_id), None)
                        if v:
                            v = self._escalate(ob, v, now)
                            self.store.update_violation(v)
                            result.escalated.append(v)
                    self._update_entity_on_violation(ob)
```

### 2.3 Action-Triggered Passive Detection (_try_fulfill)

```python
# Line 334-351
    def _try_fulfill(self, ev: GovernanceEvent) -> List[ObligationRecord]:
        """
        检查新事件是否能履行某些 open obligations。
        匹配条件：entity_id 相同 + event_type 在 required_event_types 中。
        v0.33: 扩展到 PENDING / SOFT_OVERDUE / HARD_OVERDUE 状态。
        """
        fulfilled = []
        # check all open-status obligations (PENDING + SOFT_OVERDUE + HARD_OVERDUE)
        all_obs = self.store.list_obligations(entity_id=ev.entity_id)
        for ob in all_obs:
            if not ob.status.is_open:
                continue
            if ev.event_type in ob.required_event_types:
                ob.status = ObligationStatus.FULFILLED
                ob.fulfilled_by_event_id = ev.event_id
                self.store.update_obligation(ob)
                fulfilled.append(ob)
        return fulfilled
```

### 2.4 Violation Creation and CIEU Integration

```python
# Line 407-429
    def _create_violation(
        self,
        ob: ObligationRecord,
        now: float,
        overdue_secs: float,
    ) -> OmissionViolation:
        return OmissionViolation(
            entity_id     = ob.entity_id,
            obligation_id = ob.obligation_id,
            actor_id      = ob.actor_id,
            omission_type = ob.obligation_type,
            detected_at   = now,
            overdue_secs  = overdue_secs,
            severity      = ob.severity,
            details       = {
                "required_event_types": ob.required_event_types,
                "due_at":              ob.due_at,
                "effective_due_at":    ob.effective_due_at,
                "violation_code":      ob.violation_code,
                "obligation_id":       ob.obligation_id,
                "trigger_event_id":    ob.trigger_event_id,
            },
        )
```

---

## 3. CIEU Seal — Tamper-Proof Audit Chain (cieu_store.py)

**Location:** `ystar/governance/cieu_store.py`

### 3.1 SQLite Schema with Merkle Root Tables

```python
# Line 49-146 (excerpt)
_SCHEMA = """
PRAGMA journal_mode = WAL;        -- concurrent write-safe
PRAGMA synchronous  = NORMAL;     -- crash-safe, high performance

CREATE TABLE IF NOT EXISTS cieu_events (
    -- 主キー・順序
    rowid        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT    NOT NULL UNIQUE,    -- UUID (dedup key)
    seq_global   INTEGER NOT NULL,           -- μs timestamp (global order)
    created_at   REAL    NOT NULL,           -- Unix timestamp

    -- エージェント・セッション
    session_id   TEXT    NOT NULL,
    agent_id     TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,

    -- 決定
    decision     TEXT    NOT NULL,           -- allow / deny / escalate
    passed       INTEGER NOT NULL DEFAULT 0, -- 1=passed, 0=violated

    -- 違反・ドリフト
    violations   TEXT,                       -- JSON array
    drift_detected INTEGER NOT NULL DEFAULT 0,
    drift_details TEXT,
    drift_category TEXT,

    -- 対象
    file_path    TEXT,
    command      TEXT,
    url          TEXT,
    skill_name   TEXT,
    skill_source TEXT,
    task_description TEXT,

    -- 合約
    contract_hash TEXT,
    chain_depth   INTEGER DEFAULT 0,

    -- [FIX-1] 完整调用现场快照 ─────────────────────────────────────────
    params_json       TEXT,
    result_json       TEXT,
    human_initiator   TEXT,
    lineage_path      TEXT,

    -- 監査
    sealed       INTEGER NOT NULL DEFAULT 0  -- 1=sealed (tamper-evident)
);

-- [FIX-3] 封印会话的密码学证明表 ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS sealed_sessions (
    session_id   TEXT    PRIMARY KEY,
    sealed_at    REAL    NOT NULL,           -- Unix timestamp
    event_count  INTEGER NOT NULL,           -- 封印时的事件数量
    merkle_root  TEXT    NOT NULL,           -- SHA-256(sorted event_ids)
    prev_root    TEXT,                       -- 前一次封印的 merkle_root（哈希链）
    db_path      TEXT                        -- 记录来自哪个 DB 文件
);
"""
```

### 3.2 seal_session() — Cryptographic Sealing

```python
# Line 596-664
    def seal_session(self, session_id: str) -> dict:
        """
        [FIX-3] 对指定 session 的所有记录进行密码学封印。

        做两件事：
        1. 将该 session 所有行的 sealed 标志置为 1（逻辑标记，向后兼容）。
        2. 计算该 session 所有 event_id（按 seq_global 排序）的 SHA-256，
           写入 sealed_sessions 表，并链接到上一次封印的 merkle_root。

        这使封印从"逻辑标记"升级为"可独立验证的密码学承诺"：
        - 任何人持有 event_id 列表即可重算 merkle_root 验证完整性。
        - prev_root 形成哈希链，防止历史记录被整体替换。

        Returns dict with:
            session_id, event_count, merkle_root, prev_root, sealed_at
        """
        now = time.time()

        with self._conn() as conn:
            # 1. 获取该 session 所有 event_id，按 seq_global 排序
            rows = conn.execute(
                "SELECT event_id FROM cieu_events "
                "WHERE session_id = ? ORDER BY seq_global ASC",
                (session_id,)
            ).fetchall()

            event_ids = [r["event_id"] for r in rows]
            event_count = len(event_ids)

            if event_count == 0:
                return {
                    "session_id": session_id,
                    "event_count": 0,
                    "merkle_root": None,
                    "prev_root": None,
                    "sealed_at": now,
                    "warning": "no events found for this session",
                }

            # 2. 计算 merkle root：SHA-256(event_id_0 \n event_id_1 \n ...)
            payload = "\n".join(event_ids).encode("utf-8")
            merkle_root = hashlib.sha256(payload).hexdigest()

            # 3. 获取前一次封印的 root（哈希链连接）
            prev_row = conn.execute(
                "SELECT merkle_root FROM sealed_sessions ORDER BY sealed_at DESC LIMIT 1"
            ).fetchone()
            prev_root = prev_row["merkle_root"] if prev_row else None

            # 4. 写入 sealed_sessions（REPLACE 幂等：重复封印更新记录）
            conn.execute("""
                INSERT OR REPLACE INTO sealed_sessions
                    (session_id, sealed_at, event_count, merkle_root, prev_root, db_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, now, event_count, merkle_root, prev_root, str(self.db_path)))

            # 5. 更新逻辑 sealed 标志（向后兼容）
            conn.execute(
                "UPDATE cieu_events SET sealed=1 WHERE session_id=?",
                (session_id,)
            )

        return {
            "session_id":   session_id,
            "event_count":  event_count,
            "merkle_root":  merkle_root,
            "prev_root":    prev_root,
            "sealed_at":    now,
        }
```

### 3.3 verify_session_seal() — Hash Chain Verification

```python
# Line 666-728
    def verify_session_seal(self, session_id: str) -> dict:
        """
        [FIX-3] 验证某个 session 的封印完整性。

        重新计算当前 DB 中该 session 的 merkle_root，
        与 sealed_sessions 表中记录的 root 对比。

        Returns dict with:
            session_id, valid (bool), stored_root, computed_root,
            event_count, tamper_evidence (str if mismatch)
        """
        with self._conn() as conn:
            # 从 sealed_sessions 读取存档的 root
            seal_row = conn.execute(
                "SELECT * FROM sealed_sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()

            if seal_row is None:
                return {
                    "session_id": session_id,
                    "valid": False,
                    "error": "session has never been sealed",
                }

            stored_root  = seal_row["merkle_root"]
            stored_count = seal_row["event_count"]

            # 重新计算当前 event_ids
            rows = conn.execute(
                "SELECT event_id FROM cieu_events "
                "WHERE session_id = ? ORDER BY seq_global ASC",
                (session_id,)
            ).fetchall()
            current_ids   = [r["event_id"] for r in rows]
            current_count = len(current_ids)

            payload       = "\n".join(current_ids).encode("utf-8")
            computed_root = hashlib.sha256(payload).hexdigest()

        valid = (computed_root == stored_root)
        result: Dict[str, Any] = {
            "session_id":    session_id,
            "valid":         valid,
            "stored_root":   stored_root,
            "computed_root": computed_root,
            "stored_count":  stored_count,
            "current_count": current_count,
            "sealed_at":     seal_row["sealed_at"],
        }
        if not valid:
            if current_count != stored_count:
                result["tamper_evidence"] = (
                    f"event count mismatch: sealed={stored_count}, "
                    f"current={current_count} "
                    f"({'events added' if current_count > stored_count else 'events deleted'})"
                )
            else:
                result["tamper_evidence"] = (
                    "event_id content mismatch with same count "
                    "(possible event replacement)"
                )
        return result
```

---

## 4. PreToolUse Hook — Claude Code Integration

**Location:** Multiple files

### 4.1 hooks.json Declaration

**File:** `skill/hooks/hooks.json`

```json
{
  "PreToolUse": [
    {
      "matcher": "Task|SubagentSpawn|Bash|Write|Edit|MultiEdit|WebFetch",
      "hooks": [
        {
          "type": "command",
          "command": "python3 ${CLAUDE_PLUGIN_ROOT}/skills/ystar-govern/check.py --action ${TOOL_NAME} --params '${TOOL_INPUT_JSON}' --principal ${AGENT_ID} --actor subagent"
        }
      ]
    }
  ],
  "SubagentStop": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "python3 -c \"import json,sys; d=json.loads(sys.stdin.read() or '{}'); print(f'[Y*gov] Subagent {d.get(\\\"agent_id\\\",\\\"?\\\")}: completed')\""
        }
      ]
    }
  ]
}
```

### 4.2 check_hook() Entry Point

**File:** `ystar/adapters/hook.py:178-236`

```python
def check_hook(
    hook_payload: Dict[str, Any],
    policy: Policy,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    处理一个 OpenClaw PreToolUse hook，返回 hook 响应。

    执行深度根据上下文自动选择，用户无需配置：

    有 .ystar_session.json（ystar init 已运行）：
      → enforce()：委托链验证 + 漂移检测 + CIEU 五元组 + Omission 注入
    无 .ystar_session.json：
      → Policy.check()：规则检查 + 基础 CIEU 写入

    Args:
        hook_payload: OpenClaw 发来的原始 hook dict
        policy:       Policy 对象（从 Policy.from_agents_md() 获得）
        agent_id:     覆盖 payload 里的 agent_id（可选）

    Returns:
        {} 表示允许，{"action":"block",...} 表示拒绝
    """
    tool_name  = hook_payload.get("tool_name", "")
    tool_input = hook_payload.get("tool_input", {})
    who        = agent_id or hook_payload.get("agent_id", "agent")
    session_id_payload = hook_payload.get("session_id", "")

    # 若 agent_id 未在 Policy 里注册，回退到第一个已注册的角色
    if who not in policy:
        registered = list(policy._rules.keys())
        if registered:
            who = registered[0]

    # ── 尝试完整治理路径（有 session 配置时自动升级）────────────────
    session_cfg = _load_session_config()
    if session_cfg:
        try:
            response = _check_hook_full(
                hook_payload, policy, who, tool_name, tool_input,
                session_id_payload or session_cfg.get("session_id", ""),
                session_cfg,
            )
            return response
        except Exception:
            pass   # 完整路径失败 → 静默降级到轻量路径

    # ── 轻量路径（无 session 或完整路径失败）────────────────────────
    params   = _extract_params(tool_name, tool_input)
    result   = policy.check(who, tool_name, **params)

    # 即使是轻量路径，也写入基础 CIEU（有 .ystar_cieu.db 时）
    cieu_db = session_cfg.get("cieu_db", ".ystar_cieu.db") if session_cfg else ".ystar_cieu.db"
    contract = policy._rules.get(who)
    contract_hash = contract.hash if contract else ""
    _write_cieu(who, tool_name, params, result,
                session_id_payload or "unknown", contract_hash, cieu_db)

    return _result_to_response(result)
```

### 4.3 CIEU Write Integration

**File:** `ystar/adapters/hook.py:154-176`

```python
def _write_cieu(
    who: str, tool_name: str, params: dict,
    result: PolicyResult, session_id: str,
    contract_hash: str, cieu_db: str,
) -> None:
    """把 check 结果写入 CIEU 数据库（静默失败，不影响执行路径）。"""
    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(cieu_db)
        store.write_dict({
            "session_id":    session_id,
            "agent_id":      who,
            "event_type":    tool_name,
            "decision":      "allow" if result.allowed else "deny",
            "passed":        result.allowed,
            "violations":    [{"dimension": v.dimension, "message": v.message}
                              for v in (result.violations or [])],
            "params":        params,
            "contract_hash": contract_hash,
        })
    except Exception:
        pass   # CIEU 写入失败不影响 hook 的阻断/放行决策
```

### 4.4 Omission Engine Integration in Hooks

**File:** `ystar/adapters/hook.py:489-530`

```python
# Line 489-530
    def _write_to_cieu(
        self,
        ob: ObligationRecord,
        v: OmissionViolation,
    ) -> None:
        try:
            cieu_record = {
                "event_id":    str(uuid.uuid4()),
                "seq_global":  int(self._now() * 1_000_000),
                "created_at":  self._now(),
                "session_id":  ob.entity_id,
                "agent_id":    ob.actor_id,
                "event_type":  f"omission_violation:{ob.obligation_type}",
                "decision":    "escalate",
                "passed":      False,
                "violations":  [{
                    "dimension":  "omission_governance",
                    "field":      "required_event",
                    "message":    (
                        f"{ob.obligation_type}: actor '{ob.actor_id}' "
                        f"failed to produce {ob.required_event_types} "
                        f"for entity '{ob.entity_id}' "
                        f"(overdue {v.overdue_secs:.1f}s)"
                    ),
                    "actual":     "no_required_event",
                    "constraint": f"due_at={ob.due_at}",
                    "severity":   0.8 if ob.severity == Severity.HIGH else 0.5,
                }],
                "drift_detected": True,
                "drift_details":  f"omission_type={ob.obligation_type}",
                "drift_category": "omission_failure",
                "task_description": (
                    f"Omission: {ob.obligation_type} | "
                    f"entity={ob.entity_id} | actor={ob.actor_id}"
                ),
            }
            ok = self.cieu_store.write_dict(cieu_record)
            if ok:
                v.cieu_ref = cieu_record["event_id"]
        except Exception:
            pass  # CIEU 写入失败不阻断主流程
```

---

## 5. CIEU Database Verification

### 5.1 Direct SQL Inspection

To verify CIEU records independently, use SQLite CLI or Python:

```bash
# Open the CIEU database
sqlite3 .ystar_cieu.db

# View all events
SELECT event_id, created_at, agent_id, decision, event_type, passed
FROM cieu_events
ORDER BY seq_global DESC
LIMIT 10;

# View violations only
SELECT event_id, agent_id, event_type, violations, drift_details
FROM cieu_events
WHERE passed = 0
ORDER BY created_at DESC;

# Verify seal integrity for a session
SELECT session_id, event_count, merkle_root, prev_root, sealed_at
FROM sealed_sessions
WHERE session_id = 'YOUR_SESSION_ID';

# Count events by decision type
SELECT decision, COUNT(*) as count
FROM cieu_events
GROUP BY decision;
```

### 5.2 Python Verification Script

```python
from ystar.governance.cieu_store import CIEUStore
import hashlib

# Open the store
store = CIEUStore(".ystar_cieu.db")

# Query recent events
recent = store.query(limit=10)
for event in recent:
    print(f"{event.created_at}: {event.decision} - {event.event_type}")

# Get statistics
stats = store.stats()
print(f"Total events: {stats['total']}")
print(f"Deny rate: {stats['deny_rate']:.1%}")
print(f"Drift rate: {stats['drift_rate']:.1%}")

# Verify seal integrity
session_id = "exp-001-session"
result = store.verify_session_seal(session_id)
if result["valid"]:
    print(f"✓ Seal verified: {result['computed_root']}")
else:
    print(f"✗ TAMPER DETECTED: {result['tamper_evidence']}")

# Manual Merkle root recalculation (independent verification)
import sqlite3
conn = sqlite3.connect(".ystar_cieu.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT event_id FROM cieu_events WHERE session_id = ? ORDER BY seq_global ASC",
    (session_id,)
).fetchall()
event_ids = [r["event_id"] for r in rows]
payload = "\n".join(event_ids).encode("utf-8")
computed_root = hashlib.sha256(payload).hexdigest()
print(f"Independently computed root: {computed_root}")
```

### 5.3 ystar CLI Commands

```bash
# Query CIEU records
ystar report --session exp-001-session --limit 50

# Export to JSONL for external auditing
ystar cieu export --session exp-001-session --output audit.jsonl

# Verify seal
ystar cieu verify --session exp-001-session

# Statistics summary
ystar cieu stats --since "2026-03-26"
```

---

## Reproducibility Notes

1. All line numbers reference Y*gov v0.2.0 (commit hash: in git log)
2. Security fixes FIX-1 through FIX-4 are included in this version
3. The CIEU database schema is stable across v0.2.x releases
4. Merkle root computation is deterministic: `SHA-256("\n".join(sorted_event_ids))`
5. The hook entry point is `check_hook()` in `ystar/adapters/hook.py`

To reproduce experiment results:
1. Install Y*gov v0.2.0: `pip install ystar==0.2.0`
2. Run the experiment workflow (documented in EXP-001 report)
3. Query `.ystar_cieu.db` using the SQL commands above
4. Verify seal using `store.verify_session_seal(session_id)`

All code extracts are verbatim from source with line numbers for traceability.
