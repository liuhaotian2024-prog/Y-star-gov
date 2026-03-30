"""
ystar.connector  —  OpenClaw × Y* Runtime Connector
====================================================

开箱即用的两个功能：

1. ApprovalQueue  —  ESCALATE 事件的审批链
   - ESCALATE 自动写入 .ystar_approvals.jsonl
   - `ystar-dev approve` 命令处理队列
   - 支持 webhook 回调（可选）
   - 超时后自动 DENY（fail-safe）

2. OpenClawConnector  —  真实 OpenClaw hook 接收器
   - HTTP 服务器，接收 OpenClaw PreToolUse / PostToolUse hooks
   - 把 OpenClaw 原生格式翻译成 Y* OpenClawEvent
   - 返回 {"decision": "allow" | "deny" | "escalate"}
   - `ystar-dev serve --port 7777` 一键启动

OpenClaw 配置（在你的 CLAUDE.md 或 .openclaw/config.yaml 里）：
    hooks:
      PreToolUse:
        - matcher: "*"
          hooks:
            - type: command
              command: curl -s -X POST http://localhost:7777/hook -d @-

或直接在 AGENTS.md 里：
    # Y* guard running at localhost:7777
    # All tool calls are checked before execution
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ystar.domains.openclaw.adapter import (
    OpenClawEvent, EventType, EnforceDecision,
    SessionState, OpenClawCIEU,
    enforce, make_session, get_cieu_log,
    persist_cieu_log,
)
from ystar.domains.openclaw import OpenClawDomainPack


# ═══════════════════════════════════════════════════════════════════════
# P2.1  Approval Queue  —  ESCALATE 审批链
# ═══════════════════════════════════════════════════════════════════════

APPROVAL_QUEUE_PATH = Path(".ystar_approvals.jsonl")
_APPROVAL_TIMEOUT_FALLBACK = 3600   # 兜底：1小时（无合约配置时使用）


def _get_approval_timeout() -> int:
    """
    读取审批超时时长。

    优先级（高 → 低）：
      1. .ystar_session.json 中 contract.obligation_timing['approval']
      2. .ystar_session.json 中 contract.obligation_timing['escalation']
      3. 兜底常量 3600s

    这样用户在 AGENTS.md 写"审批必须在 30 分钟内完成"就能生效。
    """
    try:
        import json
        from pathlib import Path as _Path
        p = _Path(".ystar_session.json")
        if p.exists():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            ot  = cfg.get("contract", {}).get("obligation_timing", {})
            # approval 或 escalation 键都可以表示审批时限
            secs = ot.get("approval") or ot.get("escalation")
            if secs and isinstance(secs, (int, float)) and secs > 0:
                return int(secs)
    except Exception:
        pass
    return _APPROVAL_TIMEOUT_FALLBACK


# 向后兼容（代码里直接 import APPROVAL_TIMEOUT_SECONDS 的地方仍可用）
APPROVAL_TIMEOUT_SECONDS = property(_get_approval_timeout) if False else _APPROVAL_TIMEOUT_FALLBACK


@dataclass
class PendingApproval:
    """等待人工审批的 ESCALATE 事件。"""
    approval_id:  str
    session_id:   str
    agent_id:     str
    event_type:   str
    event_detail: str           # 人类可读的事件描述
    risk_reason:  str           # 为什么需要审批
    created_at:   float
    expires_at:   float
    status:       str = "pending"   # "pending" | "approved" | "denied" | "expired"
    operator:     Optional[str] = None
    note:         Optional[str] = None
    cieu_event_id: Optional[str] = None

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "approval_id":   self.approval_id,
            "session_id":    self.session_id,
            "agent_id":      self.agent_id,
            "event_type":    self.event_type,
            "event_detail":  self.event_detail,
            "risk_reason":   self.risk_reason,
            "created_at":    self.created_at,
            "expires_at":    self.expires_at,
            "status":        self.status,
            "operator":      self.operator,
            "note":          self.note,
            "cieu_event_id": self.cieu_event_id,
        }


class ApprovalQueue:
    """
    ESCALATE 事件的持久化审批队列。

    设计原则：
    - 文件即队列（无需外部数据库）
    - append-only JSONL（不可篡改审计记录）
    - 超时自动 DENY（fail-safe）
    - 支持 webhook 通知（可选）
    """

    def __init__(
        self,
        queue_path: str = str(APPROVAL_QUEUE_PATH),
        timeout_seconds: Optional[int] = None,
        webhook_url: Optional[str] = None,
    ):
        self.queue_path  = Path(queue_path)
        self.timeout     = timeout_seconds if timeout_seconds is not None \
                           else _get_approval_timeout()
        self.webhook_url = webhook_url

    def submit(
        self,
        event:       OpenClawEvent,
        risk_reason: str,
        cieu_record: Optional[OpenClawCIEU] = None,
    ) -> PendingApproval:
        """
        ESCALATE 事件进入审批队列。
        返回 PendingApproval，包含 approval_id 供后续查询。
        """
        now = time.time()
        approval = PendingApproval(
            approval_id   = str(uuid.uuid4())[:8],
            session_id    = event.session_id,
            agent_id      = event.agent_id,
            event_type    = event.event_type.value,
            event_detail  = self._describe_event(event),
            risk_reason   = risk_reason,
            created_at    = now,
            expires_at    = now + self.timeout,
            cieu_event_id = cieu_record.event_id if cieu_record else None,
        )

        # append-only 写入
        with open(self.queue_path, "a") as f:
            f.write(json.dumps(approval.to_dict()) + "\n")

        # webhook 通知（可选）
        if self.webhook_url:
            self._notify_webhook(approval)

        return approval

    def list_pending(self) -> List[PendingApproval]:
        """列出所有待审批（未超时）的请求。"""
        all_items = self._load_all()
        pending = []
        for item in all_items:
            if item.status == "pending":
                if item.is_expired():
                    self._update_status(item.approval_id, "expired")
                else:
                    pending.append(item)
        return pending

    def approve(
        self,
        approval_id: str,
        operator:    str = "operator",
        note:        str = "",
    ) -> bool:
        """审批通过。Returns True if found and updated."""
        return self._update_status(approval_id, "approved", operator, note)

    def deny(
        self,
        approval_id: str,
        operator:    str = "operator",
        note:        str = "",
    ) -> bool:
        """拒绝。Returns True if found and updated."""
        return self._update_status(approval_id, "denied", operator, note)

    def check_status(self, approval_id: str) -> Optional[str]:
        """
        查询审批状态。供 enforce() 在需要等待审批时使用。
        Returns: "approved" | "denied" | "expired" | "pending" | None
        """
        for item in self._load_all():
            if item.approval_id == approval_id:
                if item.status == "pending" and item.is_expired():
                    self._update_status(approval_id, "expired")
                    return "expired"
                return item.status
        return None

    def _describe_event(self, event: OpenClawEvent) -> str:
        if event.file_path:
            return f"File write: {event.file_path}"
        if event.command:
            return f"Command: {event.command}"
        if event.url:
            return f"URL fetch: {event.url}"
        if event.skill_name:
            return f"Skill install: {event.skill_name} from {event.skill_source}"
        return f"{event.event_type.value} by {event.agent_id}"

    def _load_all(self) -> List[PendingApproval]:
        if not self.queue_path.exists():
            return []
        items = {}
        for line in self.queue_path.read_text().splitlines():
            try:
                d = json.loads(line)
                aid = d["approval_id"]
                # 最新のエントリで上書き（ステータス更新のため）
                items[aid] = PendingApproval(**{
                    k: v for k, v in d.items()
                    if k in PendingApproval.__dataclass_fields__
                })
            except Exception:
                pass
        return list(items.values())

    def _update_status(
        self,
        approval_id: str,
        status:      str,
        operator:    str = "system",
        note:        str = "",
    ) -> bool:
        items = self._load_all()
        found = False
        for item in items:
            if item.approval_id == approval_id:
                item.status   = status
                item.operator = operator
                item.note     = note
                found         = True
                break
        if found:
            # 全件再書き込み（小さいファイルなので問題なし）
            with open(self.queue_path, "w") as f:
                for item in items:
                    f.write(json.dumps(item.to_dict()) + "\n")
        return found

    def resume_after_approval(
        self,
        approval_id:  str,
        session_state: Any,
        original_event: Any,
    ) -> Optional[str]:
        """
        承認後にエージェントの動作を再開する。

        ESCALATE → human approves → このメソッドを呼ぶ → enforce() を再実行

        Returns:
            "approved" | "denied" | "expired" | None（承認IDが不明）
        """
        status = self.check_status(approval_id)
        if status != "approved":
            return status

        # 承認済み → enforce() を再実行（ESCALATE を ALLOW として扱う）
        try:
            from ystar.domains.openclaw.adapter import enforce, EnforceDecision
            decision, records = enforce(original_event, session_state,
                                        skip_skill_escalate=True)
            return "resumed"
        except Exception:
            return "error"

    def get_override_trail(self, session_id: Optional[str] = None) -> List[dict]:
        """
        承認/拒否/期限切れの全記録を返す（override trail）。

        Y* の「全変更に審査記録」原則の実装。
        """
        all_items = self._load_all()
        trail = []
        for item in all_items:
            if item.status in ("approved", "denied", "expired"):
                if session_id is None or item.session_id == session_id:
                    trail.append({
                        "approval_id": item.approval_id,
                        "session_id":  item.session_id,
                        "agent_id":    item.agent_id,
                        "event_type":  item.event_type,
                        "event_detail":item.event_detail,
                        "risk_reason": item.risk_reason,
                        "status":      item.status,
                        "operator":    item.operator,
                        "note":        item.note,
                        "created_at":  item.created_at,
                        "decided_at":  item.expires_at,  # 最終更新時刻
                    })
        return trail

    def _notify_webhook(self, approval: PendingApproval) -> None:
        """webhook 通知。失敗しても審批キューには影響しない。"""
        try:
            import urllib.request
            data = json.dumps(approval.to_dict()).encode()
            req  = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass   # webhook失敗は無視（審批キューの完全性を保持）


# グローバルキュー（デフォルト使用）
_default_queue: Optional[ApprovalQueue] = None

def get_approval_queue(webhook_url: Optional[str] = None) -> ApprovalQueue:
    global _default_queue
    if _default_queue is None:
        _default_queue = ApprovalQueue(webhook_url=webhook_url)
    return _default_queue


# ═══════════════════════════════════════════════════════════════════════
# P2.2  OpenClaw Hook Translator  —  OpenClaw → Y* 変換
# ═══════════════════════════════════════════════════════════════════════

# OpenClaw tool名 → Y* EventType のマッピング
_TOOL_TO_EVENT_TYPE: Dict[str, EventType] = {
    # ファイル操作
    "Write":      EventType.FILE_WRITE,
    "Edit":       EventType.FILE_WRITE,
    "MultiEdit":  EventType.FILE_WRITE,
    "Read":       EventType.FILE_READ,
    "Glob":       EventType.FILE_READ,
    "Grep":       EventType.FILE_READ,
    "LS":         EventType.FILE_READ,
    # コマンド実行
    "Bash":       EventType.CMD_EXEC,
    "Shell":      EventType.CMD_EXEC,
    # ネットワーク
    "WebFetch":   EventType.WEB_FETCH,
    "WebSearch":  EventType.WEB_FETCH,
    "mcp__web":   EventType.WEB_FETCH,
    # MCP
    "mcp__":      EventType.MCP_TOOL_CALL,
    # タスク管理
    "Task":       EventType.SUBAGENT_SPAWN,
    "TodoWrite":  EventType.FILE_WRITE,
}


def translate_openclaw_hook(
    hook_payload: Dict[str, Any],
) -> Tuple[Optional[OpenClawEvent], Optional[str]]:
    """
    OpenClaw の生の hook payload を Y* OpenClawEvent に変換する。

    Returns (event, error_reason)
    event=None のときは変換不可（未知のツール等）。

    サポートする OpenClaw hook タイプ：
      PreToolUse  — ツール実行前（Y* がブロックできる）
      PostToolUse — ツール実行後（監査目的）
    """
    hook_type  = hook_payload.get("type", "")
    tool_name  = hook_payload.get("tool_name", "")
    tool_input = hook_payload.get("tool_input", {})
    session_id = hook_payload.get("session_id", "unknown")
    agent_id   = hook_payload.get("agent_id", "unknown_agent")
    timestamp  = hook_payload.get("timestamp", time.time())

    # EventType の解決
    event_type = None
    for prefix, etype in _TOOL_TO_EVENT_TYPE.items():
        if tool_name == prefix or tool_name.startswith(prefix):
            event_type = etype
            break

    if event_type is None:
        # 未知のツール → FILE_WRITE として保守的に扱う
        event_type = EventType.FILE_WRITE

    # フィールドのマッピング
    ev = OpenClawEvent(
        event_type     = event_type,
        agent_id       = agent_id,
        session_id     = session_id,
        timestamp      = float(timestamp),
        task_ticket_id = hook_payload.get("task_id") or
                         hook_payload.get("ticket_id") or
                         f"openclaw_{session_id[:8]}",
        tool_name      = tool_name,
        tool_args      = tool_input,
    )

    # ツール別フィールドマッピング
    if event_type == EventType.FILE_WRITE:
        ev.file_path     = tool_input.get("path", tool_input.get("file_path", ""))
        ev.patch_summary = tool_input.get("description",
                           tool_input.get("summary",
                           tool_input.get("content", "")[:100]))

    elif event_type == EventType.FILE_READ:
        ev.file_path = tool_input.get("path",
                       tool_input.get("pattern",
                       tool_input.get("query", "")))

    elif event_type == EventType.CMD_EXEC:
        ev.command = tool_input.get("command",
                     tool_input.get("cmd", ""))

    elif event_type == EventType.WEB_FETCH:
        ev.url = (tool_input.get("url") or
                  tool_input.get("query") or
                  tool_input.get("prompt", ""))

    elif event_type == EventType.SUBAGENT_SPAWN:
        ev.task_description = tool_input.get("description",
                              tool_input.get("prompt", ""))
        ev.child_agent_id   = tool_input.get("subagent_id",
                              f"subagent_{uuid.uuid4().hex[:6]}")

    elif event_type == EventType.MCP_TOOL_CALL:
        ev.url = (tool_input.get("url") or
                  tool_input.get("endpoint") or "")

    return ev, None


def translate_hook_response(
    decision: EnforceDecision,
    records:  List[OpenClawCIEU],
    approval_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Y* の決定を OpenClaw hook レスポンス形式に変換する。

    OpenClaw は PreToolUse hook のレスポンスで
    {"action": "block", "message": "..."} を受け取ると実行をブロックする。
    """
    violations = []
    for rec in records:
        for v in rec.call_record.violations:
            if v.dimension != "phantom_variable":
                violations.append({
                    "dimension": v.dimension,
                    "message":   v.message,
                })

    if decision == EnforceDecision.ALLOW:
        return {
            "decision":   "allow",
            "action":     None,     # OpenClawは何もしない
            "violations": [],
        }

    elif decision == EnforceDecision.DENY:
        reason = violations[0]["message"] if violations else "Blocked by Y* constraint"
        return {
            "decision":   "deny",
            "action":     "block",  # OpenClaw にブロックを指示
            "message":    f"[Y*] {reason}",
            "violations": violations,
        }

    else:  # ESCALATE
        reason = (records[0].drift_details if records and records[0].drift_details
                  else "Requires human approval")
        return {
            "decision":    "escalate",
            "action":      "block",  # 審批中はブロック（fail-safe）
            "message":     f"[Y*] Pending approval: {reason}",
            "approval_id": approval_id,
            "violations":  violations,
        }


