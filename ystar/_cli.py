# ystar/_cli.py  —  CLI entrypoint v0.41.0
"""
ystar CLI

命令：
  ystar setup          生成 .ystar_session.json（完整治理链路必需）
  ystar hook-install   注册 PreToolUse hook 到 OpenClaw
  ystar init           生成 policy.py 合约模板
  ystar audit          查看因果审计报告
  ystar simulate       模拟评估拦截效果（A/B 对比）
  ystar quality        评估合约质量（覆盖率/误拦率）
  ystar check          对 JSONL 事件文件跑 policy check
  ystar report         生成治理报告
  ystar version        显示版本号

快速开始（三步接入 OpenClaw）：
  pip install ystar
  ystar setup            ← 第一步：生成 session 配置
  ystar hook-install     ← 第二步：注册 hook
  # 在项目目录写 AGENTS.md ← 第三步：定义合约
"""
import sys
import json
import time
import pathlib
from typing import Optional


# ══════════════════════════════════════════════════════════════════════
#  ystar init — 三步完成接入
# ══════════════════════════════════════════════════════════════════════

def _cmd_init() -> None:
    """
    从 AGENTS.md 一键接入：
      1. 找到 AGENTS.md
      2. LLM 翻译规则（或正则降级）
      3. 用户确认
      4. 输出 CLAUDE.md hook 配置
    """
    from ystar.kernel.nl_to_contract import (
        find_agents_md, load_and_translate, format_contract_for_human
    )

    print()
    print("  Y* 接入向导")
    print("  " + "─" * 40)
    print()

    # ── 步骤 1：找 AGENTS.md ──────────────────────────────────────
    md_path = find_agents_md()
    if md_path is None:
        print("  [1/3] 未找到 AGENTS.md / CLAUDE.md")
        print()
        print("  请先创建一个 AGENTS.md，写上你的规则，例如：")
        print()
        print("    # My Rules")
        print("    - Never modify /production")
        print("    - Never run rm -rf")
        print("    - Only write to ./workspace/")
        print("    - Maximum $10,000 per transaction")
        print()
        print("  然后重新运行 ystar init")
        print()
        return

    print(f"  [1/3] 找到 {md_path} ✓")
    print()

    # ── 步骤 2：翻译 + Y* 验证 ────────────────────────────────────
    print("  [2/3] 翻译规则...", end="", flush=True)
    text = md_path.read_text(encoding="utf-8", errors="replace")

    from ystar.kernel.nl_to_contract import (
        translate_to_contract, format_contract_for_human, validate_contract_draft
    )
    contract_dict, method, confidence = translate_to_contract(text)
    method_label = "LLM" if method == "llm" else "正则（降级）"
    print(f" 完成（{method_label}，{len(contract_dict)} 个维度）")
    print()

    if not contract_dict:
        print("  ⚠ 未能解析到任何规则。")
        print("  请检查 AGENTS.md 的格式，或使用 from_template() 直接定义规则。")
        print()
        return

    # 展示翻译结果 + Y* 验证报告（含错误/警告/覆盖率/建议）
    print(format_contract_for_human(contract_dict, method, confidence,
                                    original_text=text))

    validation = validate_contract_draft(contract_dict, text)

    # 有明确错误时，阻止直接确认
    if validation["errors"]:
        print()
        print("  ⛔ Y* 发现翻译错误，请修改 AGENTS.md 后重新运行 ystar init。")
        print()
        return

    # 根据健康度调整提示语
    if validation["warnings"] or not validation["is_healthy"]:
        prompt = ("  以上是你的意思吗？"
                  "规则有待完善，可先确认继续。[Y/n/e(编辑后重试)] ")
    else:
        prompt = "  以上是你的意思吗？[Y/n] "

    while True:
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  已取消。")
            return

        if answer in ("", "y", "yes", "是", "对"):
            print()
            print("  ✅ 规则已确认，进入 Y* 确定性执行层。")
            print("  之后每次 Agent 操作，check() 结果永远确定，LLM 不再参与。")
            break
        if answer in ("n", "no", "否", "不"):
            print()
            print("  已取消。请修改 AGENTS.md 后重新运行 ystar init。")
            print()
            return
        if answer in ("e", "edit", "编辑"):
            print()
            print("  请修改 AGENTS.md，然后重新运行 ystar init。")
            print()
            return
        print("  请输入 Y（确认）、N（取消）或 E（编辑后重试）")

    # ── 步骤 3：输出 hook 配置 ─────────────────────────────────────
    print()
    print("  [3/3] 在你的 CLAUDE.md 里加上以下配置：")
    print()
    print("  ┌─────────────────────────────────────────┐")
    print("  │  hooks:                                  │")
    print("  │    PreToolUse:                           │")
    print("  │      - matcher: \"*\"                      │")
    print("  │        hooks:                            │")
    print("  │          - command: ystar-hook           │")
    print("  └─────────────────────────────────────────┘")
    print()
    print("  ✅ Y* 已准备好。")

    # ── 把合约配置写入 .ystar_session.json ──────────────────────────
    # check_hook 启动时读取此文件，自动升级到完整治理路径（enforce + CIEU）
    # 用户无感知，接口零变化
    try:
        import uuid, time as _t
        session_cfg = {
            "session_id":      str(uuid.uuid4())[:12],
            "created_at":      _t.time(),
            "contract":        contract_dict,
            "source":          str(md_path) if md_path else "AGENTS.md",
            "cieu_db":         ".ystar_cieu.db",
            # 治理配置（可手动修改，或在 AGENTS.md 里通过自然语言配置）
            # auto_activate_threshold: 规则建议自动激活的置信度阈值
            #   0.9 = 标准（默认）  0.95 = 谨慎（金融/医疗）  0.8 = 宽松（快速迭代）
            "governance_config": {
                "auto_activate_threshold": 0.9,
            },
        }
        with open(".ystar_session.json", "w", encoding="utf-8") as _f:
            json.dump(session_cfg, _f, ensure_ascii=False, indent=2)
    except Exception:
        pass   # 写入失败不影响主流程，静默降级

    # ── 追溯初始基线扫描 ──────────────────────────────────────────
    # 扫描 ~/.claude/projects/ 的历史会话，用当前规则回放，
    # 告诉用户"如果 Y* 一直在运行，它会说什么"。
    # 追溯数据写入独立的 .ystar_retro_baseline.db，
    # 永不混入实时 CIEU 链，防止字节污染。
    print()
    _run_retroactive_baseline(contract_dict)
    print()


