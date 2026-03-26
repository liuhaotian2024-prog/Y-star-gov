"""
ystar.products.report_delivery  —  Multi-Channel Report Delivery
=================================================================
v0.40.0  (移入 products/ 层，3-C 架构归位)

正确归属：报告交付是 Operator Product 层的功能，不属于适配层。
适配层（adapters/report_delivery.py）保留为向后兼容的 shim。

"""

from __future__ import annotations

import json
import smtplib
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Callable, Dict, List, Optional

from ystar.governance.reporting import Report, ReportEngine


# ══════════════════════════════════════════════════════════════════════════════
# Channel 配置数据类
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EmailConfig:
    """SMTP email 配置。"""
    to:            List[str]
    smtp_host:     str      = "localhost"
    smtp_port:     int      = 587
    username:      str      = ""
    password:      str      = ""
    from_addr:     str      = "ystar@localhost"
    use_tls:       bool     = True
    subject_prefix:str      = "[Y* Report]"

    # 可选：Sendgrid-compatible HTTP API（优先于 SMTP）
    api_url:       Optional[str] = None
    api_key:       Optional[str] = None


@dataclass
class WebhookConfig:
    """Webhook 配置（兼容 Slack / Teams / 自定义）。"""
    url:           str
    format:        str      = "json"   # json / markdown / slack / teams
    headers:       Dict[str, str] = field(default_factory=dict)
    timeout_secs:  float    = 10.0

    # Slack-specific：可选 channel / username 覆盖
    slack_channel: Optional[str] = None
    slack_username:str      = "Y* ReportBot"
    slack_icon:    str      = ":robot_face:"


@dataclass
class OpenClawInjectionConfig:
    """
    OpenClaw injection 配置。
    报告会被压缩成一个 GovernanceEvent 注入 omission adapter 的事件流，
    让 agent 可以在自己的执行链中"看到"自己的治理状态。
    """
    adapter:       Any               # OmissionAdapter
    entity_id:     str = "ystar_report_channel"
    actor_id:      str = "ystar_report_engine"
    include_kpis:  bool = True
    include_violations: bool = True
    max_violations_inline: int = 5   # 摘要里最多展示几条 violation


@dataclass
class FileConfig:
    """文件输出配置。"""
    path:         str
    format:       str  = "markdown"   # markdown / json
    append_date:  bool = True          # path 里自动加日期后缀


# ══════════════════════════════════════════════════════════════════════════════
# 渠道实现
# ══════════════════════════════════════════════════════════════════════════════

