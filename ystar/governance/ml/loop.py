"""
ystar.governance.ml.loop — YStarLoop
v0.41: 从 metalearning.py 拆分，原始行 1553-1831。
"""
from __future__ import annotations
import time, json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from ystar.kernel.dimensions import IntentContract
from ystar.kernel.engine import Violation

class YStarLoop:
    """
    自适应闭环工作流接口（v0.10.0新增）。

    把 record → tighten → feedback → adapt 组装成标准使用模式。
    解决了零件存在但使用方式不清晰的问题。

    用法：
        loop = YStarLoop()

        # Record call history
        loop.record(CallRecord(seq=0, func_name="deploy", ...))

        # Run one tightening cycle
        result = loop.tighten()
        print(result.contract_additions)
        print(result.explain_diagnosis())

        # After applying contract_additions to the actual code, continue recording history...
        # On the next tighten() call, the coefficients are automatically adjusted based on the last cycle's effectiveness.

    状态字段（全部公开可检查）：
        coefficients:    当前自适应系数
        history:         完整调用记录
        last_diagnosis:  上次 tighten() 的 diagnosis
        last_result:     上次 tighten() 的 MetalearnResult
        cycle_count:     已完成的收紧周期数
    """

    def __init__(
        self,
        initial_coefficients: Optional[AdaptiveCoefficients] = None,
        base_contract:        Optional[IntentContract]        = None,
    ):
        """
        Args:
            initial_coefficients: 初始系数（None = V08先验）
            base_contract:        现有合约（用于FP率计算）
        """
        self.coefficients:    AdaptiveCoefficients   = (
            initial_coefficients if initial_coefficients is not None
            else AdaptiveCoefficients()
        )
        self.base_contract:   Optional[IntentContract] = base_contract
        self.history:         List[CallRecord]          = []
        self.last_diagnosis:  Dict[str, int]            = {}
        self.last_result:     Optional[MetalearnResult] = None
        self.cycle_count:     int                       = 0

    def record(self, record: CallRecord) -> None:
        """
        记录一次函数调用。

        Args:
            record: CallRecord（包含params/result/violations，
                    ideally也包含intent_contract和system_state）
        """
        self.history.append(record)

    def record_many(self, records: List[CallRecord]) -> None:
        """批量记录调用历史。"""
        self.history.extend(records)

    def tighten(self) -> MetalearnResult:
        """
        运行一次收紧周期。

        步骤：
          1. 从当前历史和自适应系数推导 NormativeObjective
          2. 运行 learn()，得到 MetalearnResult
          3. 如果有上次的 diagnosis，记录反馈并更新系数
          4. 更新 last_diagnosis、last_result、cycle_count

        Returns:
            MetalearnResult — 包含 contract_additions、diagnosis、
                             objective、quality

        注意：
            tighten() 不自动应用 contract_additions，用户需要手动把
            result.contract_additions 集成到实际的函数装饰器中。
            这是刻意的设计：Y* 是翻译层，执行决策属于用户。
        """
        # Step 1: Derive the objective function (using adaptive coefficients)
        objective = derive_objective_adaptive(self.history, self.coefficients)

        # Step 2: Run learn()
        result = learn(
            self.history,
            base_contract = self.base_contract,
            objective     = objective,
        )

        # Step 3: Record feedback and update coefficients (requires the previous diagnosis as "before")
        if self.last_diagnosis:
            feedback = RefinementFeedback(
                objective_used   = objective,
                diagnosis_before = dict(self.last_diagnosis),
                diagnosis_after  = dict(result.diagnosis),
                history_size     = len(self.history),
            )
            self.coefficients = update_coefficients(feedback, self.coefficients)

        # Step 4: Update state
        self.last_diagnosis = dict(result.diagnosis)
        self.last_result    = result
        self.cycle_count   += 1

        return result

    def status(self) -> str:
        """
        当前循环状态的人类可读摘要。
        """
        lines = [
            f"YStarLoop 状态:",
            f"  周期数:     {self.cycle_count}",
            f"  历史记录:   {len(self.history)} 条",
            f"  系数:       {self.coefficients}",
        ]
        if self.last_result:
            lines.append(f"  上次收紧:   {self.last_result.contract_additions}")
            if self.last_result.quality:
                lines.append(f"  合约质量:   {self.last_result.quality}")
        if self.last_diagnosis:
            diag_summary = ", ".join(
                f"{k.split('_')[0]}={v}"
                for k, v in self.last_diagnosis.items()
                if v > 0
            )
            lines.append(f"  诊断分布:   {diag_summary}")
        return "\n".join(lines)

    def reset_history(self) -> None:
        """
        清空调用历史（保留系数）。
        适用于：滑动窗口模式，只保留最近N条记录的场景。
        """
        self.history.clear()
        self.last_diagnosis = {}

    def snapshot(self) -> Dict[str, Any]:
        """
        导出当前状态快照（用于持久化）。

        Returns:
            dict — 包含 coefficients 字段值和 cycle_count
        """
        from dataclasses import asdict
        return {
            "coefficients": {
                "high_severity_pen":  self.coefficients.high_severity_pen,
                "high_density_pen":   self.coefficients.high_density_pen,
                "cat_a_bonus":        self.coefficients.cat_a_bonus,
                "observation_count":  self.coefficients.observation_count,
                "total_history_seen": self.coefficients.total_history_seen,
            },
            "cycle_count":   self.cycle_count,
            "history_size":  len(self.history),
        }

    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Any]) -> "YStarLoop":
        """从快照恢复状态（不包含 history，需要重新加载）。"""
        coeffs_data = snapshot.get("coefficients", {})
        coeffs = AdaptiveCoefficients(
            high_severity_pen  = coeffs_data.get("high_severity_pen",  0.03),
            high_density_pen   = coeffs_data.get("high_density_pen",   0.02),
            cat_a_bonus        = coeffs_data.get("cat_a_bonus",        0.02),
            observation_count  = coeffs_data.get("observation_count",  0),
            total_history_seen = coeffs_data.get("total_history_seen", 0),
        )
        loop = cls(initial_coefficients=coeffs)
        loop.cycle_count = snapshot.get("cycle_count", 0)
        return loop



