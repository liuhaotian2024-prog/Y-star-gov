"""
ystar.module_graph.registry — Y* 所有模块的语义注册表

每个条目描述一个 Y* 模块的：
  - 类型接口（输入/输出）
  - 治理语义标签
  - 是否已接线（在当前代码库中）
  - 与其他模块的已知连接

这里的"语义标签"是人工定义的，不能自动生成——
它们描述的是"这个模块在治理框架中扮演什么角色"，
这需要领域知识。
"""
from ystar.module_graph.graph import ModuleGraph, ModuleNode, ModuleEdge

# ── 构建全局注册表 ────────────────────────────────────────────────────────────
_graph = ModuleGraph()

def _n(id, mod, fn, inputs, out, tags, desc, side_effects=None, requires=None):
    _graph.add_node(ModuleNode(
        id=id, module_path=mod, func_name=fn,
        input_types=inputs, output_type=out, tags=tags,
        description=desc,
        side_effects=side_effects or [],
        requires=requires or [],
    ))

def _e(src, tgt, dtype, tags, meaning, wired=False):
    _graph.add_edge(ModuleEdge(
        source_id=src, target_id=tgt,
        data_type=dtype, combined_tags=tags,
        governance_meaning=meaning,
        is_wired=wired,
    ))

# ════════════════════════════════════════════════════════════════════════════
# 节点注册
# ════════════════════════════════════════════════════════════════════════════

# ── 合约构建 ──────────────────────────────────────────────────────────────────
_n("translate_to_contract",
   "ystar.kernel.nl_to_contract", "translate_to_contract",
   ["str"],
   "Dict[str, Any]",
   ["contract_build"],
   "将自然语言 AGENTS.md 翻译成合约字典")

_n("prefill",
   "ystar.kernel.prefill", "prefill",
   ["Callable", "str"],
   "PrefillResult",
   ["contract_prefill", "contract_build"],
   "从函数签名自动推断合约约束（含6个数据来源）",
   requires=["pretrain_discovered_patterns"])

_n("IntentContract",
   "ystar.kernel.dimensions", "IntentContract",
   ["Dict[str, Any]"],
   "IntentContract",
   ["contract_build"],
   "合约对象（8维度+义务时限）")

# ── 核心执行 ──────────────────────────────────────────────────────────────────
_n("check",
   "ystar.kernel.engine", "check",
   ["Dict[str, Any]", "IntentContract"],
   "CheckResult",
   ["enforcement", "contract_check"],
   "对工具调用参数进行合约检查",
   side_effects=[])

_n("enforce",
   "ystar.domains.openclaw.adapter", "enforce",
   ["OpenClawEvent", "SessionState"],
   "OpenClawCIEU",
   ["enforcement", "audit_write"],
   "执行检查并写入 CIEU 审计链",
   side_effects=["CIEUStore.write"],
   requires=["check"])

# ── 历史扫描与追溯 ────────────────────────────────────────────────────────────
_n("scan_history",
   "ystar.kernel.history_scanner", "scan_history",
   ["str", "int"],
   "List[ToolCallRecord]",
   ["retro_assess"],
   "扫描历史工具调用记录（多来源适配器）")

_n("assess_batch",
   "ystar.kernel.retroactive", "assess_batch",
   ["List[ToolCallRecord]", "IntentContract"],
   "List[RetroAssessment]",
   ["retro_assess", "contract_check"],
   "对历史记录批量追溯评估（反事实分析）",
   requires=["scan_history"])

# ── 检测层 ────────────────────────────────────────────────────────────────────
_n("ChainDriftDetector",
   "ystar.domains.openclaw.adapter", "ChainDriftDetector.detect",
   ["str", "List[str]", "str"],
   "Tuple[bool, Optional[str], Optional[str]]",
   ["drift_detection"],
   "检测 agent 链级任务漂移（使命偏离/扩权/组合信号）")

_n("SkillProvenance",
   "ystar.domains.openclaw.adapter", "SkillProvenance.risk_level",
   ["str", "str"],
   "str",
   ["skill_risk"],
   "评估技能供应链风险（safe/escalate/deny）")