class _EmailChannel:
    def __init__(self, cfg: EmailConfig) -> None:
        self.cfg = cfg

    def send(self, report: Report) -> DeliveryResult:
        cfg = self.cfg
        subject = f"{cfg.subject_prefix} {report.report_type.upper()} — {report.period_label}"
        body_md  = report.to_markdown()
        body_html = _md_to_html(body_md)

        # Try API first, fall back to SMTP
        if cfg.api_url and cfg.api_key:
            return self._send_api(subject, body_md, body_html)
        return self._send_smtp(subject, body_md, body_html)

    def _send_smtp(self, subject, body_md, body_html) -> "DeliveryResult":
        cfg = self.cfg
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = cfg.from_addr
            msg["To"]      = ", ".join(cfg.to)
            msg.attach(MIMEText(body_md, "plain", "utf-8"))
            msg.attach(MIMEText(body_html, "html", "utf-8"))

            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as server:
                if cfg.use_tls:
                    server.starttls()
                if cfg.username:
                    server.login(cfg.username, cfg.password)
                server.sendmail(cfg.from_addr, cfg.to, msg.as_string())

            return DeliveryResult(channel="email", success=True,
                                  detail=f"Sent to {cfg.to}")
        except Exception as e:
            return DeliveryResult(channel="email", success=False, error=str(e))

    def _send_api(self, subject, body_md, body_html) -> "DeliveryResult":
        cfg = self.cfg
        try:
            payload = json.dumps({
                "to": cfg.to,
                "subject": subject,
                "text": body_md,
                "html": body_html,
            }).encode()
            req = urllib.request.Request(
                cfg.api_url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {cfg.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=15)
            return DeliveryResult(channel="email_api", success=True,
                                  detail=f"Sent via API to {cfg.to}")
        except Exception as e:
            return DeliveryResult(channel="email_api", success=False, error=str(e))


class _WebhookChannel:
    def __init__(self, cfg: WebhookConfig) -> None:
        self.cfg = cfg

    def send(self, report: Report) -> "DeliveryResult":
        cfg = self.cfg
        try:
            payload = self._build_payload(report)
            data    = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json", **cfg.headers}
            req = urllib.request.Request(
                cfg.url, data=data, headers=headers, method="POST"
            )
            urllib.request.urlopen(req, timeout=cfg.timeout_secs)
            return DeliveryResult(channel="webhook", success=True,
                                  detail=cfg.url)
        except Exception as e:
            return DeliveryResult(channel="webhook", success=False, error=str(e))

    def _build_payload(self, report: Report) -> dict:
        cfg = self.cfg
        fmt = cfg.format

        if fmt == "slack":
            return self._slack_payload(report)
        elif fmt == "teams":
            return self._teams_payload(report)
        elif fmt == "markdown":
            return {"text": report.to_markdown()}
        else:
            return report.to_dict()   # raw JSON

    def _slack_payload(self, report: Report) -> dict:
        """Slack Block Kit payload。"""
        d = report.to_dict()
        kpis = d.get("kpis", {})

        # 健康状态颜色
        vr = kpis.get("omission_detection_rate", 0)
        er = kpis.get("obligation_expiry_rate", 0)
        color = "#36a64f" if er < 0.1 else ("#ff9900" if er < 0.3 else "#ff0000")

        kpi_lines = "\n".join(
            f"  • {k.replace('_', ' ')}: *{v:.1%}*"
            for k, v in list(kpis.items())[:6]
        )
        omit = d.get("omissions", {})
        violation_summary = (
            f"{omit.get('omission_total_violations', 0)} violations | "
            f"{omit.get('omission_recovered_count', 0)} recovered"
        )
        text = (
            f":chart_with_upwards_trend: *Y* {report.report_type.upper()} REPORT*\n"
            f"*{report.period_label}* | v{report.integrity.ystar_version}\n\n"
            f"*KPIs:*\n{kpi_lines}\n\n"
            f"*Omissions:* {violation_summary}"
        )
        payload: dict = {
            "username": self.cfg.slack_username,
            "icon_emoji": self.cfg.slack_icon,
            "attachments": [{
                "color": color,
                "text": text,
                "mrkdwn_in": ["text"],
            }],
        }
        if self.cfg.slack_channel:
            payload["channel"] = self.cfg.slack_channel
        return payload

    def _teams_payload(self, report: Report) -> dict:
        """Microsoft Teams Adaptive Card payload。"""
        kpis = report.to_dict().get("kpis", {})
        facts = [
            {"name": k.replace("_", " "), "value": f"{v:.1%}"}
            for k, v in list(kpis.items())[:6]
        ]
        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": "0076D7",
            "summary": f"Y* {report.report_type} report",
            "sections": [{
                "activityTitle": f"Y* {report.report_type.upper()} REPORT",
                "activitySubtitle": (
                    f"{report.period_label} | v{report.integrity.ystar_version}"
                ),
                "facts": facts,
                "markdown": True,
            }],
        }


