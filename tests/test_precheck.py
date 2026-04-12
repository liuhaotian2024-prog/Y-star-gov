"""Tests for governance precheck validation (governance-evolution spec).

Test scenarios:
1. CTO提交技术维度预检 → ALLOW
2. CTO提交"叙事清晰度"维度 → DENY (维度不匹配角色)
3. CMO提交叙事维度预检 → ALLOW
4. 预检assumption少于10字符 → DENY
5. Level 1指令不需要预检 → ALLOW (跳过验证)
6. conclusion="escalate" → 创建CEO义务 (handled by caller, not tested here)
7. 未知agent_id (无cognitive_profile) → ALLOW但带warning
8. 预检通过后CIEU记录存在 (integration test)
"""

import pytest
from ystar.governance.precheck import validate_precheck, PrecheckResult


# Fixture: sample cognitive profiles
@pytest.fixture
def cognitive_profiles():
    return {
        "cto": {
            "primary_dimensions": ["技术可行性", "系统稳定性", "架构合理性"],
            "primary_risks": ["技术故障", "性能退化", "依赖冲突", "测试不足"],
            "success_metrics": ["测试通过率", "安装成功率", "性能基线"]
        },
        "cmo": {
            "primary_dimensions": ["叙事清晰度", "受众匹配", "平台适配"],
            "primary_risks": ["叙事失败", "内容过长", "时机不对", "受众错位"],
            "success_metrics": ["点击率", "评论质量", "传播深度"]
        },
        "ceo": {
            "primary_dimensions": ["战略一致性", "跨部门协调", "执行节奏"],
            "primary_risks": ["方向偏移", "团队过载", "Board信任损耗"],
            "success_metrics": ["指令完成率", "CIEU健康分", "义务清零率"]
        }
    }


def test_cto_technical_dimension_allow(cognitive_profiles):
    """Test 1: CTO提交技术维度预检 → ALLOW"""
    result = validate_precheck(
        agent_id="cto",
        directive_level=2,
        primary_dimension="技术可行性",
        primary_risk="技术故障",
        assumption="系统可以在不重启服务的情况下升级依赖包",
        worst_case="升级失败导致服务不可用，需要回滚",
        cognitive_profiles=cognitive_profiles,
    )

    assert result.passed is True
    assert result.reason == "Precheck validated — matches cognitive profile"
    assert result.allowed_dimensions == ["技术可行性", "系统稳定性", "架构合理性"]
    assert result.allowed_risks == ["技术故障", "性能退化", "依赖冲突", "测试不足"]


def test_cto_wrong_dimension_deny(cognitive_profiles):
    """Test 2: CTO提交"叙事清晰度"维度 → DENY (维度不匹配角色)"""
    result = validate_precheck(
        agent_id="cto",
        directive_level=2,
        primary_dimension="叙事清晰度",  # This is CMO's dimension
        primary_risk="技术故障",
        assumption="这个技术方案需要用简单的叙事向Board解释",
        worst_case="Board不理解技术细节导致项目被拒",
        cognitive_profiles=cognitive_profiles,
    )

    assert result.passed is False
    assert "叙事清晰度" in result.reason
    assert "not in cto's cognitive profile" in result.reason
    assert "技术可行性" in str(result.allowed_dimensions)


def test_cmo_narrative_dimension_allow(cognitive_profiles):
    """Test 3: CMO提交叙事维度预检 → ALLOW"""
    result = validate_precheck(
        agent_id="cmo",
        directive_level=3,
        primary_dimension="叙事清晰度",
        primary_risk="叙事失败",
        assumption="目标受众对治理概念有基础理解",
        worst_case="文章太技术化导致目标受众看不懂",
        cognitive_profiles=cognitive_profiles,
    )

    assert result.passed is True
    assert result.reason == "Precheck validated — matches cognitive profile"


def test_assumption_too_short_deny(cognitive_profiles):
    """Test 4: 预检assumption少于10字符 → DENY"""
    result = validate_precheck(
        agent_id="cto",
        directive_level=2,
        primary_dimension="技术可行性",
        primary_risk="技术故障",
        assumption="可行",  # Only 2 chars
        worst_case="升级失败导致服务不可用",
        cognitive_profiles=cognitive_profiles,
    )

    assert result.passed is False
    assert "assumption too short" in result.reason
    assert "at least 10 characters" in result.reason


def test_level1_bypass_validation(cognitive_profiles):
    """Test 5: Level 1指令不需要预检 → ALLOW (跳过验证)"""
    result = validate_precheck(
        agent_id="cto",
        directive_level=1,  # Level 1 bypasses validation
        primary_dimension="WRONG_DIMENSION",  # Should be ignored
        primary_risk="WRONG_RISK",
        assumption="short",  # Should be ignored
        worst_case="也很短",
        cognitive_profiles=cognitive_profiles,
    )

    assert result.passed is True
    assert result.reason == "Level 1 directive — precheck not required"
    assert result.directive_level == 1


def test_unknown_agent_allow_with_warning(cognitive_profiles):
    """Test 7: 未知agent_id (无cognitive_profile) → ALLOW但带warning"""
    result = validate_precheck(
        agent_id="unknown_agent",  # Not in cognitive_profiles
        directive_level=2,
        primary_dimension="some_dimension",
        primary_risk="some_risk",
        assumption="This is a valid assumption text",
        worst_case="This is a valid worst case text",
        cognitive_profiles=cognitive_profiles,
    )

    assert result.passed is True
    assert "WARNING" in result.reason
    assert "No cognitive profile found" in result.reason
    assert "unknown_agent" in result.reason


def test_worst_case_too_short_deny(cognitive_profiles):
    """Test: worst_case少于10字符 → DENY"""
    result = validate_precheck(
        agent_id="ceo",
        directive_level=2,
        primary_dimension="战略一致性",
        primary_risk="方向偏移",
        assumption="团队能够在2周内完成3个高优先级任务",
        worst_case="失败",  # Only 2 chars
        cognitive_profiles=cognitive_profiles,
    )

    assert result.passed is False
    assert "worst_case too short" in result.reason


def test_wrong_risk_dimension_deny(cognitive_profiles):
    """Test: primary_risk不匹配角色 → DENY"""
    result = validate_precheck(
        agent_id="cto",
        directive_level=2,
        primary_dimension="技术可行性",
        primary_risk="叙事失败",  # This is CMO's risk
        assumption="系统升级需要向Board解释清楚",
        worst_case="Board不批准导致技术债累积",
        cognitive_profiles=cognitive_profiles,
    )

    assert result.passed is False
    assert "叙事失败" in result.reason
    assert "not in cto's cognitive profile" in result.reason
    assert "技术故障" in str(result.allowed_risks)


def test_precheck_result_conclusion_field():
    """Test: PrecheckResult包含conclusion字段"""
    result = PrecheckResult(
        passed=True,
        reason="test",
        allowed_dimensions=["dim1"],
        allowed_risks=["risk1"],
        agent_id="cto",
        directive_level=2,
        conclusion="escalate",
    )

    assert result.conclusion == "escalate"
    assert result.passed is True
