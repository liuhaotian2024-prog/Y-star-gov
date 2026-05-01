from __future__ import annotations

from typing import Any, Dict


def _text(item_dict: Dict[str, Any]) -> str:
    parts = []
    for key, value in item_dict.items():
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}={value}")
        elif isinstance(value, (list, tuple, set)):
            parts.extend(str(v) for v in value)
    return " ".join(parts).lower()


def classify_m_triangle_alignment(item_dict: Dict[str, Any]) -> Dict[str, Any]:
    text = _text(item_dict)
    m1 = any(k in text for k in ["survivability", "backup", "recovery", "uptime", "identity continuity", "m-1"])
    m2 = any(k in text for k in ["governance", "deterministic", "cieu", "approval", "audit", "permission", "escalation", "m-2"])
    m3 = any(k in text for k in ["revenue", "customer", "paid", "first cash", "sales", "user", "feedback", "pilot", "value production", "m-3"])

    if m3:
        primary = "M-3 Value Production"
        explanation = "Item directly supports customers, revenue, feedback, or paid validation."
    elif m2:
        primary = "M-2 Governability"
        explanation = "Item supports auditability, permissioning, deterministic enforcement, or approval gates."
    elif m1:
        primary = "M-1 Survivability"
        explanation = "Item supports continuity, backup, recovery, or persistence."
    else:
        primary = "unclear"
        explanation = "No clear M Triangle alignment found; owner or mission context should decide."

    return {
        "m1": m1,
        "m2": m2,
        "m3": m3,
        "primary": primary,
        "explanation": explanation,
    }


def value_production_relevance(item_dict: Dict[str, Any]) -> Dict[str, Any]:
    text = _text(item_dict)
    if any(k in text for k in ["paid", "revenue", "first cash", "customer", "pilot", "sales", "external user", "user interview", "feedback"]):
        score = "HIGH"
        reason = "Direct customer/revenue/feedback relevance."
    elif any(k in text for k in ["product", "delivery", "test baseline", "install", "demo", "pricing", "offer"]):
        score = "MEDIUM"
        reason = "Supports deliverability or commercialization but is not itself cash validation."
    elif any(k in text for k in ["daily report", "weekly report", "cadence", "admin", "ceremony", "internal summary"]):
        score = "LOW"
        reason = "Administrative ceremony has low M-3 relevance unless bound to a live mission."
    else:
        score = "UNKNOWN"
        reason = "Value-production relevance is unclear from the item alone."
    return {"relevance": score, "reason": reason, "executes_action": False}