class _OpenClawInjectionChannel:
    """
    把报告注入 OpenClaw agent 事件流。

    这是最独特的交付方式：
    agent 在执行过程中收到自己的治理报告，可以据此调整行为。
    报告被压缩成一个 GovernanceEvent（event_type=INTERVENTION_PULSE 扩展类型）
    注入 omission_adapter 的 engine，对 agent 完全透明可查。
    """
    def __init__(self, cfg: OpenClawInjectionConfig) -> None:
        self.cfg = cfg

    def send(self, report: Report) -> "DeliveryResult":
        cfg = self.cfg
        try:
            from ystar.governance.omission_models import GovernanceEvent
            payload = self._build_payload(report)
            ev = GovernanceEvent(
                event_type  = "governance_report",
                entity_id   = cfg.entity_id,
                actor_id    = cfg.actor_id,
                ts          = time.time(),
                payload     = payload,
                source      = "report_delivery",
            )
            cfg.adapter.engine.store.add_event(ev)
            return DeliveryResult(
                channel="openclaw_injection",
                success=True,
                detail=f"Injected into entity_id={cfg.entity_id}",
            )
        except Exception as e:
            return DeliveryResult(channel="openclaw_injection",
                                  success=False, error=str(e))

    def _build_payload(self, report: Report) -> dict:
        cfg = self.cfg
        d = report.to_dict()
        payload: dict = {
            "report_type":   report.report_type,
            "period_label":  report.period_label,
            "ystar_version": report.integrity.ystar_version,
            "confidence":    report.integrity.report_confidence_level,
        }
        if cfg.include_kpis:
            payload["kpis"] = d.get("kpis", {})
        if cfg.include_violations:
            violations = d.get("omissions", {}).get("by_omission_type", {})
            payload["top_violations"] = dict(
                list(violations.items())[:cfg.max_violations_inline]
            )
            payload["broken_chains"] = d.get("omissions", {}).get("broken_chains", 0)
        return payload


class _FileChannel:
    def __init__(self, cfg: FileConfig) -> None:
        self.cfg = cfg

    def send(self, report: Report) -> "DeliveryResult":
        import datetime
        cfg = self.cfg
        path = cfg.path
        if cfg.append_date:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dot = path.rfind(".")
            if dot != -1:
                path = path[:dot] + f"_{ts}" + path[dot:]
            else:
                path = f"{path}_{ts}"
        try:
            text = report.to_json() if cfg.format == "json" else report.to_markdown()
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return DeliveryResult(channel="file", success=True, detail=path)
        except Exception as e:
            return DeliveryResult(channel="file", success=False, error=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# DeliveryResult
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DeliveryResult:
    channel:  str
    success:  bool
    detail:   str = ""
    error:    str = ""
    sent_at:  float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "channel": self.channel, "success": self.success,
            "detail": self.detail, "error": self.error,
            "sent_at": self.sent_at,
        }


# ══════════════════════════════════════════════════════════════════════════════
# DeliveryManager — 主入口
# ══════════════════════════════════════════════════════════════════════════════