_n("assess_skill_risk",
   "ystar.domains.openclaw.adapter", "assess_skill_risk",
   ["str", "str"],
   "Tuple[bool, Optional[str]]",
   ["skill_risk"],
   "底层技能风险评估函数")

# ── Omission 治理 ─────────────────────────────────────────────────────────────
_n("OmissionEngine.scan",
   "ystar.governance.omission_engine", "OmissionEngine.scan",
   ["float"],
   "EngineResult",
   ["obligation_track", "omission_gate"],
   "扫描超时 obligation 生成违规",
   side_effects=["OmissionStore.write", "CIEUStore.write"],
   requires=["InterventionEngine"])

_n("InterventionEngine.process_violations",
   "ystar.governance.intervention_engine",
   "InterventionEngine.process_violations",
   ["List[OmissionViolation]"],
   "InterventionResult",
   ["intervention", "omission_gate"],
   "处理违规→写入 PulseStore（触发 gate_check DENY）",
   side_effects=["PulseStore.write"])

# ── 元学习 ────────────────────────────────────────────────────────────────────
_n("derive_objective",
   "ystar.governance.metalearning", "derive_objective",
   ["List[CallRecord]"],
   "NormativeObjective",
   ["objective_derive"],
   "从 CIEU 历史推导目标函数（纯算术，零LLM）",
   requires=["CIEUStore"])

_n("learn",
   "ystar.governance.metalearning", "learn",
   ["List[CallRecord]", "IntentContract"],
   "MetalearnResult",
   ["meta_learn"],
   "最小覆盖算法发现规则候选",
   requires=["derive_objective"])

_n("update_coefficients",
   "ystar.governance.metalearning", "update_coefficients",
   ["RefinementFeedback", "AdaptiveCoefficients"],
   "AdaptiveCoefficients",
   ["autotune"],
   "确定性更新先验系数（过激/效果不足信号驱动）")

_n("discover_parameters",
   "ystar.governance.metalearning", "discover_parameters",
   ["List[CallRecord]", "IntentContract"],
   "List[ParameterHint]",
   ["meta_learn", "contract_build"],
   "从历史数据发现高置信度参数规则")

# ── 报告与治理循环 ────────────────────────────────────────────────────────────
_n("ReportEngine.daily_report",
   "ystar.governance.reporting", "ReportEngine.daily_report",
   ["float"],
   "Report",
   ["report_gen", "health_monitor"],
   "生成每日治理报告（CIEU+Omission+Intervention 综合）",
   requires=["CIEUStore", "OmissionStore"])

_n("GovernanceLoop.tighten",
   "ystar.governance.governance_loop", "GovernanceLoop.tighten",
   ["List[GovernanceObservation]"],
   "GovernanceTightenResult",
   ["health_monitor", "meta_learn", "autotune"],
   "综合观测+学习+建议的治理周期",
   requires=["ReportEngine.daily_report", "learn"])

_n("GovernanceLoop.bootstrap_from_scan_history",
   "ystar.governance.governance_loop",
   "GovernanceLoop.bootstrap_from_scan_history",
   ["str", "int"],
   "int",
   ["retro_assess", "meta_learn"],
   "从 scan_history 历史冷启动治理循环（v5.1 新增连接）",
   requires=["scan_history"])

# ── Domain Packs ──────────────────────────────────────────────────────────────
_n("apply_finance_pack",
   "ystar.domains.omission_domain_packs", "apply_finance_pack",
   ["RuleRegistry", "IntentContract"],
   "None",
   ["domain_pack", "obligation_track"],
   "金融场景义务时限覆盖（严格监管要求）")

_n("apply_healthcare_pack",
   "ystar.domains.omission_domain_packs", "apply_healthcare_pack",
   ["RuleRegistry", "IntentContract"],
   "None",
   ["domain_pack", "obligation_track"],
   "医疗场景义务时限覆盖（HIPAA 合规）")

_n("apply_devops_pack",
   "ystar.domains.omission_domain_packs", "apply_devops_pack",
   ["RuleRegistry", "IntentContract"],
   "None",
   ["domain_pack", "obligation_track"],
   "DevOps 场景义务时限覆盖（部署审批要求）")

