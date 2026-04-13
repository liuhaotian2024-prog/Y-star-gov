# Layer: Prescriptive Governance
"""
ystar.governance.autonomy_driver  —  Autonomy Driver Engine (ADE)
==================================================================

OmissionEngine 的对偶——从 detection 到 direction。

职责：
  1. 根据 priority_brief + obligation backlog + role capabilities 生成 action queue
  2. 检测 agent 偏离 daily_target（OFF_TARGET）
  3. 自动认领无 owner 的 orphan obligations
  4. 提供 pull_next_action() → 返回下一个要做的事

设计原则：
  - Prescriptive (not descriptive)：告诉 agent "该做什么"，不是"做了什么"
  - Goal gradient：daily/weekly/monthly targets 驱动优先级
  - Idle-pull：agent 静默 5min → 自动 pull 不等指令
  - Orphan-claim：无 owner obligation 自动按 role 派

使用方式：
    from ystar.governance.autonomy_driver import AutonomyDriver
    from ystar.governance.omission_store import InMemoryOmissionStore

    driver = AutonomyDriver(
        omission_store=store,
        role_capabilities={"ceo": ["delegation", "coordination"], ...},
        priority_brief_path="reports/priority_brief.md"
    )

    # 获取下一个行动
    action = driver.pull_next_action(agent_id="ceo")

    # 检测是否偏离目标
    if driver.detect_off_target("ceo", current_action="meta-governance tuning"):
        print("WARNING: OFF_TARGET")

    # 认领孤儿义务
    driver.claim_orphan_obligations()
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ystar.governance.omission_store import OmissionStore, InMemoryOmissionStore
from ystar.governance.omission_models import ObligationStatus

_log = logging.getLogger(__name__)


# ── Action Model ──────────────────────────────────────────────────────────────

@dataclass
class Action:
    """单个行动项。"""
    action_id: str
    description: str
    why: str  # 为什么要做
    verify: str  # 如何验证完成
    on_fail: str  # 失败后怎么办
    priority: int = 0  # 越小越优先
    tags: List[str] = field(default_factory=list)
    source: str = "unknown"  # 来源：daily_target / obligation / orphan


@dataclass
class PriorityBrief:
    """优先级简报结构。"""
    today_targets: List[str] = field(default_factory=list)
    this_week_targets: List[str] = field(default_factory=list)
    this_month_targets: List[str] = field(default_factory=list)
    campaign: Optional[str] = None
    day: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Autonomy Driver Engine ────────────────────────────────────────────────────

class AutonomyDriver:
    """
    自驱力引擎 — OmissionEngine 的对偶。

    参数：
        omission_store: OmissionStore (用于读取 obligation backlog)
        role_capabilities: Dict[agent_id, List[capability]] (agent 能力清单)
        priority_brief_path: priority_brief.md 文件路径
    """

    def __init__(
        self,
        omission_store: OmissionStore,
        role_capabilities: Dict[str, List[str]],
        priority_brief_path: str = "reports/priority_brief.md"
    ):
        self.omission_store = omission_store
        self.role_capabilities = role_capabilities
        self.priority_brief_path = Path(priority_brief_path)
        self.action_queues: Dict[str, List[Action]] = {}  # agent_id → action_queue

    def pull_next_action(self, agent_id: str) -> Optional[Action]:
        """
        从 action_queue 取下一个要做的事。

        如果 queue 为空，自动 recompute。
        如果 recompute 后仍为空，返回 None。
        """
        if agent_id not in self.action_queues or not self.action_queues[agent_id]:
            _log.info(f"[ADE] action_queue empty for {agent_id}, recomputing...")
            self.recompute_action_queue(agent_id)

        queue = self.action_queues.get(agent_id, [])
        if not queue:
            _log.warning(f"[ADE] no actions available for {agent_id} after recompute")
            return None

        # 取优先级最高（priority 最小）
        action = queue.pop(0)
        _log.info(f"[ADE] {agent_id} pulled: {action.description[:60]}")
        return action

    def recompute_action_queue(self, agent_id: str):
        """
        重新计算 agent 的 action_queue。

        算法：
          1. 解析 priority_brief → 提取 today_targets
          2. 从 omission_store 读取 pending obligations
          3. 根据 role_capabilities 过滤
          4. 按优先级排序
          5. 生成 Action 对象列表
        """
        brief = self._load_priority_brief()
        actions: List[Action] = []

        # 1. today_targets → actions (priority=0, 最优先)
        for idx, target in enumerate(brief.today_targets):
            actions.append(Action(
                action_id=f"daily_{idx}",
                description=target,
                why="daily_target",
                verify="check completion in DISPATCH.md",
                on_fail="escalate to CEO if blocked",
                priority=0,
                tags=["daily_target"],
                source="priority_brief"
            ))

        # 2. pending obligations → actions (priority=1)
        pending = self._get_pending_obligations(agent_id)
        for obl in pending:
            # ObligationRecord has obligation_type, notes (not description)
            description = obl.notes if obl.notes else f"{obl.obligation_type} for {obl.entity_id}"
            actions.append(Action(
                action_id=obl.obligation_id,
                description=description,
                why=f"obligation {obl.obligation_type}",
                verify="check obligation fulfillment event",
                on_fail="report to CEO",
                priority=1,
                tags=["obligation", obl.obligation_type],
                source="obligation_backlog"
            ))

        # 3. this_week_targets → actions (priority=2)
        for idx, target in enumerate(brief.this_week_targets):
            actions.append(Action(
                action_id=f"weekly_{idx}",
                description=target,
                why="weekly_target",
                verify="check weekly progress",
                on_fail="adjust timeline",
                priority=2,
                tags=["weekly_target"],
                source="priority_brief"
            ))

        # 排序：priority 升序
        actions.sort(key=lambda a: a.priority)
        self.action_queues[agent_id] = actions
        _log.info(f"[ADE] recomputed action_queue for {agent_id}: {len(actions)} actions")

    def detect_off_target(self, agent_id: str, current_action: str) -> bool:
        """
        检测当前 action 是否偏离 daily_target。

        返回：
          - True: OFF_TARGET (当前做的不在 daily_target 内)
          - False: ON_TARGET
        """
        brief = self._load_priority_brief()
        if not brief.today_targets:
            return False  # 没有 target，不算偏离

        # 简单关键词匹配
        current_lower = current_action.lower()
        for target in brief.today_targets:
            target_lower = target.lower()
            # 提取关键词（去除常见词）
            keywords = [w for w in target_lower.split() if len(w) > 3]
            if any(kw in current_lower for kw in keywords):
                return False  # ON_TARGET

        _log.warning(f"[ADE] {agent_id} OFF_TARGET: '{current_action}' not in daily_targets")
        return True

    def claim_orphan_obligations(self):
        """
        自动认领无 owner 的 orphan obligations。

        算法：
          1. 从 omission_store 读取所有 pending obligations
          2. 找出 actor_id="" 的 orphan (ObligationRecord 用 actor_id 不是 owner)
          3. 根据 obligation_type 映射到 role
          4. 更新 obligation.actor_id
        """
        all_obligations = self.omission_store.list_obligations()
        orphans = [o for o in all_obligations if not o.actor_id and o.status == ObligationStatus.PENDING]

        if not orphans:
            _log.info("[ADE] no orphan obligations to claim")
            return

        claimed_count = 0
        for orphan in orphans:
            actor = self._infer_owner(orphan.obligation_type)
            if actor:
                orphan.actor_id = actor
                self.omission_store.update_obligation(orphan)
                claimed_count += 1
                _log.info(f"[ADE] claimed orphan {orphan.obligation_id} → {actor}")

        _log.info(f"[ADE] claimed {claimed_count} orphan obligations")

    def get_action_queue_summary(self, agent_id: str) -> str:
        """返回 action_queue 的摘要（用于 boot_packages.category_11）。"""
        if agent_id not in self.action_queues or not self.action_queues[agent_id]:
            self.recompute_action_queue(agent_id)

        queue = self.action_queues.get(agent_id, [])
        if not queue:
            return "No actions queued"

        lines = []
        for i, action in enumerate(queue[:5], 1):  # 只显示前 5 个
            lines.append(f"  [{i}] {action.description[:60]}")
            lines.append(f"      why: {action.why}, verify: {action.verify[:40]}")
        if len(queue) > 5:
            lines.append(f"  ... and {len(queue) - 5} more")
        return "\n".join(lines)

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _load_priority_brief(self) -> PriorityBrief:
        """从 priority_brief.md 解析出结构化数据。"""
        if not self.priority_brief_path.exists():
            _log.warning(f"[ADE] priority_brief.md not found: {self.priority_brief_path}")
            return PriorityBrief()

        content = self.priority_brief_path.read_text(encoding="utf-8")
        brief = PriorityBrief()

        # 解析 today_targets (简单正则)
        today_match = re.search(r"today_targets:\s*\n((?:  - .+\n?)+)", content, re.MULTILINE)
        if today_match:
            lines = today_match.group(1).strip().split("\n")
            brief.today_targets = [line.strip("- ").strip() for line in lines]

        # 解析 this_week_targets
        week_match = re.search(r"this_week_targets:\s*\n((?:  - .+\n?)+)", content, re.MULTILINE)
        if week_match:
            lines = week_match.group(1).strip().split("\n")
            brief.this_week_targets = [line.strip("- ").strip() for line in lines]

        # 解析 this_month_targets
        month_match = re.search(r"this_month_targets:\s*\n((?:  - .+\n?)+)", content, re.MULTILINE)
        if month_match:
            lines = month_match.group(1).strip().split("\n")
            brief.this_month_targets = [line.strip("- ").strip() for line in lines]

        # 解析 campaign
        campaign_match = re.search(r"campaign:\s*(.+)", content)
        if campaign_match:
            brief.campaign = campaign_match.group(1).strip()

        # 解析 day
        day_match = re.search(r"day:\s*(\d+)", content)
        if day_match:
            brief.day = int(day_match.group(1))

        return brief

    def _get_pending_obligations(self, agent_id: str) -> List[Any]:
        """从 omission_store 读取 pending obligations。"""
        # Use list_obligations with actor_id filter
        return self.omission_store.list_obligations(
            actor_id=agent_id,
            status=ObligationStatus.PENDING
        )

    def _infer_owner(self, obligation_type: str) -> Optional[str]:
        """根据 obligation_type 推断 owner（简单启发式）。"""
        # 基于 obligation_type 关键词映射
        type_lower = obligation_type.lower()
        if any(kw in type_lower for kw in ["ceo", "delegation", "coordination"]):
            return "ceo"
        elif any(kw in type_lower for kw in ["cto", "bug", "test", "code"]):
            return "cto"
        elif any(kw in type_lower for kw in ["cmo", "content", "blog", "article"]):
            return "cmo"
        elif any(kw in type_lower for kw in ["cso", "sales", "lead"]):
            return "cso"
        elif any(kw in type_lower for kw in ["cfo", "finance", "token"]):
            return "cfo"
        elif "kernel" in type_lower:
            return "eng-kernel"
        elif "governance" in type_lower:
            return "eng-governance"
        elif "platform" in type_lower:
            return "eng-platform"
        elif "domains" in type_lower:
            return "eng-domains"
        else:
            return None  # 无法推断


# ── Factory ───────────────────────────────────────────────────────────────────

def create_autonomy_driver(
    omission_store: Optional[OmissionStore] = None,
    priority_brief_path: str = "reports/priority_brief.md"
) -> AutonomyDriver:
    """工厂函数：快速创建 AutonomyDriver 实例。"""
    if omission_store is None:
        omission_store = InMemoryOmissionStore()

    # 默认 role_capabilities
    role_capabilities = {
        "ceo": ["delegation", "coordination", "reporting", "board_interface"],
        "cto": ["code", "test", "architecture", "git", "debug"],
        "cmo": ["content", "blog", "marketing", "social_media"],
        "cso": ["sales", "lead_gen", "crm", "patent"],
        "cfo": ["finance", "pricing", "token", "budget"],
        "eng-kernel": ["kernel", "causal_engine", "pulse", "meta_learning"],
        "eng-governance": ["governance", "omission_engine", "intervention", "rules"],
        "eng-platform": ["platform", "mcp", "cli", "adapters"],
        "eng-domains": ["domains", "domain_packs", "industry_rules"],
    }

    return AutonomyDriver(
        omission_store=omission_store,
        role_capabilities=role_capabilities,
        priority_brief_path=priority_brief_path
    )