class DeliveryManager:
    """
    多渠道报告交付管理器。

    一个 DeliveryManager 可以同时配置多个渠道，
    deliver() 时并行向所有渠道发送。
    """

    def __init__(self, report_engine: ReportEngine) -> None:
        self.report_engine = report_engine
        self._channels: List[Any] = []
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._delivery_log: List[dict] = []

    # ── 渠道注册 ──────────────────────────────────────────────────────────────

    def add_email(
        self,
        to: List[str],
        smtp_host: str = "localhost",
        smtp_port: int = 587,
        username: str = "",
        password: str = "",
        from_addr: str = "ystar@localhost",
        use_tls: bool = True,
        subject_prefix: str = "[Y* Report]",
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> "DeliveryManager":
        cfg = EmailConfig(
            to=to, smtp_host=smtp_host, smtp_port=smtp_port,
            username=username, password=password, from_addr=from_addr,
            use_tls=use_tls, subject_prefix=subject_prefix,
            api_url=api_url, api_key=api_key,
        )
        self._channels.append(_EmailChannel(cfg))
        return self  # 链式调用

    def add_webhook(
        self,
        url: str,
        format: str = "json",   # json / markdown / slack / teams
        headers: Optional[Dict[str, str]] = None,
        timeout_secs: float = 10.0,
        slack_channel: Optional[str] = None,
    ) -> "DeliveryManager":
        cfg = WebhookConfig(
            url=url, format=format,
            headers=headers or {},
            timeout_secs=timeout_secs,
            slack_channel=slack_channel,
        )
        self._channels.append(_WebhookChannel(cfg))
        return self

    def add_openclaw_injection(
        self,
        adapter: Any,
        entity_id: str = "ystar_report_channel",
        actor_id: str = "ystar_report_engine",
        include_kpis: bool = True,
        include_violations: bool = True,
    ) -> "DeliveryManager":
        cfg = OpenClawInjectionConfig(
            adapter=adapter, entity_id=entity_id, actor_id=actor_id,
            include_kpis=include_kpis, include_violations=include_violations,
        )
        self._channels.append(_OpenClawInjectionChannel(cfg))
        return self

    def add_file(
        self,
        path: str,
        format: str = "markdown",
        append_date: bool = True,
    ) -> "DeliveryManager":
        cfg = FileConfig(path=path, format=format, append_date=append_date)
        self._channels.append(_FileChannel(cfg))
        return self

    # ── 立即发送 ─────────────────────────────────────────────────────────────

    def deliver(self, report: Report) -> List[DeliveryResult]:
        """向所有已配置渠道发送报告，返回每个渠道的结果。"""
        results = []
        for channel in self._channels:
            result = channel.send(report)
            results.append(result)
            self._delivery_log.append({
                **result.to_dict(),
                "report_type":  report.report_type,
                "period_label": report.period_label,
            })
        return results

    def deliver_baseline(self) -> List[DeliveryResult]:
        return self.deliver(self.report_engine.baseline_report())

    def deliver_daily(self, since: Optional[float] = None) -> List[DeliveryResult]:
        return self.deliver(self.report_engine.daily_report(since=since))

    # ── 定时发送 ─────────────────────────────────────────────────────────────

    def schedule_daily(
        self,
        hour: int = 9,
        minute: int = 0,
        report_type: str = "daily",    # daily / baseline
    ) -> "DeliveryManager":
        """
        启动后台线程，每天在指定时间发送报告。
        非阻塞，daemon thread（主进程退出时自动停止）。
        """
        self._stop_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            args=(hour, minute, report_type),
            name="ystar-report-scheduler",
            daemon=True,
        )
        self._scheduler_thread.start()
        return self

    def schedule_interval(
        self,
        interval_secs: float,
        report_type: str = "daily",
    ) -> "DeliveryManager":
        """每隔 interval_secs 秒发送一次报告（适合高频场景或测试）。"""
        self._stop_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._interval_loop,
            args=(interval_secs, report_type),
            name="ystar-report-interval",
            daemon=True,
        )
        self._scheduler_thread.start()
        return self

    def stop_schedule(self) -> None:
        self._stop_event.set()
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5.0)

    # ── 附加到 OmissionScanner ───────────────────────────────────────────────

    def attach_to_scanner(
        self,
        scanner: Any,          # OmissionScanner
        on_violation: bool = True,   # 每次发现 violation 时发送
        on_escalation: bool = True,  # 每次发现 escalation 时发送
        report_type: str = "daily",
    ) -> "DeliveryManager":
        """
        将报告发送挂载到 OmissionScanner 的回调上。
        当 scanner 扫到 violation / escalation 时自动触发报告发送。

        这样的效果：
          scan() → violation → on_violation callback → deliver_daily()
        """
        if on_violation:
            original_viol = scanner.on_violation

            def _viol_with_report(v):
                original_viol(v)
                try:
                    report = (self.report_engine.daily_report()
                              if report_type == "daily"
                              else self.report_engine.baseline_report())
                    self.deliver(report)
                except Exception:
                    pass

            scanner.on_violation = _viol_with_report

        if on_escalation:
            original_esc = scanner.on_escalation

            def _esc_with_report(v):
                original_esc(v)
                try:
                    report = (self.report_engine.daily_report()
                              if report_type == "daily"
                              else self.report_engine.baseline_report())
                    self.deliver(report)
                except Exception:
                    pass

            scanner.on_escalation = _esc_with_report

        return self

    # ── 交付日志 ─────────────────────────────────────────────────────────────

    def delivery_log(self) -> List[dict]:
        """返回所有已发送记录。"""
        return list(self._delivery_log)

    def last_delivery_status(self) -> dict:
        """最近一次各渠道发送结果。"""
        if not self._delivery_log:
            return {}
        # Group by channel, take latest
        latest: dict = {}
        for entry in reversed(self._delivery_log):
            c = entry["channel"]
            if c not in latest:
                latest[c] = entry
        return latest

    # ── 私有：调度循环 ────────────────────────────────────────────────────────

    def _scheduler_loop(self, hour: int, minute: int, report_type: str) -> None:
        import datetime
        while not self._stop_event.is_set():
            now = datetime.datetime.now()
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += datetime.timedelta(days=1)
            wait_secs = (next_run - now).total_seconds()
            self._stop_event.wait(timeout=wait_secs)
            if self._stop_event.is_set():
                break
            try:
                if report_type == "daily":
                    self.deliver_daily()
                else:
                    self.deliver_baseline()
            except Exception:
                pass

    def _interval_loop(self, interval_secs: float, report_type: str) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=interval_secs)
            if self._stop_event.is_set():
                break
            try:
                if report_type == "daily":
                    self.deliver_daily()
                else:
                    self.deliver_baseline()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════════════