# ── 委托链 ────────────────────────────────────────────────────────────────────
_n("DelegationChain",
   "ystar.kernel.dimensions", "DelegationChain",
   ["str", "str", "int"],
   "DelegationChain",
   ["enforcement", "attribution"],
   "多级委托链（捕获子 agent 越权）",
   requires=["check"])

# ════════════════════════════════════════════════════════════════════════════
# 已知已接线的边（当前代码库中实际存在的连接）
# ════════════════════════════════════════════════════════════════════════════

# 管道1：执行
_e("translate_to_contract","IntentContract","Dict",
   ["contract_build"],"AGENTS.md → 合约对象",wired=True)
_e("prefill","check","PrefillResult",
   ["contract_prefill","enforcement"],"prefill 结果→ check 使用",wired=True)
_e("check","enforce","CheckResult",
   ["enforcement","audit_write"],"check 结果 → enforce 写入 CIEU",wired=True)
_e("enforce","GovernanceLoop.tighten","OpenClawCIEU",
   ["enforcement","health_monitor"],"enforce 事件 → 治理循环观测",wired=False)

# 管道2：Omission
_e("OmissionEngine.scan","InterventionEngine.process_violations","EngineResult",
   ["obligation_track","omission_gate"],"scan 违规 → intervention 处理（已接）",wired=True)
_e("InterventionEngine.process_violations","enforce","InterventionResult",
   ["omission_gate","enforcement"],"INTERRUPT_GATE 脉冲→ enforce gate_check（已接）",wired=True)

# 管道3：报告/学习
_e("scan_history","assess_batch","List[ToolCallRecord]",
   ["retro_assess"],"历史记录→追溯评估",wired=True)
_e("assess_batch","learn","List[RetroAssessment]",
   ["retro_assess","meta_learn"],"追溯评估→元学习（已接）",wired=True)
_e("learn","GovernanceLoop.tighten","MetalearnResult",
   ["meta_learn","health_monitor"],"候选规则→治理循环（已接）",wired=True)
_e("derive_objective","learn","NormativeObjective",
   ["objective_derive","meta_learn"],"目标函数→学习（已接）",wired=True)
_e("ReportEngine.daily_report","GovernanceLoop.tighten","Report",
   ["report_gen","health_monitor"],"每日报告→治理循环（已接）",wired=True)
_e("GovernanceLoop.bootstrap_from_scan_history","GovernanceLoop.tighten","int",
   ["retro_assess","meta_learn"],"scan_history→治理循环（v5.1 新接）",wired=True)

# 未接但高价值的边
_e("SkillProvenance","OmissionEngine.scan","str",
   ["skill_risk","obligation_track"],
   "高风险技能→自动创建 review 义务（v0.40.0 已接）",wired=True)
_e("ChainDriftDetector","OmissionEngine.scan","Tuple",
   ["drift_detection","obligation_track"],
   "漂移事件→触发跟踪义务（v0.40.0 已接）",wired=True)
_e("DelegationChain","apply_finance_pack","DelegationChain",
   ["enforcement","domain_pack"],
   "委托深度→自动匹配更严格的领域包（v0.40.0 已接）",wired=True)
_e("discover_parameters","prefill","List[ParameterHint]",
   ["meta_learn","contract_prefill"],
   "数据发现的参数规则→prefill Source 6（v5.1 新接）",wired=True)
_e("GovernanceLoop.tighten","translate_to_contract","GovernanceTightenResult",
   ["health_monitor","contract_build"],
   "治理建议→回写 AGENTS.md（已部分接）",wired=True)
_e("assess_batch","derive_objective","List[RetroAssessment]",
   ["retro_assess","objective_derive"],
   "追溯评估→目标函数推导（v5管道已接：assess_batch结果→CallRecord→derive_objective）",wired=True)

# ── 自动推导剩余兼容边 ────────────────────────────────────────────────────────
n_auto = _graph.auto_derive_edges()

# 导出
MODULE_REGISTRY: ModuleGraph = _graph