def _run_retroactive_baseline(contract_dict: dict) -> None:
    """
    扫描既有历史行为，运行追溯基线分析。

    通过 kernel/history_scanner.scan_history() 调度，
    不关心数据来自哪个框架（Claude Code / OpenClaw / JSONL …）。
    """
    import warnings as _w
    _w.filterwarnings("ignore")

    from ystar.kernel.history_scanner import scan_history, available_sources
    from ystar.kernel.retroactive import assess_batch, summarize
    from ystar.governance.retro_store import RetroBaselineStore
    from ystar.dimensions import IntentContract, normalize_aliases

    # ① 探测可用来源
    sources = available_sources()
    any_available = any(s["available"] for s in sources)

    if not any_available:
        print("  ─── 初始基线 ────────────────────────────────────────────────")
        print("  未找到任何历史行为记录。")
        print()
        for s in sources:
            if not s["available"]:
                print(f"  · {s['label']}: {s.get('reason', '不可用')}")
        print()
        print("  这是正常的。运行 Agent 后，Y* 将开始记录 CIEU 因果链。")
        print("  运行 Agent 后执行：")
        print("    ystar audit          查看意图 vs 行动的因果报告")
        print("    ystar quality        评估规则覆盖率")
        return

    # ② 扫描（框架无关）
    print("  正在扫描历史记录...", end="", flush=True)
    records, source_id, source_desc = scan_history(days_back=30, max_records=5000)

    if not records:
        print(" 未找到记录")
        print()
        print("  最近 30 天内没有历史记录。")
        print("  运行 Agent 后执行 ystar audit 建立第一份因果报告。")
        return

    from ystar.adapters.claude_code_scanner import scan_summary
    summary_info = scan_summary(records)
    print(f" 发现 {summary_info['total']} 条记录（来源: {source_desc}）")

    # ③ 询问确认
    print()
    print(f"  {summary_info['sessions']} 个会话，"
          f"时间范围: {summary_info['date_range']}")
    print(f"  工具调用: "
          + ", ".join(f"{n}×{c}" for n, c in summary_info["top_tools"][:4]))
    print()
    print("  Y* 将用你的当前规则回放这些历史记录，")
    print("  告诉你「如果 Y* 一直在运行，它会看到什么」。")
    print()
    print("  结果写入 .ystar_retro_baseline.db（独立文件，不影响实时 CIEU）。")
    print()
    try:
        answer = input("  是否立即生成初始基线报告？[Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer in ("n", "no", "否"):
        print()
        print("  跳过。稍后可运行 ystar baseline 生成追溯基线报告。")
        return

    # ④ 构建合约
    cd = dict(contract_dict or {})
    cd.pop("temporal", None)
    try:
        contract = normalize_aliases(**cd)
    except Exception:
        contract = IntentContract()

    # ⑤ 追溯检查（核心层）
    print()
    print("  正在回放历史记录...", end="", flush=True)
    assessments   = assess_batch(records, contract)
    retro_summary = summarize(assessments)
    print(f" 完成（{len(assessments)} 条）")

    # ⑥ 写入独立存储（防字节污染）
    store       = RetroBaselineStore()
    baseline_id = store.begin_baseline(
        contract_hash=contract.hash,
        notes=f"ystar init, source={source_id}, {len(assessments)} records",
    )
    store.write_assessments(assessments, baseline_id)

    # ⑦ ContractQuality + DimensionDiscovery
    quality_score = None
    dim_hints     = []
    try:
        from ystar.governance.metalearning import ContractQuality, DimensionDiscovery
        call_records = store.as_call_records(baseline_id, limit=300)
        if call_records:
            q             = ContractQuality.evaluate(contract, call_records)
            quality_score = q.quality_score
            dim_hints     = DimensionDiscovery.analyze(call_records)[:3]
    except Exception:
        pass

    # ⑧ 输出报告
    _print_retro_baseline_report(retro_summary, quality_score, dim_hints, baseline_id)


def _print_retro_baseline_report(
    retro_summary,
    quality_score: float | None,
    dim_hints: list,
    baseline_id: str,
) -> None:
    """输出追溯基线报告（真实数据，明确标注来源）。"""
    W = 52

    def h(title):  print(f"\n  ┌─ {title} {'─' * max(0, W - len(title) - 4)}┐")
    def row(k, v): print(f"  │  {k:<28} {v:<21}│")
    def foot():    print(f"  └{'─' * (W + 2)}┘")
    def note(s):   print(f"  ✦ {s}")

    total = retro_summary.total
    deny  = retro_summary.deny_count
    allow = retro_summary.allow_count

    h(f"追溯基线报告  [基于真实历史，非模拟]")
    row("历史记录总计",     f"{total} 条工具调用")
    row("时间范围",         retro_summary.date_range)
    row("会话数",           f"{retro_summary.sessions} 个会话")
    row("按当前规则：允许", f"{allow} 次 ({allow/max(total,1):.0%})")
    row("按当前规则：拦截", f"{deny}  次 ({deny/max(total,1):.0%})")
    foot()
    note("这是追溯分析：用你现在的规则回放历史，不是实时审计")

    # 违规维度分布
    if retro_summary.top_violations:
        h("历史违规维度（如果 Y* 当时在运行）")
        for dim, cnt in retro_summary.top_violations[:5]:
            bar = "█" * min(cnt * 2, 18)
            print(f"  │  {dim:<22} {bar:<18} {cnt}│")
        foot()

    # ContractQuality 评分
    if quality_score is not None:
        qs_icon = "✅" if quality_score >= 0.8 else ("⚠ " if quality_score >= 0.6 else "❌")
        h(f"规则质量评估")
        row("综合质量分",  f"{qs_icon} {quality_score:.2f} / 1.00")
        foot()

    # DimensionDiscovery 建议
    if dim_hints:
        h("💡 DimensionDiscovery 发现未覆盖的模式")
        for hint in dim_hints:
            # 截断英文提示，保留关键信息
            short = hint[:50] + "…" if len(hint) > 50 else hint
            print(f"  │  → {short:<47}│")
        foot()
        note("考虑在 AGENTS.md 里补充这些约束类型，重新运行 ystar init")

    # 行动指南
    print()
    print(f"  ┌─ 接下来你可以做什么 {'─' * 30}┐")
    print(f"  │                                                    │")

    if deny > 0:
        print(f"  │  ystar audit       查看 {deny} 次历史拦截的完整现场        │")
    else:
        print(f"  │  ystar audit       运行 Agent 后查看实时因果审计报告       │")

    if dim_hints:
        print(f"  │  ystar quality     查看规则覆盖率，获取补充维度建议        │")

    print(f"  │  ystar simulate    验证规则的实时拦截效果（A/B 对比）    │")
    print(f"  │                                                    │")
    print(f"  └{'─' * (W + 2)}┘")
    print()
    note(f"基线已锚定（ID: {baseline_id}）。")
    note("运行 Agent 后的数据将与此基线对比，显示治理改善程度。")


def _print_baseline_report(wr_result, sim_result, g_result) -> None:
    """
    把 WorkloadRunner + WorkloadSimulator + GovernanceLoop 的结果
    组合成用户能看懂的初始基线报告。

    四个区块：
      1. 拦截能力（WorkloadSimulator 数字）
      2. 合规监控（WorkloadRunner 数字）
      3. 治理建议（GovernanceLoop 输出）
      4. 行动指南（静态 + 动态，根据数据状态生成）
    """
    W = 52

    def sep(char="─"): print(f"  {char * W}")
    def h(title):      print(f"\n  ┌─ {title} {'─' * max(0, W - len(title) - 4)}┐")
    def row(k, v):     print(f"  │  {k:<30} {v:<17}│")
    def foot():        print(f"  └{'─' * (W + 2)}┘")
    def note(s):       print(f"  ✦ {s}")

    print("  （以下数据来自模拟工作负载，不是你的真实 Agent 数据）")

    # ── 区块 1：拦截能力 ──────────────────────────────────────────
    h("拦截能力  [模拟：你的规则 vs 25% 危险操作]")
    row("危险操作拦截率",  f"{sim_result.recall:.0%}  （无 Y* = 0%）")
    row("正常操作误拦率",  f"{sim_result.false_positive_rate:.0%}")
    row("模拟规模",        f"{sim_result.total_events} 个操作")
    foot()
    note("hook 规则已生效：Agent 每次操作前 Y* 都会比对你的合约")

    # ── 区块 2：合规监控 ──────────────────────────────────────────
    h("合规监控（omission / 任务承诺）")
    row("任务承诺总数",    str(wr_result.total_obligations))
    row("按时履约率",      f"{wr_result.fulfillment_rate:.0%}")
    row("遗漏检测率",      f"{wr_result.raw_report.kpis.get('omission_detection_rate', 0):.0%}")
    row("治理建议数",      str(wr_result.governance_suggestions))
    foot()
    note("Y* 监控的不只是「做了什么」，还有「承诺做的有没有做」")

    # ── 区块 3：治理建议 ──────────────────────────────────────────
    # 说明：健康状态来自模拟场景（Agent 有任务时限但未及时关闭），
    # 不代表用户的规则有问题，而是展示"Y* 在真实环境里会检测到什么"
    health = g_result.overall_health
    health_icons = {"healthy": "✅", "warning": "⚠ ", "degraded": "⚠ ", "critical": "⚠ "}
    icon   = health_icons.get(health, "·")
    health_label = {
        "healthy":  "健康",
        "warning":  "有待观察",
        "degraded": "需要关注",
        "critical": "检测到遗漏行为",
    }.get(health, health)

    h(f"Y* 在真实场景能检测到  {icon} {health_label}  [模拟]")
    if g_result.recommended_action and "No observations" not in g_result.recommended_action:
        action = g_result.recommended_action
        if "omission rate" in action.lower() or "recovery rate" in action.lower():
            action_cn = "模拟中检测到任务遗漏——真实 Agent 接入后 Y* 会同样记录"
        elif "tighten" in action.lower():
            action_cn = "建议收紧部分规则，运行 ystar quality 查看具体改进方向"
        elif "healthy" in action.lower() or health == "healthy":
            action_cn = "治理状态健康，规则覆盖正常"
        elif "no improvement" in action.lower():
            action_cn = "未检测到改善空间，维持现有规则"
        else:
            # 截取英文句子的核心部分，去掉具体数字
            import re as _re
            cn_parts = []
            if "omission" in action.lower():   cn_parts.append("存在遗漏行为")
            if "closure"  in action.lower():   cn_parts.append("任务未完整关闭")
            if "tighten"  in action.lower():   cn_parts.append("建议收紧规则")
            if "domain"   in action.lower():   cn_parts.append("考虑应用领域规则包")
            action_cn = "；".join(cn_parts) if cn_parts else action[:50]
        print(f"  │  {action_cn:<50}│")

    for sug in (g_result.governance_suggestions or [])[:2]:
        if hasattr(sug, "rationale") and sug.rationale:
            # 把英文 rationale 提取关键信息翻译
            r = sug.rationale
            cn = ""
            if "omission detection" in r.lower() and "recovery" in r.lower():
                cn = "遗漏已被检测到，但尚未恢复——考虑激活干预机制"
            elif "accounts for" in r.lower() and "%" in r:
                import re as _re
                m = _re.search(r"'([^']+)' accounts for (\d+)%", r)
                if m:
                    cn = f"主要违规类型 {m.group(1)!r}，占比 {m.group(2)}%——优先处理"
            if cn:
                print(f"  │  · {cn:<47}│")
    foot()

    # ── 区块 4：行动指南 ──────────────────────────────────────────
    print()
    print(f"  ┌─ 接下来你可以做什么 {'─' * 30}┐")
    print(f"  │                                                    │")

    lines_guide = []
    seen_cmds   = set()

    def add(cmd, desc):
        if cmd not in seen_cmds:
            lines_guide.append((cmd, desc))
            seen_cmds.add(cmd)

    # 固定顺序：先跑 Agent → 看 audit → 看 quality → simulate 随时可用
    add("ystar audit",    "运行 Agent 后，查看意图 vs 行动的因果报告")
    add("ystar quality",  "评估规则覆盖率，获取补充维度建议")
    add("ystar simulate", "随时验证拦截效果（A/B 对比）")

    for cmd, desc in lines_guide[:4]:
        print(f"  │  {cmd:<16}  {desc:<32}│")

    print(f"  │                                                    │")
    print(f"  └{'─' * (W + 2)}┘")
    print()
    note("CIEU 因果链从现在开始持续记录。"
         "运行 ystar audit 随时查看 Agent 承诺 vs 实际行动。")


# ══════════════════════════════════════════════════════════════════════
#  ystar audit — 因果审计报告
# ══════════════════════════════════════════════════════════════════════

def _cmd_audit(args: list) -> None:
    """
    因果审计报告：意图合约 vs 实际行动，完整现场重现。

    用法：
      ystar audit                         最近 session 摘要
      ystar audit --session sess-001      指定 session
      ystar audit --db path/to/cieu.db    指定数据库文件
      ystar audit --limit 20              最多展示 N 条违规（默认 10）
    """
    session_id = None
    db_path    = ".ystar_cieu.db"
    limit      = 10

    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_id = args[i + 1]; i += 2
        elif args[i] == "--db" and i + 1 < len(args):
            db_path = args[i + 1]; i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            i += 1

    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(db_path)
    except Exception as e:
        print(f"\n  无法打开数据库 {db_path}: {e}\n")
        return

    if store.count() == 0:
        print()
        print("  CIEU 数据库为空。运行你的 Agent 后再来查看。")
        print()
        return

    stats = store.stats(session_id=session_id)
    total_n    = stats.get("total", 0)
    by_dec     = stats.get("by_decision", {})
    allow_n    = by_dec.get("allow", 0)
    deny_n     = by_dec.get("deny", 0)
    escalate_n = by_dec.get("escalate", 0)

    print()
    print("  Y* 因果审计报告")
    print("  " + "═" * 50)
    if session_id:
        print(f"  会话: {session_id}")
    print()

    # ── 封印验证 ──────────────────────────────────────────────────
    if session_id:
        vr = store.verify_session_seal(session_id)
        if "error" in vr or "valid" not in vr:
            seal_line = "⚪ 未封印 — 运行 `ystar seal --session` 生成密码学证明"
        elif vr["valid"]:
            root_short = vr["stored_root"][:16]
            seal_line  = (f"✅ 已封印（Merkle root: {root_short}…  "
                          f"事件数: {vr['stored_count']}）")
        else:
            tamper = vr.get("tamper_evidence", "未知原因")
            seal_line = f"❌ 封印验证失败 — {tamper}"
        print(f"  封印状态: {seal_line}")
        print()

    # ── 执行摘要 ──────────────────────────────────────────────────
    print("  执行摘要")
    print("  " + "─" * 50)
    print(f"  审计事件总计:        {total_n} 条（含完整参数快照）")
    print(f"  ✅ 按承诺执行:       {allow_n} 次")
    print(f"  ❌ 超出承诺（已拦截）: {deny_n} 次")
    if escalate_n:
        print(f"  ⚠  升级人工审批:    {escalate_n} 次")

    # 违规维度分布
    top_viols = stats.get("top_violations", [])
    if top_viols:
        print()
        print("  违规维度")
        for dim, count in top_viols:
            bar = "█" * min(count * 2, 20)
            print(f"    {dim:<20} {bar} {count}")

    # 一致性结论
    print()
    if deny_n == 0 and escalate_n == 0:
        print("  意图与行动一致性: ✅ 所有操作均在合约范围内")
    else:
        print(f"  意图与行动一致性: ✅ {deny_n + escalate_n} 次越界操作已被拦截，"
              "无漏网")
    print()

    # ── 违规现场重现 ──────────────────────────────────────────────
    deny_records = store.query(
        session_id=session_id,
        decision="deny",
        limit=limit,
    )
    if not deny_records:
        print("  （本 session 无违规记录）")
        print()
        return

    print(f"  违规现场（最近 {min(limit, len(deny_records))} 条）")
    print("  " + "─" * 50)

    import datetime
    for idx, r in enumerate(deny_records, 1):
        ts = datetime.datetime.fromtimestamp(r.created_at).strftime("%m-%d %H:%M:%S")

        # 主要操作目标
        target = (r.file_path or r.command or r.url or r.event_type or "?")
        if len(target) > 45:
            target = target[:42] + "…"

        # 违规维度
        dim = r.violations[0]["dimension"] if r.violations else "?"
        dim_icons = {
            "deny":          "🚫 路径/字符串禁止",
            "deny_commands": "🚫 命令禁止",
            "only_paths":    "🚫 路径不在白名单",
            "only_domains":  "🚫 域名不在白名单",
            "value_range":   "📊 数值超限",
            "invariant":     "⚠️  条件不满足",
            "postcondition": "⚠️  后置条件违反",
        }
        dim_label = dim_icons.get(dim, f"[{dim}]")

        print(f"  [{idx}] {ts}  {r.agent_id}")
        print(f"       类型: {dim_label}")
        print(f"       操作: {target}")

        # 违规消息
        if r.violations:
            print(f"       原因: {r.violations[0]['message']}")

        # 原始参数快照
        if r.params_json:
            try:
                params = json.loads(r.params_json)
                # 只展示最相关的字段
                shown = {}
                for key in ("file_path", "command", "url", "amount",
                            "risk_approved", "action"):
                    if key in params and params[key] not in (None, ""):
                        val = params[key]
                        if isinstance(val, str) and len(val) > 40:
                            val = val[:37] + "…"
                        shown[key] = val
                if shown:
                    param_str = "  ".join(f"{k}={repr(v)}" for k, v in shown.items())
                    print(f"       参数: {param_str}")
            except Exception:
                pass

        # 发起人和授权链
        meta_parts = []
        if r.human_initiator:
            meta_parts.append(f"发起: {r.human_initiator}")
        if r.lineage_path:
            try:
                chain = json.loads(r.lineage_path)
                meta_parts.append("授权链: " + " → ".join(chain))
            except Exception:
                pass
        if meta_parts:
            print(f"       {' | '.join(meta_parts)}")

        print()

    # 尾注
    if deny_n > limit:
        print(f"  … 还有 {deny_n - limit} 条，用 --limit {deny_n} 查看全部")
        print()


# ══════════════════════════════════════════════════════════════════════
#  ystar simulate — 内置 A/B 效果评估
# ══════════════════════════════════════════════════════════════════════

def _cmd_simulate(args: list) -> None:
    """
    用内置工作负载模拟器评估 Y* 的效果（无需连接真实系统）。

    用法：
      ystar simulate                      用默认配置运行
      ystar simulate --sessions 100       指定会话数量
      ystar simulate --agents-md FILE     用指定规则文件
    """
    sessions = 50
    agents_md_path = None

    i = 0
    while i < len(args):
        if args[i] == "--sessions" and i + 1 < len(args):
            sessions = int(args[i + 1]); i += 2
        elif args[i] == "--agents-md" and i + 1 < len(args):
            agents_md_path = args[i + 1]; i += 2
        else:
            i += 1

    print()
    print("  Y* 效果评估（内置工作负载模拟）")
    print("  " + "─" * 40)
    print(f"  模拟 {sessions} 个会话 × 20 个事件（含 25% 危险操作）")
    print("  正在运行...", end="", flush=True)

    try:
        import warnings
        warnings.filterwarnings("ignore")
        from ystar.simulation import WorkloadSimulator

        sim = WorkloadSimulator(sessions=sessions, seed=42)
        report = sim.run()

        print(" 完成")
        print()
        print("              无 Y*     有 Y*")
        print("  " + "─" * 32)
        print(f"  危险操作拦截率  0%      {report.recall:.1%}")
        print(f"  正常操作误拦率  —       {report.false_positive_rate:.1%}")
        print(f"  风险降低率      —       {report.risk_reduction:.1%}")
        print(f"  运行耗时        —       {report.run_time_sec:.2f}s")
        print()

        if report.recall > 0.9:
            print(f"  结论: ✅ Y* 拦截了 {report.recall:.0%} 的危险操作，"
                  f"误拦率 {report.false_positive_rate:.1%}")
        else:
            print(f"  结论: ⚠ 拦截率 {report.recall:.0%}，"
                  "建议检查规则是否覆盖了主要危险操作类型")
        print()
        print("  ── 推荐接入路径（EnforcementMode）──────────────────")
        print("  第 1 步: SIMULATE_ONLY  → 不拦截任何操作，只记录假设性违规")
        print("  第 2 步: OBSERVE_ONLY   → 记录真实违规，不阻断，观察一周")
        print("  第 3 步: FAIL_OPEN      → 违规记录 + 放行（降级保护）")
        print("  第 4 步: FAIL_CLOSED    → 违规即阻断（严格合规）")
        print()
        print("  用你自己的规则测试：")
        print("    ystar simulate --agents-md AGENTS.md")

    except Exception as e:
        print(f"\n  模拟运行失败: {e}")
        print()


# ══════════════════════════════════════════════════════════════════════
#  ystar quality — 合约质量评估
# ══════════════════════════════════════════════════════════════════════

def _cmd_quality(args: list) -> None:
    """
    评估当前合约对 CIEU 历史记录的覆盖质量，并可生成/应用规则优化建议。

    用法：
      ystar quality                  基础质量评估（覆盖率 / 误拦率 / 质量分）
      ystar quality --suggest        额外展示规则优化建议（基于 learn() 全链路）
      ystar quality --apply          交互式接受建议并写回 AGENTS.md
      ystar quality --db FILE        指定 CIEU 数据库
      ystar quality --agents-md FILE 指定规则文件
    """
    db_path        = ".ystar_cieu.db"
    agents_md_path = None
    do_suggest     = False
    do_apply       = False

    i = 0
    while i < len(args):
        if args[i] == "--db" and i + 1 < len(args):
            db_path = args[i + 1]; i += 2
        elif args[i] == "--agents-md" and i + 1 < len(args):
            agents_md_path = args[i + 1]; i += 2
        elif args[i] == "--suggest":
            do_suggest = True; i += 1
        elif args[i] == "--apply":
            do_suggest = True   # apply 隐含 suggest
            do_apply   = True; i += 1
        else:
            i += 1

    print()
    print("  Y* 合约质量评估")
    print("  " + "─" * 50)

    # ── 1. 加载合约 ───────────────────────────────────────────────────────
    from ystar.kernel.nl_to_contract import load_and_translate
    from ystar.dimensions import IntentContract, normalize_aliases

    contract_dict, src = load_and_translate(path=agents_md_path, confirm=False)
    if not contract_dict:
        print("  ⚠ 未找到 AGENTS.md，无法评估合约质量。")
        print("  提示：先运行 ystar init 完成接入。")
        print()
        return

    cd = dict(contract_dict)
    cd.pop("temporal", None)
    try:
        contract = normalize_aliases(**cd)
    except Exception:
        contract = IntentContract()

    print(f"  合约来源: {src or '（未知）'}")

    # ── 2. 从 CIEU 数据库重建调用历史 ────────────────────────────────────
    from ystar.governance.cieu_store import CIEUStore
    from ystar import check as ystar_check
    from ystar.governance.metalearning import CallRecord

    try:
        store = CIEUStore(db_path)
        total = store.count()
    except Exception as e:
        print(f"  ⚠ 无法读取数据库 {db_path}: {e}")
        print()
        return

    if total == 0:
        print("  ⚠ CIEU 数据库为空，运行 Agent 后再来评估。")
        print()
        return

    print(f"  历史记录: {total} 条（取最近 500 条）")

    records_raw = store.query(limit=500)
    history     = []
    for r in records_raw:
        try:
            params = json.loads(r.params_json or "{}")
            chk    = ystar_check(params, {}, contract)
            history.append(CallRecord(
                seq=len(history),
                func_name=r.event_type or "unknown",
                params=params,
                result=json.loads(r.result_json or "{}"),
                violations=chk.violations,
                intent_contract=contract,
            ))
        except Exception:
            pass

    if not history:
        print("  ⚠ 无法解析历史记录。")
        print()
        return

    # ── 3. 全链路 learn() ────────────────────────────────────────────────
    from ystar.governance.metalearning import (
        learn, ContractQuality, DimensionDiscovery, derive_objective
    )

    print()
    print("  运行全链路质量分析...", end="", flush=True)
    result    = learn(history, base_contract=contract)
    objective = derive_objective(history)
    print(" 完成")
    print()

    quality = result.quality or ContractQuality.evaluate(contract, history)
    n_viol  = sum(1 for r in history if r.violations)
    n_safe  = len(history) - n_viol

    # ── 4. 质量指标展示 ───────────────────────────────────────────────────
    print("  质量评估结果")
    print("  " + "─" * 50)
    print(f"  历史样本: {len(history)} 条（违规 {n_viol} / 安全 {n_safe}）")
    print()

    cov_icon = "✅" if quality.coverage_rate >= 0.9 else ("⚠ " if quality.coverage_rate >= 0.6 else "❌")
    fp_icon  = "✅" if quality.false_positive_rate <= 0.05 else ("⚠ " if quality.false_positive_rate <= 0.15 else "❌")
    qs_icon  = "✅" if quality.quality_score >= 0.8 else ("⚠ " if quality.quality_score >= 0.6 else "❌")

    print(f"  {cov_icon} 违规覆盖率:    {quality.coverage_rate:.0%}"
          f"  — 历史违规中有多少能被当前规则预防")
    print(f"  {fp_icon} 正常操作误拦率: {quality.false_positive_rate:.0%}"
          f"  — 越低越好")
    print(f"  {qs_icon} 综合质量分:    {quality.quality_score:.2f} / 1.00")
    print()
    print(f"  推荐误报容忍度: {objective.fp_tolerance:.3f}"
          f"  — 由历史数据统计推导（Pearl Rung-3）")
    print()

    # ABCD 诊断
    diag = result.diagnosis or {}
    if any(v > 0 for v in diag.values()):
        print("  运行状态诊断（ABCD 分类）：")
        labels = {
            "A_ideal_deficient": "A 理想不足（规则覆盖但未触发）",
            "B_execution_drift": "B 执行漂移（行为偏离意图）",
            "C_over_tightened":  "C 过度收紧（正常操作被拦）",
            "D_normal":          "D 正常运行",
        }
        for k, label in labels.items():
            v = diag.get(k, 0)
            if v > 0:
                print(f"    {label}: {v}")
        print()

    # DimensionDiscovery（已有）
    hints = result.dimension_hints or DimensionDiscovery.analyze(history)
    if hints:
        print("  💡 DimensionDiscovery 发现未覆盖的违规模式：")
        for h in hints[:3]:
            print(f"     → {h}")
        print()
    else:
        print("  ✅ DimensionDiscovery：当前维度已覆盖所有违规模式")
        print()

    # ── 5. --suggest：展示规则优化建议 ───────────────────────────────────
    if not do_suggest:
        print("  提示：运行 ystar quality --suggest 查看规则优化建议")
        print("        运行 ystar quality --apply   交互式接受建议并写回 AGENTS.md")
        print()
        return

    from ystar.governance.rule_advisor import generate_advice
    print("  生成规则优化建议...", end="", flush=True)
    advice = generate_advice(contract, history)
    print(f" 完成（{len(advice.suggestions)} 条建议）")
    print()

    if not advice.has_suggestions():
        print("  ✅ 当前规则已是最优，暂无建议。")
        print()
        return

    _print_rule_suggestions(advice)

    # ── 6. --apply：交互式接受建议 ────────────────────────────────────────
    if not do_apply:
        print()
        print("  运行 ystar quality --apply 逐条确认并写回 AGENTS.md")
        print()
        return

    print()
    _apply_suggestions(advice, agents_md_path or src)


def _print_rule_suggestions(advice) -> None:
    """格式化展示规则建议，按类型分组。"""
    categories = [
        ("add",       "建议添加的规则",     "  [+]"),
        ("tighten",   "建议收紧的规则",     "  [↑]"),
        ("relax",     "建议放宽的规则",     "  [↓]"),
        ("dimension", "建议引入的新维度",   "  [~]"),
    ]

    has_any = False
    for kind, title, prefix in categories:
        group = [s for s in advice.suggestions if s.kind == kind]
        if not group:
            continue
        has_any = True
        print(f"  {title}（{len(group)} 条）")
        print("  " + "─" * 50)
        for idx, s in enumerate(group, 1):
            conf_icon = "✅" if s.confidence >= 0.8 else ("⚠ " if s.confidence >= 0.6 else "·")
            verified  = "（已数学验证）" if s.verified else ""
            print(f"  {idx}. {conf_icon} {s.description}{verified}")
            print(f"     证据：{s.evidence}")
            if s.rule_value is not None:
                print(f"     建议值：{s.rule_value}")
            if s.coverage > 0:
                print(f"     若接受：覆盖率 +{s.coverage:.0%}，误拦率 {s.fp_rate:.0%}")
            print(f"     置信度：{s.confidence:.0%}  来源：{s.source}")
            print()

    if not has_any:
        print("  暂无建议")


def _apply_suggestions(advice, agents_md_path: str) -> None:
    """
    交互式逐条确认建议，把接受的规则追加到 AGENTS.md。
    通过 ConstraintRegistry 受控激活链（DRAFT → APPROVED → ACTIVE）。
    """
    from ystar.governance.rule_advisor import (
        append_suggestions_to_agents_md, RuleSuggestion
    )
    from ystar.governance.metalearning import ConstraintRegistry, ManagedConstraint

    actionable = [s for s in advice.suggestions
                  if s.kind in ("add", "tighten") and s.rule_value is not None]

    if not actionable:
        print("  没有可直接应用的建议（无具体规则值）。")
        print()
        return

    print("  逐条确认规则建议")
    print("  " + "─" * 50)
    print("  [Y] 接受  [N] 忽略  [?] 暂存（写入 ConstraintRegistry 待审批）")
    print()

    registry = ConstraintRegistry()
    accepted = []

    for idx, s in enumerate(actionable, 1):
        conf_icon = "✅" if s.confidence >= 0.8 else "⚠ "
        print(f"  [{idx}/{len(actionable)}] {conf_icon} {s.description}")
        print(f"  建议值: {s.rule_value}  置信度: {s.confidence:.0%}")

        while True:
            try:
                ans = input("  选择 [Y/n/?] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if ans in ("", "y", "yes", "是"):
                s.accepted = True
                accepted.append(s)
                print("  ✅ 已接受")
                break
            elif ans in ("n", "no", "否"):
                s.accepted = False
                print("  ⏭  已跳过")
                break
            elif ans in ("?", "p", "暂存"):
                # 写入 ConstraintRegistry，稍后审批
                mc = ManagedConstraint(
                    id          = f"suggest-{idx}-{int(time.time())}",
                    dimension   = s.dimension,
                    rule        = str(s.rule_value),
                    status      = "DRAFT",
                    source      = f"ystar quality --apply ({s.source})",
                    confidence  = s.confidence,
                    created_at  = time.time(),
                    updated_at  = time.time(),
                    notes       = s.evidence,
                )
                try:
                    registry.add(mc)
                    print("  📋 已暂存到 ConstraintRegistry（DRAFT 状态）")
                except Exception as e:
                    print(f"  ⚠ 暂存失败: {e}")
                break
            print("  请输入 Y、N 或 ?")
        print()

    # 写回 AGENTS.md
    if accepted:
        print(f"  写入 {len(accepted)} 条规则到 AGENTS.md...", end="", flush=True)
        ok = append_suggestions_to_agents_md(
            agents_md_path, accepted, advice.history_size
        )
        if ok:
            print(" 完成")
            print()
            print("  ✅ AGENTS.md 已更新。运行 ystar init 让新规则生效：")
            print("     ystar init")
        else:
            print(" 失败")
            print(f"  ⚠ 无法写入 {agents_md_path}")
    else:
        print("  未接受任何建议，AGENTS.md 未修改。")

    # 展示 ConstraintRegistry 里暂存的建议
    drafts = registry.by_status("DRAFT")
    if drafts:
        print()
        print(f"  📋 {len(drafts)} 条建议已暂存到 ConstraintRegistry。")
        print("  运行以下命令管理暂存建议：")
        print("    from ystar.governance.metalearning import ConstraintRegistry")
        print("    reg = ConstraintRegistry()")
        print("    reg.summary()")
    print()


# ══════════════════════════════════════════════════════════════════════
#  原有命令（保留兼容性）
# ══════════════════════════════════════════════════════════════════════

def _cmd_check(path: str) -> None:
    from ystar import IntentContract, check as ystar_check
    events_path = pathlib.Path(path)
    if not events_path.exists():
        print(f"File not found: {path}"); sys.exit(1)

    violations = 0
    total = 0
    for line in events_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        params = rec.get("params", rec)
        contract_def = rec.get("contract", {})
        c = IntentContract(**{k: v for k, v in contract_def.items()
                              if k in ("deny", "only_paths", "deny_commands",
                                       "only_domains", "invariant")})
        r = ystar_check(params, {}, c)
        total += 1
        if not r.passed:
            violations += 1
            for v in r.violations:
                print(f"VIOLATION  {v.dimension}: {v.message}")

    print(f"\nTotal: {total}  Violations: {violations}  "
          f"Pass rate: {(total-violations)/max(total,1)*100:.1f}%")


def _cmd_report(path: str = "") -> None:
    """
    从 CIEU + Omission 数据生成完整的治理日报。

    数据来源优先级：
      1. 有 path 参数 → 读指定 DB
      2. 无 path → 读 .ystar_session.json 里的 cieu_db 路径
    """
    import pathlib as _pl

    # 解析 DB 路径
    if path:
        cieu_db_path = str(path)
        omission_db  = str(path).replace(".db", "_omission.db")
    else:
        # 从 session 配置读取
        try:
            import json as _j
            cfg = _j.load(open(".ystar_session.json", encoding="utf-8"))
            cieu_db_path = cfg.get("cieu_db", ".ystar_cieu.db")
            omission_db  = cieu_db_path.replace(".db", "_omission.db")
        except Exception:
            cieu_db_path = ".ystar_cieu.db"
            omission_db  = ".ystar_cieu_omission.db"

    try:
        from ystar.governance.omission_store import OmissionStore, InMemoryOmissionStore
        from ystar.governance.cieu_store import CIEUStore
        from ystar.governance.reporting import ReportEngine

        # 优先读持久化 OmissionStore，没有就用内存版
        if _pl.Path(omission_db).exists():
            omission_store = OmissionStore(db_path=omission_db)
        else:
            omission_store = InMemoryOmissionStore()

        # 读 CIEUStore（统一日志，补全 omission + intervention 数据）
        cieu_store = None
        if _pl.Path(cieu_db_path).exists():
            cieu_store = CIEUStore(cieu_db_path)

        engine = ReportEngine(
            omission_store = omission_store,
            cieu_store     = cieu_store,
        )
        report = engine.daily_report()

        print()
        if hasattr(report, "to_markdown"):
            print(report.to_markdown())
        else:
            print(str(report))

        # 额外打印 HN 摘要
        try:
            from ystar.products.report_render import render_hn_summary
            print()
            print("─" * 50)
            print(render_hn_summary(report))
        except Exception:
            pass

    except Exception as e:
        print(f"Report error: {e}")


# ══════════════════════════════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return

    cmd  = args[0]
    rest = args[1:]

    if cmd == "setup":
        _cmd_setup()

    elif cmd == "hook-install":
        _cmd_hook_install()

    elif cmd == "init":
        _cmd_init()

    elif cmd == "audit":
        _cmd_audit(rest)

    elif cmd == "simulate":
        _cmd_simulate(rest)

    elif cmd == "quality":
        _cmd_quality(rest)

    elif cmd == "version":
        from ystar import __version__
        print(f"ystar {__version__}")

    elif cmd == "check":
        if not rest:
            print("Usage: ystar check <events.jsonl>"); sys.exit(1)
        _cmd_check(rest[0])

    elif cmd == "pretrain":
        _cmd_pretrain(rest)

    elif cmd == "report":
        _cmd_report(rest[0] if rest else "")

    else:
        print(f"未知命令: {cmd}\n{__doc__}")
        sys.exit(1)



# ══════════════════════════════════════════════════════════════════════
#  ystar setup — 生成 .ystar_session.json
# ══════════════════════════════════════════════════════════════════════

def _cmd_setup() -> None:
    """
    交互式生成 .ystar_session.json。
    这是 enforce() 完整治理链路（check + CIEU + omission）的必要配置文件。
    """
    import pathlib, json, uuid

    print()
    print("  Y* Session 配置生成")
    print("  " + "─" * 40)
    print()
    print("  此命令将在当前目录生成 .ystar_session.json")
    print("  Y* hook 启动时自动读取此文件，开启完整治理链路。")
    print()

    # 项目名称 → session_id
    default_name = pathlib.Path.cwd().name
    project = input(f"  项目名称 [{default_name}]: ").strip() or default_name
    session_id = f"{project}_{uuid.uuid4().hex[:8]}"

    # CIEU 数据库路径
    cieu_db = input(f"  CIEU 审计库路径 [.ystar_cieu.db]: ").strip() or ".ystar_cieu.db"

    # 合约：禁止路径
    print()
    print("  禁止访问的路径（逗号分隔，直接回车使用默认值）:")
    raw_deny = input("  [/etc,/root,/production]: ").strip()
    deny_paths = [p.strip() for p in raw_deny.split(",") if p.strip()]         if raw_deny else ["/etc", "/root", "/production"]

    # 合约：禁止命令
    print("  禁止执行的命令（逗号分隔）:")
    raw_cmds = input("  [rm -rf,sudo,DROP TABLE]: ").strip()
    deny_cmds = [c.strip() for c in raw_cmds.split(",") if c.strip()]         if raw_cmds else ["rm -rf", "sudo", "DROP TABLE"]

    # 义务时限
    print()
    print("  义务时限配置（秒，0=不启用）:")
    complaint_secs = input("  respond_to_complaint [300]: ").strip()
    try:
        complaint_timeout = float(complaint_secs) if complaint_secs else 300.0
    except ValueError:
        complaint_timeout = 300.0

    obligation_timing = {}
    if complaint_timeout > 0:
        obligation_timing["respond_to_complaint"] = complaint_timeout

    session_config = {
        "session_id": session_id,
        "cieu_db":    cieu_db,
        "contract": {
            "name":               f"{project}_policy",
            "deny":               deny_paths,
            "deny_commands":      deny_cmds,
            "obligation_timing":  obligation_timing,
        }
    }

    out_path = pathlib.Path(".ystar_session.json")
    out_path.write_text(json.dumps(session_config, ensure_ascii=False, indent=2))

    print()
    print(f"  ✅ 已生成 {out_path}")
    print(f"     session_id: {session_id}")
    print(f"     cieu_db:    {cieu_db}")
    print(f"     deny:       {deny_paths}")
    print(f"     commands:   {deny_cmds}")
    if obligation_timing:
        print(f"     义务时限:   {obligation_timing}")
    print()
    print("  下一步: ystar hook-install")
    print()


# ══════════════════════════════════════════════════════════════════════
#  ystar hook-install — 写入 OpenClaw hook 配置
# ══════════════════════════════════════════════════════════════════════

def _cmd_hook_install() -> None:
    """
    在 ~/.claude/settings.json 中注册 Y* 的 PreToolUse hook。
    已有 hooks 配置时自动合并，不会覆盖其他 hook。
    v0.41: 安装后自动发测试 payload 验证 hook 响应正确。
    """
    import pathlib, json, sys

    print()
    print("  Y* Hook 安装")
    print("  " + "─" * 40)
    print()

    # v0.41: 检测所有可能的配置路径，不只是 ~/.claude/settings.json
    candidate_paths = [
        pathlib.Path.home() / ".claude" / "settings.json",
        pathlib.Path.home() / ".config" / "openclaw" / "openclaw.json",
        pathlib.Path.home() / "Library" / "Application Support" / "Claude" / "settings.json",
    ]

    # 找已存在的配置文件
    settings_path = None
    for p in candidate_paths:
        if p.exists():
            settings_path = p
            print(f"  Found existing config: {p}")
            break
    if settings_path is None:
        settings_path = candidate_paths[0]  # 默认用 ~/.claude/settings.json
        print(f"  No existing config found, will create: {settings_path}")

    # 构建 hook 命令
    python_exec = sys.executable

    # Windows Git Bash fix: convert backslashes to forward slashes
    # Git Bash converts C:\path to /c/path (MSYS path conversion)
    # Using forward slashes works on both Windows and Unix
    if sys.platform == "win32":
        python_exec = python_exec.replace("\\", "/")

    hook_script = (
        "import json,sys;"
        "from ystar import Policy;"
        "from ystar.adapters.hook import check_hook;"
        "p=json.loads(sys.stdin.read());"
        "policy=Policy.from_agents_md('AGENTS.md') if __import__('pathlib').Path('AGENTS.md').exists() "
        "else Policy({});"
        "r=check_hook(p,policy);"
        "print(json.dumps(r))"
    )

    ystar_hook = {
        "type":    "command",
        "command": f"MSYS_NO_PATHCONV=1 {python_exec} -c '{hook_script}'",
    }

    hook_entry = {
        "matcher": "",
        "hooks":   [ystar_hook],
    }

    # 读取现有 settings.json
    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except Exception:
            existing = {}

    # 检查是否已安装
    existing_hooks = existing.get("hooks", {})
    pre_tool_use   = existing_hooks.get("PreToolUse", [])
    already_installed = any(
        "ystar" in str(h.get("hooks", []))
        for h in pre_tool_use
        if isinstance(h, dict)
    )

    if already_installed:
        print("  ℹ  Y* hook 已安装，无需重复操作。")
        print(f"     配置文件: {settings_path}")
    else:
        pre_tool_use.insert(0, hook_entry)
        existing.setdefault("hooks", {})["PreToolUse"] = pre_tool_use
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
        print(f"  ✅ Hook 已写入 {settings_path}")

    # v0.41: 安装后自验证——发送测试 payload
    print()
    print("  [自验证] 发送测试 payload...")
    try:
        from ystar.kernel.dimensions import IntentContract
        from ystar.session import Policy
        from ystar.adapters.hook import check_hook
        from unittest.mock import patch

        ic = IntentContract(deny=["/etc"], deny_commands=["rm -rf"])
        policy = Policy({"test_agent": ic})
        bad_payload  = {"tool_name": "Read", "tool_input": {"path": "/etc/passwd"},
                        "agent_id": "test_agent", "session_id": "install_test"}
        good_payload = {"tool_name": "Read", "tool_input": {"path": "/workspace/ok.py"},
                        "agent_id": "test_agent", "session_id": "install_test"}

        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            bad_result  = check_hook(bad_payload, policy, agent_id="test_agent")
            good_result = check_hook(good_payload, policy, agent_id="test_agent")

        if bad_result.get("action") == "block" and good_result == {}:
            print("  ✅ 自验证通过：/etc/passwd 被正确拦截，/workspace/ok.py 放行")
        else:
            print("  ⚠️  自验证结果异常:")
            print(f"     /etc/passwd → {bad_result}")
            print(f"     /workspace/ → {good_result}")
    except Exception as e:
        print(f"  ⚠️  自验证跳过: {e}")

    print()
    print("  ✅ 安装完成。重启 Claude Code / OpenClaw 后生效。")
    print()


if __name__ == "__main__":
    main()





def _cmd_init() -> None:
    """
    Interactive onboarding — generates a ready-to-run policy.py in 3 questions.
    No Python knowledge required.
    """
    print()
    print("  Y* Policy Setup")
    print("  " + "─" * 40)
    print()

    # Q1: scenario
    print("  What are you building?")
    print("   1  Software team  (developer / ops / manager)")
    print("   2  Business team  (sales / finance / analyst)")
    print("   3  AI agents      (OpenClaw / multi-agent)")
    print("   4  Custom         (I'll define my own roles)")
    print()
    choice = input("  Choose 1-4 [1]: ").strip() or "1"

    scenario_templates = {
        "1": {"manager": "manager", "rd": "rd",      "ops": "ops"},
        "2": {"manager": "manager", "sales": "sales", "finance": "finance"},
        "3": {"manager": "manager", "agent": "openclaw_agent"},
        "4": {},
    }
    agent_names = scenario_templates.get(choice, scenario_templates["1"])

    # Q2: custom roles (if choice 4)
    if choice == "4":
        print()
        print("  Enter your role names (comma-separated):")
        raw = input("  Roles [admin, user]: ").strip() or "admin, user"
        for name in [r.strip() for r in raw.split(",") if r.strip()]:
            agent_names[name] = "readonly"   # safe default

    # Q3: output path
    print()
    out = input("  Save policy to [./policy.py]: ").strip() or "./policy.py"

    # Generate policy.py
    import pathlib
    lines = [
        '"""',
        'Y* Policy — generated by `ystar init`',
        'Edit the from_template({...}) values to match your rules.',
        '"""',
        "from ystar import Policy, from_template",
        "from ystar.templates import get_template",
        "",
        "",
        "policy = Policy({",
    ]
    for role, tpl_name in agent_names.items():
        lines.append(f'    # {role}: based on built-in "{tpl_name}" template')
        lines.append(f'    "{role}": get_template("{tpl_name}"),')
        lines.append(f'    # Or customise:')
        lines.append(f'    # "{role}": from_template({{')
        lines.append(f'    #     "can_write_to":  ["./workspace/"],')
        lines.append(f'    #     "cannot_touch":  [".env", "production"],')
        lines.append(f'    #     "cannot_run":    ["rm -rf", "DELETE FROM"],')
        lines.append(f'    #     "amount_limit":  10000,')
        lines.append(f'    # }}),')
    lines += [
        "})",
        "",
        "",
        'if __name__ == "__main__":',
        '    # Quick test — edit these to match your use case',
    ]
    for role in list(agent_names)[:1]:
        lines += [
            f'    result = policy.check("{role}", "write", path="./workspace/main.py")',
            f'    print(result.allowed, result.reason)',
            f'    result = policy.check("{role}", "write", path="./.env")',
            f'    print(result.allowed, result.reason)',
        ]

    output = "\n".join(lines) + "\n"
    pathlib.Path(out).write_text(output)
    print()
    print(f"  ✅ Created {out}")
    print()
    print("  Next steps:")
    print(f"   • Edit {out} to customise your rules")
    print( "   • Run:  python " + out)
    print( "   • Docs: https://github.com/liuhaotian2024-prog/K9Audit")
    print()

def main() -> None:
    # v0.41: 修复第二个 main() 缺少命令分发的 bug（原 bug：setup/hook-install/doctor/verify 全部报 Unknown command）
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return

    cmd  = args[0]
    rest = args[1:]  # v0.41 fix: rest 未定义导致 pretrain 崩溃

    if cmd == "setup":
        _cmd_setup()

    elif cmd == "hook-install":
        _cmd_hook_install()

    elif cmd == "init":
        _cmd_init()

    elif cmd == "version":
        from ystar import __version__
        print(f"ystar {__version__}")

    elif cmd == "check":
        if not rest:
            print("Usage: ystar check <events.jsonl>"); sys.exit(1)
        _cmd_check(rest[0])

    elif cmd == "pretrain":
        _cmd_pretrain(rest)

    elif cmd == "report":
        if not rest:
            print("Usage: ystar report [--db <path>] [--format json|text]")
            sys.exit(1)
        _cmd_report_enhanced(rest)

    elif cmd == "audit":
        _cmd_audit(rest)

    elif cmd == "simulate":
        _cmd_simulate(rest)

    elif cmd == "quality":
        _cmd_quality(rest)

    elif cmd == "doctor":
        _cmd_doctor(rest)

    elif cmd == "verify":
        _cmd_verify(rest)

    elif cmd == "policy-builder":
        _cmd_policy_builder()

    elif cmd == "seal":
        _cmd_seal(rest)

    else:
        print(f"Unknown command: {cmd}\n")
        print("Available commands: setup, hook-install, doctor, verify, report,")
        print("                    seal, policy-builder, audit, check, init, version")
        sys.exit(1)


def _cmd_check(path: str) -> None:
    import json, pathlib
    from ystar import IntentContract, check
    events_path = pathlib.Path(path)
    if not events_path.exists():
        print(f"File not found: {path}"); sys.exit(1)

    violations = 0
    total = 0
    for line in events_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        params = rec.get("params", rec)
        contract_def = rec.get("contract", {})
        c = IntentContract(**{k: v for k, v in contract_def.items()
                              if k in ("deny","only_paths","deny_commands",
                                       "only_domains","invariant")})
        r = check(params, {}, c)
        total += 1
        if not r.passed:
            violations += 1
            for v in r.violations:
                print(f"VIOLATION  {v.dimension}: {v.message}")

    print(f"\nTotal: {total}  Violations: {violations}  "
          f"Pass rate: {(total-violations)/max(total,1)*100:.1f}%")


def _cmd_report(path: str) -> None:
    import pathlib
    db_path = pathlib.Path(path)
    if not db_path.exists():
        print(f"DB not found: {path}"); sys.exit(1)
    try:
        from ystar.governance.omission_store import OmissionStore
        from ystar.governance.reporting import ReportEngine
        store = OmissionStore(db_path=str(db_path))
        engine = ReportEngine(omission_store=store)
        report = engine.daily_report()
        print(report.to_markdown() if hasattr(report,"to_markdown") else str(report))
    except Exception as e:
        print(f"Report error: {e}")



# ══════════════════════════════════════════════════════════════════════
#  ystar setup — 生成 .ystar_session.json
# ══════════════════════════════════════════════════════════════════════

def _cmd_setup() -> None:
    """
    交互式生成 .ystar_session.json。
    这是 enforce() 完整治理链路（check + CIEU + omission）的必要配置文件。
    """
    import pathlib, json, uuid

    print()
    print("  Y* Session 配置生成")
    print("  " + "─" * 40)
    print()
    print("  此命令将在当前目录生成 .ystar_session.json")
    print("  Y* hook 启动时自动读取此文件，开启完整治理链路。")
    print()

    # 项目名称 → session_id
    default_name = pathlib.Path.cwd().name
    project = input(f"  项目名称 [{default_name}]: ").strip() or default_name
    session_id = f"{project}_{uuid.uuid4().hex[:8]}"

    # CIEU 数据库路径
    cieu_db = input(f"  CIEU 审计库路径 [.ystar_cieu.db]: ").strip() or ".ystar_cieu.db"

    # 合约：禁止路径
    print()
    print("  禁止访问的路径（逗号分隔，直接回车使用默认值）:")
    raw_deny = input("  [/etc,/root,/production]: ").strip()
    deny_paths = [p.strip() for p in raw_deny.split(",") if p.strip()]         if raw_deny else ["/etc", "/root", "/production"]

    # 合约：禁止命令
    print("  禁止执行的命令（逗号分隔）:")
    raw_cmds = input("  [rm -rf,sudo,DROP TABLE]: ").strip()
    deny_cmds = [c.strip() for c in raw_cmds.split(",") if c.strip()]         if raw_cmds else ["rm -rf", "sudo", "DROP TABLE"]

    # 义务时限
    print()
    print("  义务时限配置（秒，0=不启用）:")
    complaint_secs = input("  respond_to_complaint [300]: ").strip()
    try:
        complaint_timeout = float(complaint_secs) if complaint_secs else 300.0
    except ValueError:
        complaint_timeout = 300.0

    obligation_timing = {}
    if complaint_timeout > 0:
        obligation_timing["respond_to_complaint"] = complaint_timeout

    session_config = {
        "session_id": session_id,
        "cieu_db":    cieu_db,
        "contract": {
            "name":               f"{project}_policy",
            "deny":               deny_paths,
            "deny_commands":      deny_cmds,
            "obligation_timing":  obligation_timing,
        }
    }

    out_path = pathlib.Path(".ystar_session.json")
    out_path.write_text(json.dumps(session_config, ensure_ascii=False, indent=2))

    print()
    print(f"  ✅ 已生成 {out_path}")
    print(f"     session_id: {session_id}")
    print(f"     cieu_db:    {cieu_db}")
    print(f"     deny:       {deny_paths}")
    print(f"     commands:   {deny_cmds}")
    if obligation_timing:
        print(f"     义务时限:   {obligation_timing}")
    print()
    print("  下一步: ystar hook-install")
    print()


# ══════════════════════════════════════════════════════════════════════
#  ystar hook-install — 写入 OpenClaw hook 配置
# ══════════════════════════════════════════════════════════════════════

def _cmd_hook_install() -> None:
    """
    在 ~/.claude/settings.json 中注册 Y* 的 PreToolUse hook。
    已有 hooks 配置时自动合并，不会覆盖其他 hook。
    """
    import pathlib, json, sys

    print()
    print("  Y* Hook 安装")
    print("  " + "─" * 40)
    print()

    settings_path = pathlib.Path.home() / ".claude" / "settings.json"

    # 构建 hook 命令
    python_exec = sys.executable

    # Windows Git Bash fix: convert backslashes to forward slashes
    # Git Bash converts C:\path to /c/path (MSYS path conversion)
    # Using forward slashes works on both Windows and Unix
    if sys.platform == "win32":
        python_exec = python_exec.replace("\\", "/")

    hook_script = (
        "import json,sys;"
        "from ystar import Policy;"
        "from ystar.adapters.hook import check_hook;"
        "p=json.loads(sys.stdin.read());"
        "policy=Policy.from_agents_md('AGENTS.md') if __import__('pathlib').Path('AGENTS.md').exists() "
        "else Policy({});"
        "r=check_hook(p,policy);"
        "print(json.dumps(r))"
    )

    ystar_hook = {
        "type":    "command",
        "command": f"MSYS_NO_PATHCONV=1 {python_exec} -c '{hook_script}'",
    }

    hook_entry = {
        "matcher": "",
        "hooks":   [ystar_hook],
    }

    # 读取现有 settings.json（如果存在）
    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except Exception:
            existing = {}

    # 检查是否已安装
    existing_hooks = existing.get("hooks", {})
    pre_tool_use   = existing_hooks.get("PreToolUse", [])

    already_installed = any(
        "ystar" in str(h.get("hooks", []))
        for h in pre_tool_use
        if isinstance(h, dict)
    )

    if already_installed:
        print("  ℹ  Y* hook 已安装，无需重复操作。")
        print(f"     配置文件: {settings_path}")
        print()
        return

    # 合并：在 PreToolUse 列表前插入 ystar hook
    pre_tool_use.insert(0, hook_entry)
    existing.setdefault("hooks", {})["PreToolUse"] = pre_tool_use

    # 确保目录存在
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))

    print(f"  ✅ Hook 已写入 {settings_path}")
    print()
    print("  配置内容（PreToolUse 条目）:")
    print('    matcher: "" （匹配所有工具调用）')
    print(f'    command: {python_exec} -c "...ystar check_hook..."')
    print()
    print("  ✅ 安装完成。重启 OpenClaw 后生效。")
    print()
    print("  验证：在 OpenClaw 里运行任意命令，如果看到")
    print("  [Y*] 开头的提示说明 hook 正常工作。")
    print()