def _md_to_html(md: str) -> str:
    """
    简单 Markdown → HTML 转换（不依赖外部库）。
    用于 email HTML part。
    """
    lines = []
    for line in md.split("\n"):
        if line.startswith("# "):
            lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("| ") and "|----" not in line:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            td = "".join(f"<td style='padding:4px 8px'>{c}</td>" for c in cells)
            lines.append(f"<tr>{td}</tr>")
        elif "|----" in line:
            lines.append("<tbody>")
        elif line.startswith("---"):
            lines.append("<hr/>")
        elif line.strip() == "":
            lines.append("<br/>")
        else:
            import re
            line = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", line)
            line = re.sub(r"\*(.*?)\*",   r"<em>\1</em>",           line)
            line = re.sub(r"`(.*?)`",     r"<code>\1</code>",       line)
            lines.append(f"<p style='margin:2px 0'>{line}</p>")
    html = "\n".join(lines)
    return f"""<!DOCTYPE html><html><body style='font-family:monospace;max-width:800px'>
{html}
</body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
# 快速设置工厂
# ══════════════════════════════════════════════════════════════════════════════

def create_delivery_manager(
    report_engine: ReportEngine,
    *,
    # Email
    email_to: Optional[List[str]] = None,
    smtp_host: str = "localhost",
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_pass: str = "",
    smtp_from: str = "ystar@localhost",
    # Slack
    slack_webhook_url: Optional[str] = None,
    slack_channel: Optional[str] = None,
    # Teams
    teams_webhook_url: Optional[str] = None,
    # Generic webhook
    webhook_url: Optional[str] = None,
    webhook_format: str = "json",
    # OpenClaw injection
    openclaw_adapter: Optional[Any] = None,
    # File
    report_file_path: Optional[str] = None,
    report_file_format: str = "markdown",
) -> DeliveryManager:
    """
    一行创建配置好的 DeliveryManager。

    示例：
        dm = create_delivery_manager(
            report_engine   = engine,
            email_to        = ["ops@company.com"],
            slack_webhook_url = "https://hooks.slack.com/...",
            openclaw_adapter  = adapter,
        )
        dm.schedule_daily(hour=9)
    """
    dm = DeliveryManager(report_engine)

    if email_to:
        dm.add_email(
            to=email_to, smtp_host=smtp_host, smtp_port=smtp_port,
            username=smtp_user, password=smtp_pass, from_addr=smtp_from,
        )
    if slack_webhook_url:
        dm.add_webhook(url=slack_webhook_url, format="slack",
                       slack_channel=slack_channel)
    if teams_webhook_url:
        dm.add_webhook(url=teams_webhook_url, format="teams")
    if webhook_url:
        dm.add_webhook(url=webhook_url, format=webhook_format)
    if openclaw_adapter:
        dm.add_openclaw_injection(adapter=openclaw_adapter)
    if report_file_path:
        dm.add_file(path=report_file_path, format=report_file_format)

    return dm
