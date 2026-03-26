# ystar/integrations/openclaw.py  —  OpenClaw Production Integration
# Copyright (C) 2026 Haotian Liu — MIT License
"""
OpenClaw 生产接入连接器  v0.41.0

两种接入模式：

  模式A  OpenClawConnector（主动拉取 / SSE 流）
    连接 OpenClaw runtime 的 HTTP endpoint，实时拉取事件流，
    每个事件经 Y* enforce() 判断后把决策注回 OpenClaw。

  模式B  WebhookConnector（被动接收）
    启动本地 HTTP webhook 服务器，
    让 OpenClaw 主动把事件 POST 过来，Y* 实时响应。

与仿真的对比测试（证明接入价值）：

    from ystar.integrations import WorkloadRunner
    from ystar.integrations.openclaw import OpenClawConnector
    from ystar.integrations.simulation import SimulatedWorkloadConnector

    sim  = WorkloadRunner.run(SimulatedWorkloadConnector(config))
    real = WorkloadRunner.run(OpenClawConnector(config))
    delta = real.delta_from(sim)
    print(delta)   # 证明生产接入的额外价值
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Generator, Optional

from ystar.integrations.base import (
    EventStreamConnector,
    IntegrationHealth,
    LiveWorkloadConfig,
    WorkloadEvent,
)


# ══════════════════════════════════════════════════════════════════════
# 模式A：主动拉取（SSE / polling）
# ══════════════════════════════════════════════════════════════════════

class OpenClawConnector(EventStreamConnector):
    """
    OpenClaw 主动拉取连接器。

    连接 OpenClaw runtime 的 HTTP endpoint，以 SSE 或轮询方式
    拉取事件流，每个事件经 Y* 处理后把决策注回 OpenClaw。

    配置字段（LiveWorkloadConfig）：
      endpoint_url  — OpenClaw events endpoint，如 http://localhost:9000/events
      auth_token    — Bearer token（可选）
      source_name   — 来源标识，默认 "openclaw"

    示例::

        from ystar.integrations.base import LiveWorkloadConfig
        from ystar.integrations.openclaw import OpenClawConnector
        from ystar.integrations import WorkloadRunner

        config = LiveWorkloadConfig(
            endpoint_url="http://localhost:9000/events",
            auth_token="my-token",
            source_name="openclaw",
        )
        result = WorkloadRunner.run(OpenClawConnector(config))
    """

    # OpenClaw 事件字段 → WorkloadEvent 字段的映射
    _FIELD_MAP = {
        "event_type":    "action",
        "agent_id":      "agent_id",
        "session_id":    "session_id",
        "file_path":     "resource",
        "url":           "resource",
        "command":       "resource",
        "task_ticket_id":"ticket_id",
    }

    def connect(self) -> bool:
        """建立与 OpenClaw endpoint 的连接，验证可达性。"""
        url = self.config.endpoint_url
        if not url:
            self._health.error_message = "endpoint_url not configured"
            return False
        try:
            req = urllib.request.Request(
                url + "/health",
                headers=self._auth_headers(),
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self._health.connected = resp.status == 200
                return self._health.connected
        except urllib.error.URLError as e:
            # endpoint 不可达时退化为 polling 模式，仍标记为已连接
            self._health.connected = True
            self._health.error_message = f"health check failed ({e}), using polling"
            return True
        except Exception as e:
            self._health.error_message = str(e)
            return False

    def stream_events(self) -> Generator[WorkloadEvent, None, None]:
        """
        从 OpenClaw endpoint 拉取事件流。

        优先尝试 SSE（text/event-stream），降级到 1s 轮询。
        每个 WorkloadEvent 都带有原始 OpenClaw 事件数据（extra 字段）。
        """
        url = self.config.endpoint_url
        if not url:
            return

        headers = self._auth_headers()
        headers["Accept"] = "text/event-stream, application/json"
        poll_interval = getattr(self._config, "poll_interval_seconds", 1.0)

        while self._health.connected:
            try:
                req = urllib.request.Request(
                    url + "/events",
                    headers=headers,
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    if "event-stream" in content_type:
                        yield from self._parse_sse(resp)
                    else:
                        data = json.loads(resp.read().decode())
                        events = data if isinstance(data, list) else [data]
                        for raw in events:
                            ev = self._translate(raw)
                            if ev:
                                yield ev
            except urllib.error.URLError:
                time.sleep(poll_interval)
            except StopIteration:
                break

    def disconnect(self) -> None:
        self._health.connected = False

    def send_decision(self, event: WorkloadEvent,
                      decision: str, rationale: str = "") -> bool:
        """把 Y* 的裁决注回 OpenClaw。"""
        url = self.config.endpoint_url
        if not url:
            return False
        payload = json.dumps({
            "event_id":  event.extra.get("event_id", ""),
            "session_id": event.session_id,
            "agent_id":   event.agent_id,
            "decision":   decision,      # "allow" / "deny" / "escalate"
            "rationale":  rationale,
            "source":     "ystar",
        }).encode()
        try:
            req = urllib.request.Request(
                url + "/decisions",
                data=payload,
                headers={**self._auth_headers(),
                         "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status in (200, 201, 202)
        except Exception:
            return False

    # ── helpers ───────────────────────────────────────────────────

    def _auth_headers(self) -> dict:
        token = getattr(self._config, "auth_token", None)
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _parse_sse(self, resp) -> Generator[WorkloadEvent, None, None]:
        """Parse Server-Sent Events stream."""
        buf = ""
        for chunk in iter(lambda: resp.read(1024).decode(errors="replace"), ""):
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                for line in block.splitlines():
                    if line.startswith("data:"):
                        try:
                            raw = json.loads(line[5:].strip())
                            ev = self._translate(raw)
                            if ev:
                                yield ev
                        except json.JSONDecodeError:
                            pass

    def _translate(self, raw: dict) -> Optional[WorkloadEvent]:
        """OpenClaw 事件 → WorkloadEvent。"""
        event_type = raw.get("event_type", raw.get("action", "unknown"))
        # 把 OpenClaw 的各路径/命令/URL 参数归入 payload
        payload = {k: v for k, v in raw.items()
                   if k not in ("event_type", "agent_id", "session_id",
                                "timestamp", "parent_agent_id", "child_agent_id",
                                "task_ticket_id")}
        return WorkloadEvent(
            event_type      = event_type,
            agent_id        = raw.get("agent_id", "unknown"),
            session_id      = raw.get("session_id", ""),
            timestamp       = raw.get("timestamp", time.time()),
            parent_agent_id = raw.get("parent_agent_id"),
            child_agent_id  = raw.get("child_agent_id"),
            task_ticket_id  = raw.get("task_ticket_id"),
            payload         = payload,
            source          = "openclaw",
        )


# ══════════════════════════════════════════════════════════════════════
# 模式B：被动 Webhook 接收
# ══════════════════════════════════════════════════════════════════════

class WebhookConnector(EventStreamConnector):
    """
    Y* Webhook 服务器 — 让 OpenClaw 把事件 POST 到本地。

    启动一个轻量 HTTP 服务器监听指定端口。
    OpenClaw 配置 webhook URL 指向此服务器，
    每个事件以 JSON 形式 POST 过来，Y* 同步返回 allow/deny 决策。

    配置字段（LiveWorkloadConfig）：
      extra.port  — 监听端口，默认 8765
      extra.path  — 路径，默认 /ystar/events

    示例（OpenClaw 侧配置）：

        ystar_webhook_url = "http://localhost:8765/ystar/events"

    示例（Y* 侧启动）::

        config = LiveWorkloadConfig(
            source_name="webhook",
            extra={"port": 8765, "path": "/ystar/events"},
        )
        result = WorkloadRunner.run(WebhookConnector(config))
    """

    def __init__(self, config: LiveWorkloadConfig) -> None:
        super().__init__(config)
        self._port   = int(config.extra.get("port", 8765))
        self._path   = config.extra.get("path", "/ystar/events")
        self._queue: list[WorkloadEvent] = []
        self._lock   = threading.Lock()
        self._server: Optional[HTTPServer] = None

    def connect(self) -> bool:
        """启动 HTTP webhook 服务器。"""
        connector = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != connector._path:
                    self.send_response(404); self.end_headers(); return
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    raw = json.loads(body)
                    ev = connector._translate(raw)
                    if ev:
                        with connector._lock:
                            connector._queue.append(ev)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"received"}')
                except Exception as e:
                    self.send_response(400); self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())

            def log_message(self, *_):
                pass  # suppress default logging

        try:
            self._server = HTTPServer(("0.0.0.0", self._port), Handler)
            t = threading.Thread(target=self._server.serve_forever, daemon=True)
            t.start()
            self._health.connected = True
            return True
        except OSError as e:
            self._health.error_message = str(e)
            return False

    def stream_events(self) -> Generator[WorkloadEvent, None, None]:
        """从 webhook 队列产出事件。"""
        while self._health.connected:
            with self._lock:
                if self._queue:
                    yield self._queue.pop(0)
                    continue
            time.sleep(0.05)

    def disconnect(self) -> None:
        self._health.connected = False
        if self._server:
            self._server.shutdown()

    def _translate(self, raw: dict) -> Optional[WorkloadEvent]:
        event_type = raw.get("event_type", raw.get("action", "unknown"))
        payload = {k: v for k, v in raw.items()
                   if k not in ("event_type", "agent_id", "session_id",
                                "timestamp", "parent_agent_id", "child_agent_id",
                                "task_ticket_id")}
        return WorkloadEvent(
            event_type      = event_type,
            agent_id        = raw.get("agent_id", "unknown"),
            session_id      = raw.get("session_id", ""),
            timestamp       = raw.get("timestamp", time.time()),
            parent_agent_id = raw.get("parent_agent_id"),
            child_agent_id  = raw.get("child_agent_id"),
            task_ticket_id  = raw.get("task_ticket_id"),
            payload         = payload,
            source          = "webhook",
        )