if __name__ == "__main__":
    main()



def _cmd_pretrain(args: list) -> None:
    """
    ystar pretrain — 运行完整预训练管道

    用法：
        ystar pretrain                   # 用默认数据运行
        ystar pretrain --jsonl <path>    # 指定 JSONL 路径
        ystar pretrain --days <N>        # 扫描最近 N 天历史

    输出：
        pretrain/outputs/pretrain_result_v5.json
        更新 ystar/pretrain/loader.py
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl",  default=None, help="JSONL 数据路径")
    parser.add_argument("--days",   type=int, default=30)
    parser.add_argument("--quiet",  action="store_true")
    parsed = parser.parse_args(args)

    try:
        import subprocess, sys, os
        pipeline = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "pretrain", "run_full_pretrain_pipeline.py"
        )
        if not os.path.exists(pipeline):
            print("❌ pretrain/run_full_pretrain_pipeline.py 不存在")
            print("   请确保完整安装了 ystar（包含 pretrain/ 目录）")
            return
        env = dict(os.environ)
        result = subprocess.run(
            [sys.executable, pipeline],
            env=env,
            capture_output=parsed.quiet
        )
        if result.returncode != 0 and parsed.quiet:
            print("❌ 预训练失败，运行 ystar pretrain 查看详情")
        elif result.returncode == 0 and parsed.quiet:
            from ystar.pretrain import pretrain_summary
            print(f"✅ {pretrain_summary()}")
    except Exception as e:
        print(f"❌ 预训练错误: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# v0.41 新增命令实现
# ══════════════════════════════════════════════════════════════════════════════

def _cmd_doctor(args: list) -> None:
    """
    ystar doctor — 诊断当前环境的完整性
    检查：session config / hook 注册 / CIEU 可写 / omission 配置
    """
    import json, pathlib, os

    ok_count = 0
    fail_count = 0

    def ok(msg):
        nonlocal ok_count
        print(f"  ✅ {msg}")
        ok_count += 1

    def fail(msg, hint=""):
        nonlocal fail_count
        print(f"  ❌ {msg}")
        if hint:
            print(f"     → {hint}")
        fail_count += 1

    def warn(msg):
        print(f"  ⚠️  {msg}")

    print()
    print("  Y*gov Doctor — 环境诊断")
    print("  ─────────────────────────────────────────")
    print()

    # ── 1. 检查 session config ──────────────────────────────────────────
    print("  [1] Session Config")
    session_cfg = None
    for search_dir in [os.getcwd(), str(pathlib.Path.home())]:
        p = pathlib.Path(search_dir) / ".ystar_session.json"
        if p.exists():
            try:
                session_cfg = json.loads(p.read_text())
                ok(f".ystar_session.json found at {p}")
                break
            except Exception as e:
                fail(f".ystar_session.json found but invalid JSON: {e}",
                     "Run: ystar setup --yes")
    if session_cfg is None:
        fail(".ystar_session.json not found",
             "Run: ystar setup --yes")

    # ── 2. 检查 hook 注册 ────────────────────────────────────────────────
    print()
    print("  [2] Hook Registration")
    hook_locations = [
        pathlib.Path.home() / ".claude" / "settings.json",
        pathlib.Path.home() / ".config" / "openclaw" / "openclaw.json",
        pathlib.Path.home() / "Library" / "Application Support" / "Claude" / "settings.json",
    ]
    hook_found = False
    for loc in hook_locations:
        if loc.exists():
            try:
                cfg = json.loads(loc.read_text())
                hooks_obj = cfg.get("hooks", {})
                if "ystar" in __import__("json").dumps(hooks_obj).lower():
                    ok(f"Hook registered in {loc}")
                    hook_found = True
                    break
                else:
                    warn(f"{loc} exists but no ystar hook found")
            except Exception:
                warn(f"Could not parse {loc}")
    if not hook_found:
        fail("No ystar hook registered in any config location",
             "Run: ystar hook-install")

    # ── 3. 检查 CIEU 数据库可写 ──────────────────────────────────────────
    print()
    print("  [3] CIEU Database")
    cieu_path = ".ystar_cieu.db"
    if session_cfg:
        cieu_path = session_cfg.get("cieu_db", cieu_path)
    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(cieu_path)
        stats = store.stats()
        ok(f"CIEU database accessible: {stats['total']} records at {cieu_path}")
        if stats["total"] > 0:
            ok(f"  allow={stats['by_decision'].get('allow',0)}  "
               f"deny={stats['by_decision'].get('deny',0)}  "
               f"deny_rate={stats.get('deny_rate',0):.1%}")
    except Exception as e:
        fail(f"CIEU database not accessible: {e}",
             f"Check path: {cieu_path}")

    # ── 4. 检查 AGENTS.md ────────────────────────────────────────────────
    print()
    print("  [4] AGENTS.md")
    agents_md = pathlib.Path("AGENTS.md")
    if agents_md.exists():
        lines = agents_md.read_text().splitlines()
        ok(f"AGENTS.md found ({len(lines)} lines)")
        has_deny = any("never" in l.lower() or "deny" in l.lower() or "- /" in l for l in lines)
        if has_deny:
            ok("AGENTS.md contains constraint rules")
        else:
            warn("AGENTS.md exists but may have no constraint rules")
    else:
        fail("AGENTS.md not found in current directory",
             "Create AGENTS.md with your governance rules")

    # ── 5. 自检 hook payload ──────────────────────────────────────────────
    print()
    print("  [5] Hook Self-Test")
    try:
        from ystar.kernel.dimensions import IntentContract
        from ystar.session import Policy
        from ystar.adapters.hook import check_hook
        from unittest.mock import patch

        ic = IntentContract(deny=["/etc"], deny_commands=["rm -rf"])
        policy = Policy({"doctor_agent": ic})
        test_payload = {"tool_name": "Read",
                        "tool_input": {"path": "/etc/passwd"},
                        "agent_id": "doctor_agent",
                        "session_id": "doctor_test"}
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook(test_payload, policy, agent_id="doctor_agent")
        if result.get("action") == "block":
            ok("Hook self-test passed: /etc/passwd correctly blocked")
        else:
            fail("Hook self-test failed: /etc/passwd was NOT blocked",
                 "Check your AGENTS.md and session config")
    except Exception as e:
        fail(f"Hook self-test error: {e}")

    # ── 汇总 ─────────────────────────────────────────────────────────────
    print()
    print("  ─────────────────────────────────────────")
    if fail_count == 0:
        print(f"  ✅ All {ok_count} checks passed — Y*gov is healthy")
    else:
        print(f"  ⚠️  {ok_count} passed, {fail_count} failed")
        print("     Run the suggested commands above to fix issues")
    print()


def _cmd_verify(args: list) -> None:
    """
    ystar verify [--db <path>] [--session <id>]
    验证 CIEU 数据库的密码学完整性
    """
    import argparse, json

    parser = argparse.ArgumentParser(prog="ystar verify")
    parser.add_argument("--db", default=".ystar_cieu.db", help="CIEU 数据库路径")
    parser.add_argument("--session", default=None, help="指定 session_id（默认检查所有已封印的）")
    parser.add_argument("--seal", action="store_true", help="验证前先封印")
    parsed = parser.parse_args(args)

    print()
    print("  Y*gov Verify — CIEU 完整性验证")
    print("  ─────────────────────────────────────────")
    print()

    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(parsed.db)
        stats = store.stats()
        print(f"  Database: {parsed.db}")
        print(f"  Total records: {stats['total']}")
        print()

        if parsed.seal or parsed.session:
            target = parsed.session or "default"
            if parsed.seal:
                print(f"  Sealing session '{target}'...")
                seal_result = store.seal_session(target)
                if seal_result.get("event_count", 0) == 0:
                    print(f"  ⚠️  No records found for session '{target}'")
                else:
                    print(f"  ✅ Sealed: {seal_result['event_count']} events")
                    print(f"     Merkle root: {seal_result['merkle_root'][:32]}...")
                    if seal_result.get("prev_root"):
                        print(f"     Chain link:  {seal_result['prev_root'][:32]}...")
                print()

            if parsed.session:
                print(f"  Verifying session '{parsed.session}'...")
                v = store.verify_session_seal(parsed.session)
                if v.get("valid"):
                    print(f"  ✅ Integrity OK: {v.get('stored_count',0)} events verified")
                    print(f"     Root: {v.get('stored_root','?')[:32]}...")
                else:
                    print(f"  ❌ INTEGRITY FAILURE")
                    print(f"     Expected: {v.get('stored_root','?')[:32]}...")
                    print(f"     Computed: {v.get('computed_root','?')[:32]}...")
                    if v.get("count_mismatch"):
                        print(f"     Record count mismatch: stored={v.get('stored_count')} "
                              f"current={v.get('current_count')}")
        else:
            print("  Usage examples:")
            print("    ystar verify --db .ystar_cieu.db --seal --session my_session")
            print("    ystar verify --db .ystar_cieu.db --session my_session")
            print()
            print("  Tip: use 'ystar seal' to auto-seal the current session")

    except Exception as e:
        print(f"  ❌ Error: {e}")
    print()


def _cmd_seal(args: list) -> None:
    """
    ystar seal [--db <path>] [--session <id>]
    封印当前 session 的 CIEU 记录，生成 Merkle root
    """
    import argparse, json, pathlib

    parser = argparse.ArgumentParser(prog="ystar seal")
    parser.add_argument("--db", default=None, help="CIEU 数据库路径")
    parser.add_argument("--session", default=None, help="Session ID")
    parsed = parser.parse_args(args)

    # 从 session config 读取默认值
    db_path = parsed.db
    session_id = parsed.session
    if not db_path or not session_id:
        for d in [pathlib.Path.cwd(), pathlib.Path.home()]:
            cfg_path = d / ".ystar_session.json"
            if cfg_path.exists():
                try:
                    cfg = json.loads(cfg_path.read_text())
                    db_path = db_path or cfg.get("cieu_db", ".ystar_cieu.db")
                    session_id = session_id or cfg.get("session_id", "default")
                    break
                except Exception:
                    pass
    db_path = db_path or ".ystar_cieu.db"
    session_id = session_id or "default"

    print()
    print("  Y*gov Seal — 封印 CIEU 记录")
    print(f"  Database: {db_path}")
    print(f"  Session:  {session_id}")
    print()

    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(db_path)
        result = store.seal_session(session_id)

        if result.get("event_count", 0) == 0:
            print(f"  ⚠️  No records found for session '{session_id}'")
        else:
            print(f"  ✅ Sealed {result['event_count']} events")
            print(f"     Merkle root: {result['merkle_root']}")
            if result.get("prev_root"):
                print(f"     Chain prev:  {result['prev_root'][:32]}...")
            print()
            print("  Run 'ystar verify --session {session_id}' to confirm integrity")
    except Exception as e:
        print(f"  ❌ Seal failed: {e}")
    print()


def _cmd_report_enhanced(args: list) -> None:
    """
    ystar report [--db <path>] [--format json|text|md]
    v0.41 增强版报告：完整的 CIEU telemetry 分析
    """
    import argparse, json

    parser = argparse.ArgumentParser(prog="ystar report")
    parser.add_argument("--db", default=".ystar_cieu.db")
    parser.add_argument("--format", default="text", choices=["text", "json", "md"])
    parser.add_argument("positional", nargs="?", default=None,
                        help="DB 路径（兼容旧版：ystar report path.db）")
    parsed = parser.parse_args(args)

    db_path = parsed.positional or parsed.db

    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(db_path)
        stats = store.stats()
    except Exception as e:
        print(f"❌ Cannot open database: {e}")
        return

    total = stats.get("total", 0)
    if total == 0:
        print("No CIEU records found.")
        return

    by_decision = stats.get("by_decision", {})
    allow_n = by_decision.get("allow", 0)
    deny_n  = by_decision.get("deny", 0)
    esc_n   = by_decision.get("escalate", 0)

    # ── 路径频率分析（从数据库查询）──────────────────────────────────────
    top_blocked = []
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT COALESCE(file_path, command, url, 'unknown') as target,
                   COUNT(*) as cnt
            FROM cieu_events
            WHERE decision = 'deny'
            GROUP BY target
            ORDER BY cnt DESC
            LIMIT 10
        """).fetchall()
        top_blocked = [(r["target"], r["cnt"]) for r in rows]

        # 义务超时分析
        omission_rows = conn.execute("""
            SELECT event_type, COUNT(*) as cnt
            FROM cieu_events
            WHERE event_type LIKE '%omission%' OR event_type LIKE '%overdue%'
               OR event_type LIKE '%violation%'
            GROUP BY event_type
            ORDER BY cnt DESC
            LIMIT 10
        """).fetchall()
        omission_stats = [(r["event_type"], r["cnt"]) for r in omission_rows]

        # agent 分布
        agent_rows = conn.execute("""
            SELECT agent_id, COUNT(*) as total,
                   SUM(CASE WHEN decision='deny' THEN 1 ELSE 0 END) as denied
            FROM cieu_events
            GROUP BY agent_id
            ORDER BY total DESC
            LIMIT 10
        """).fetchall()
        agent_stats = [(r["agent_id"], r["total"], r["denied"]) for r in agent_rows]
        conn.close()
    except Exception:
        top_blocked = []
        omission_stats = []
        agent_stats = []

    if parsed.format == "json":
        output = {
            "total": total,
            "allow": allow_n,
            "deny": deny_n,
            "escalate": esc_n,
            "deny_rate": round(deny_n / max(total, 1), 3),
            "top_blocked_paths": [{"path": p, "count": c} for p, c in top_blocked],
            "omission_events": [{"type": t, "count": c} for t, c in omission_stats],
            "agents": [{"id": a, "total": t, "denied": d} for a, t, d in agent_stats],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    # text / md 输出
    sep = "─" * 50
    h = "##" if parsed.format == "md" else " "

    print()
    print(f"{h} Y*gov CIEU Report — {db_path}")
    print(sep)
    print(f"  Total decisions : {total:,}")
    print(f"  Allow           : {allow_n:,}  ({allow_n/max(total,1):.1%})")
    print(f"  Deny            : {deny_n:,}   ({deny_n/max(total,1):.1%})")
    if esc_n:
        print(f"  Escalate        : {esc_n:,}  ({esc_n/max(total,1):.1%})")

    if top_blocked:
        print()
        print(f"{h} Top Blocked Paths/Commands")
        print(sep)
        for path, cnt in top_blocked:
            bar = "█" * min(cnt, 30)
            print(f"  {cnt:5d}  {bar}  {path[:60]}")

    if agent_stats:
        print()
        print(f"{h} By Agent")
        print(sep)
        print(f"  {'Agent':<30} {'Total':>8} {'Denied':>8} {'Deny%':>7}")
        for agent_id, total_a, denied_a in agent_stats:
            pct = f"{denied_a/max(total_a,1):.0%}"
            print(f"  {agent_id:<30} {total_a:>8,} {denied_a:>8,} {pct:>7}")

    if omission_stats:
        print()
        print(f"{h} Omission / Obligation Events")
        print(sep)
        for etype, cnt in omission_stats:
            print(f"  {cnt:5d}  {etype}")

    print()


def _cmd_policy_builder() -> None:
    """
    ystar policy-builder
    在本地启动 Policy Builder UI（单文件 HTML，无外部依赖）
    """
    import pathlib, webbrowser, http.server, threading, os

    # 找 policy-builder.html
    candidates = [
        pathlib.Path(__file__).parent / "policy-builder.html",
        pathlib.Path(__file__).parent.parent / "policy-builder.html",
    ]
    html_path = None
    for c in candidates:
        if c.exists():
            html_path = c
            break

    if not html_path:
        print("❌ policy-builder.html not found in ystar package.")
        print("   You can find it at: https://github.com/liuhaotian2024-prog/Y-star-gov")
        return

    PORT = 7921
    os.chdir(html_path.parent)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args): pass  # 静默日志

    def serve():
        with http.server.HTTPServer(("", PORT), Handler) as httpd:
            httpd.serve_forever()

    t = threading.Thread(target=serve, daemon=True)
    t.start()

    url = f"http://localhost:{PORT}/{html_path.name}"
    print()
    print(f"  Y*gov Policy Builder — http://localhost:{PORT}/{html_path.name}")
    print("  ─────────────────────────────────────────")
    print("  Build your IntentContract visually, then copy the generated")
    print("  Python code into your AGENTS.md or session config.")
    print()
    print("  Press Ctrl+C to stop the server.")
    print()

    webbrowser.open(url)
    try:
        t.join()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