# ── Convenience: learn from JSONL ledger ─────────────────────────────────────

def learn_from_jsonl(
    path:        str,
    func_name:   str   = "",
    max_fp_rate: float = 0.05,
) -> MetalearnResult:
    """
    Load call history from a JSONL file and run metalearning.

    Supports both ystar native format and K9Audit CIEU format.

    Args:
        path:        path to JSONL history file
        func_name:   filter to specific function (empty = all functions)
        max_fp_rate: maximum acceptable false positive rate

    Returns:
        MetalearnResult
    """
    from ystar.kernel.engine import Violation as V

    records: List[CallRecord] = []
    seq = 0

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue

            # Support K9Audit CIEU format
            # Support K9Audit CIEU format
            u_t   = rec.get("U_t", {})
            r_t   = rec.get("R_t+1", {})
            skill = u_t.get("skill", rec.get("func_name", ""))

            if func_name and func_name not in skill:
                continue

            params     = u_t.get("params", rec.get("params", {}))
            result_val = rec.get("Y_t+1", {}).get("result", None)
            timestamp  = rec.get("timestamp", rec.get("ts", 0.0))
            caller_ctx = rec.get("caller_ctx", {})

            raw_violations = r_t.get("violations", rec.get("violations", []))
            violations = []
            for vd in raw_violations:
                violations.append(V(
                    dimension  = vd.get("type", "deny").lower().replace(
                        "deny_content", "deny").replace("blocklist_hit", "deny_commands"),
                    field      = vd.get("field", ""),
                    message    = vd.get("message", ""),
                    actual     = vd.get("actual", ""),
                    constraint = vd.get("constraint", ""),
                    severity   = vd.get("severity", 0.8),
                ))

            # v0.7: parse CIEU complete five-tuple fields
            # y*_t — ideal contract (K9Audit format: Y_star_t field)
            intent_dict = rec.get("Y_star_t", rec.get("intent_contract", None))
            intent_c = None
            if isinstance(intent_dict, dict):
                from ystar.kernel.dimensions import IntentContract as _IC
                intent_c = _IC.from_dict(intent_dict)

            # applied_contract (the contract actually used by Y*)
            applied_dict = rec.get("applied_contract", None)
            applied_c = None
            if isinstance(applied_dict, dict):
                from ystar.kernel.dimensions import IntentContract as _IC2
                applied_c = _IC2.from_dict(applied_dict)

            # x_t — system state
            system_state = rec.get("X_t", rec.get("system_state", {}))

            records.append(CallRecord(
                seq              = seq,
                func_name        = skill,
                params           = params,
                result           = result_val,
                violations       = violations,
                intent_contract  = intent_c,
                applied_contract = applied_c,
                system_state     = system_state,
                timestamp        = float(timestamp),
                caller_ctx       = caller_ctx,
            ))
            seq += 1

    return learn(records, max_fp_rate=max_fp_rate)


# ══════════════════════════════════════════════════════════════════════════════
# v0.13.0  ParameterDiscovery — automatic discovery of unknown parameters and threshold inference
# ══════════════════════════════════════════════════════════════════════════════
# TODO: Implementation pending