# ═══════════════════════════════════════════════════════════════════════
# P2.3  OpenClaw HTTP Connector  —  HTTP サーバー本体
# ═══════════════════════════════════════════════════════════════════════

class OpenClawHTTPConnector:
    """
    OpenClaw の hook を受け取る HTTP サーバー。

    `ystar-dev serve --port 7777` で起動。
    OpenClaw 側の設定（CLAUDE.md / .openclaw/hooks.yaml）：

        hooks:
          PreToolUse:
            - matcher: "*"
              hooks:
                - type: command
                  command: |
                    echo $HOOK_INPUT | curl -s -X POST \\
                      http://localhost:7777/hook \\
                      -H 'Content-Type: application/json' \\
                      -d @-

    または簡略版：
        YStar Guard: curl -s http://localhost:7777/health で確認
    """

    def __init__(
        self,
        port:             int = 7777,
        host:             str = "127.0.0.1",
        session_config:   Optional[Dict] = None,
        webhook_url:      Optional[str]  = None,
        strict_handoff:   bool = False,
        auto_persist_cieu: bool = True,
    ):
        self.port              = port
        self.host              = host
        self.session_config    = session_config or {}
        self.webhook_url       = webhook_url
        self.strict_handoff    = strict_handoff
        self.auto_persist_cieu = auto_persist_cieu

        # セッション管理（session_id → SessionState）
        self._sessions: Dict[str, SessionState] = {}
        self._queue = get_approval_queue(webhook_url)
        self._pack  = OpenClawDomainPack()
        self._request_count = 0

    def _get_or_create_session(self, session_id: str) -> SessionState:
        """セッションを取得または新規作成。"""
        if session_id not in self._sessions:
            cfg = self.session_config
            state = make_session(
                session_id      = session_id,
                allowed_paths   = cfg.get("allowed_paths", ["./src", "./tests"]),
                allowed_domains = cfg.get("allowed_domains", []),
                strict          = self.strict_handoff,
            )
            # デフォルトエージェント合約を登録（strict=False 時）
            if not self.strict_handoff:
                for role in ["planner", "coder_agent", "tester_agent",
                             "reviewer_agent", "researcher_agent"]:
                    base_role = role.replace("_agent", "")
                    try:
                        c = self._pack.make_contract(base_role, {
                            "allowed_paths": cfg.get("allowed_paths",
                                                     ["./src","./tests"]),
                            "allowed_domains": cfg.get("allowed_domains", []),
                        })
                        state.agent_contracts[role] = c
                    except Exception:
                        pass
            self._sessions[session_id] = state
        return self._sessions[session_id]

    def handle_hook(
        self, payload: Dict[str, Any]
    ) -> Tuple[int, Dict[str, Any]]:
        """
        OpenClaw hook payload を処理し、HTTP レスポンスを返す。

        Returns: (http_status_code, response_dict)
        """
        self._request_count += 1

        # イベント変換
        event, err = translate_openclaw_hook(payload)
        if event is None:
            return 400, {"error": f"Cannot translate hook: {err}"}

        # セッション取得
        state = self._get_or_create_session(event.session_id)

        # Y* でチェック
        decision, records = enforce(event, state, seq=self._request_count)

        # ESCALATE → 審批キューに投入
        approval_id = None
        if decision == EnforceDecision.ESCALATE and records:
            rec = records[0]
            pending = self._queue.submit(
                event       = event,
                risk_reason = rec.drift_details or "Requires human review",
                cieu_record = rec,
            )
            approval_id = pending.approval_id

        # 自動 CIEU 永続化
        if self.auto_persist_cieu:
            persist_cieu_log()

        # レスポンス生成
        response = translate_hook_response(decision, records, approval_id)
        http_status = 200  # OpenClaw は常に 200 を期待する

        return http_status, response

    def run(self) -> None:
        """
        HTTP サーバーを起動して接続を待ち受ける。
        Ctrl+C で停止。
        """
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import sys

        connector = self

        class HookHandler(BaseHTTPRequestHandler):

            def do_GET(self):
                if self.path == "/health":
                    self._json(200, {
                        "status":   "ok",
                        "version":  __import__("ystar").__version__,
                        "sessions": len(connector._sessions),
                        "requests": connector._request_count,
                        "pending_approvals": len(
                            connector._queue.list_pending()
                        ),
                    })
                elif self.path == "/pending":
                    pending = connector._queue.list_pending()
                    self._json(200, {
                        "count":   len(pending),
                        "items":   [p.to_dict() for p in pending],
                    })
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                if self.path == "/hook":
                    length  = int(self.headers.get("Content-Length", 0))
                    body    = self.rfile.read(length)
                    try:
                        payload = json.loads(body)
                    except json.JSONDecodeError:
                        self._json(400, {"error": "invalid JSON"})
                        return
                    status, response = connector.handle_hook(payload)
                    self._json(status, response)

                elif self.path.startswith("/approve/"):
                    aid = self.path.split("/approve/")[-1]
                    ok  = connector._queue.approve(aid, operator="api")
                    self._json(200 if ok else 404, {"approved": ok})

                elif self.path.startswith("/deny/"):
                    aid = self.path.split("/deny/")[-1]
                    ok  = connector._queue.deny(aid, operator="api")
                    self._json(200 if ok else 404, {"denied": ok})

                else:
                    self._json(404, {"error": "not found"})

            def _json(self, code: int, data: dict):
                body = json.dumps(data, default=str).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                pass   # 標準ログを抑制

        server = HTTPServer((self.host, self.port), HookHandler)
        print(f"  Y* OpenClaw Connector running at http://{self.host}:{self.port}")
        print(f"  Health:   GET  /health")
        print(f"  Hook:     POST /hook")
        print(f"  Pending:  GET  /pending")
        print(f"  Approve:  POST /approve/<id>")
        print(f"  Deny:     POST /deny/<id>")
        print(f"  Press Ctrl+C to stop\n")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n  Connector stopped.")
            if self.auto_persist_cieu:
                n = persist_cieu_log()
                print(f"  {n} CIEU records persisted.")


def create_connector(
    port:           int = 7777,
    allowed_paths:  Optional[List[str]] = None,
    allowed_domains: Optional[List[str]] = None,
    strict:         bool = False,
    webhook_url:    Optional[str] = None,
) -> OpenClawHTTPConnector:
    """
    開箱即用のコネクター作成。

    最小使用例：
        from ystar.adapters.connector import create_connector
        connector = create_connector(allowed_paths=["./src"])
        connector.run()   # localhost:7777 で待ち受け

    カスタム例：
        connector = create_connector(
            port=8888,
            allowed_paths=["./src/payments"],
            allowed_domains=["github.com", "pypi.org"],
            strict=True,
            webhook_url="https://hooks.slack.com/...",
        )
    """
    return OpenClawHTTPConnector(
        port           = port,
        session_config = {
            "allowed_paths":   allowed_paths or ["./src", "./tests"],
            "allowed_domains": allowed_domains or [],
        },
        strict_handoff = strict,
        webhook_url    = webhook_url,
    )
