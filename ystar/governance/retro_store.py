# ystar/governance/retro_store.py
# Copyright (C) 2026 Haotian Liu — MIT License
"""
ystar.governance.retro_store  —  追溯基线存储  v0.41.0
=======================================================

字节污染防护设计
─────────────────
RetroBaselineStore 与 CIEUStore 是完全独立的存储系统：
  - 独立数据库文件：.ystar_retro_baseline.db（不是 .ystar_cieu.db）
  - 独立表结构：retro_assessments（不是 cieu_events）
  - 无 seal_session() / verify_session_seal()（追溯数据不需要密码学封印）
  - 所有记录永久标注 source="retroactive"

这确保：
  1. 实时 CIEU 的 SHA-256 哈希链不受任何追溯数据影响
  2. 追溯记录永远无法被误认为是实时记录
  3. 合规审计员可以清楚区分"Y* 实时监控的"和"追溯分析的"

治理层职责：
  - 持久化追溯评估结果
  - 提供统计查询（ContractQuality / DimensionDiscovery 的数据来源）
  - 锚定追溯基线（供后续 delta 分析使用）
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


_DEFAULT_DB_NAME = ".ystar_retro_baseline.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS retro_assessments (
    -- 主键
    rowid        INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id    TEXT    NOT NULL UNIQUE,    -- UUID

    -- 来源信息（溯源用）
    source_file  TEXT    NOT NULL,           -- 来自哪个 .jsonl 文件
    session_id   TEXT    NOT NULL,           -- Claude Code 会话 UUID
    created_at   REAL    NOT NULL,           -- 原始操作时间（Unix timestamp）
    scanned_at   REAL    NOT NULL,           -- 扫描时间

    -- 工具调用信息
    tool_name    TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,
    params_json  TEXT,                       -- 传给 check() 的参数快照

    -- 评估结果
    passed       INTEGER NOT NULL DEFAULT 0, -- 1=pass 0=deny
    decision     TEXT    NOT NULL,           -- allow / deny
    violations   TEXT,                       -- JSON array

    -- 追溯标注（永远是 retroactive）
    source       TEXT    NOT NULL DEFAULT 'retroactive',

    -- 基线批次（同一次 ystar init 扫描的记录归同一批次）
    baseline_id  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retro_session   ON retro_assessments(session_id);
CREATE INDEX IF NOT EXISTS idx_retro_baseline  ON retro_assessments(baseline_id);
CREATE INDEX IF NOT EXISTS idx_retro_decision  ON retro_assessments(decision);
CREATE INDEX IF NOT EXISTS idx_retro_tool      ON retro_assessments(tool_name);

-- 基线元数据：每次扫描的摘要
CREATE TABLE IF NOT EXISTS retro_baselines (
    baseline_id   TEXT    PRIMARY KEY,
    created_at    REAL    NOT NULL,
    total_records INTEGER NOT NULL DEFAULT 0,
    allow_count   INTEGER NOT NULL DEFAULT 0,
    deny_count    INTEGER NOT NULL DEFAULT 0,
    date_range    TEXT    NOT NULL DEFAULT '',
    contract_hash TEXT,                      -- 评估时使用的合约哈希
    notes         TEXT                       -- 用于说明这次基线的来源
);
"""


class RetroBaselineStore:
    """
    追溯基线存储。

    完全独立于 CIEUStore，防止实时审计链被污染。

    使用方式：
        store = RetroBaselineStore()  # 默认在当前目录
        store = RetroBaselineStore(".ystar_retro_baseline.db")
        store = RetroBaselineStore(":memory:")  # 测试用

        baseline_id = store.begin_baseline(contract_hash="sha256:abc...")
        store.write_assessments(assessments, baseline_id)
        summary = store.get_baseline_summary(baseline_id)
    """

    def __init__(self, db_path: str = _DEFAULT_DB_NAME) -> None:
        self._is_memory = (db_path == ":memory:")
        self.db_path    = Path(db_path) if not self._is_memory else Path(":memory:")
        self._mem_conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        if self._is_memory:
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.executescript(_SCHEMA)
            self._mem_conn.commit()
        else:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        if self._is_memory:
            conn = self._mem_conn
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        else:
            conn = sqlite3.connect(str(self.db_path), timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    # ── 基线管理 ──────────────────────────────────────────────────────────

    def begin_baseline(
        self,
        contract_hash: str = "",
        notes: str = "",
    ) -> str:
        """开始一次新的追溯基线扫描，返回 baseline_id。"""
        baseline_id = str(uuid.uuid4())[:12]
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO retro_baselines "
                "(baseline_id, created_at, contract_hash, notes) "
                "VALUES (?, ?, ?, ?)",
                (baseline_id, time.time(), contract_hash, notes)
            )
        return baseline_id

    def write_assessments(
        self,
        assessments: List[Any],   # List[RetroAssessment]
        baseline_id: str,
    ) -> int:
        """批量写入追溯评估结果，返回实际写入条数。"""
        scanned_at = time.time()
        written    = 0

        with self._conn() as conn:
            for a in assessments:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO retro_assessments "
                        "(record_id, source_file, session_id, created_at, scanned_at, "
                        " tool_name, event_type, params_json, "
                        " passed, decision, violations, source, baseline_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'retroactive', ?)",
                        (
                            str(uuid.uuid4()),
                            a.source_file,
                            a.session_id,
                            a.timestamp,
                            scanned_at,
                            a.tool_name,
                            a.event_type,
                            json.dumps(a.params),
                            1 if a.passed else 0,
                            a.decision,
                            json.dumps(a.violations),
                            baseline_id,
                        )
                    )
                    written += 1
                except sqlite3.IntegrityError:
                    pass  # 重复记录跳过

            # 更新基线摘要
            allow_n = sum(1 for a in assessments if a.passed)
            deny_n  = len(assessments) - allow_n
            date_range = ""
            ts_list = [a.timestamp for a in assessments if a.timestamp > 0]
            if ts_list:
                import datetime
                oldest = datetime.datetime.fromtimestamp(min(ts_list)).strftime("%Y-%m-%d")
                newest = datetime.datetime.fromtimestamp(max(ts_list)).strftime("%Y-%m-%d")
                date_range = f"{oldest} → {newest}"

            conn.execute(
                "UPDATE retro_baselines SET "
                "total_records=?, allow_count=?, deny_count=?, date_range=? "
                "WHERE baseline_id=?",
                (len(assessments), allow_n, deny_n, date_range, baseline_id)
            )

        return written

    # ── 查询 ──────────────────────────────────────────────────────────────

    def get_baseline_summary(self, baseline_id: str) -> Optional[Dict[str, Any]]:
        """获取指定基线的摘要。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM retro_baselines WHERE baseline_id=?",
                (baseline_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_latest_baseline_id(self) -> Optional[str]:
        """获取最新一次基线的 ID。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT baseline_id FROM retro_baselines "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return row["baseline_id"] if row else None

    def stats(self, baseline_id: Optional[str] = None) -> Dict[str, Any]:
        """统计追溯评估数据（用于 ContractQuality / DimensionDiscovery）。"""
        with self._conn() as conn:
            cond   = "WHERE baseline_id=?" if baseline_id else ""
            params = (baseline_id,) if baseline_id else ()

            total = conn.execute(
                f"SELECT COUNT(*) FROM retro_assessments {cond}", params
            ).fetchone()[0]

            by_decision = {}
            for row in conn.execute(
                f"SELECT decision, COUNT(*) FROM retro_assessments {cond} "
                f"GROUP BY decision", params
            ).fetchall():
                by_decision[row[0]] = row[1]

            by_tool = {}
            for row in conn.execute(
                f"SELECT tool_name, COUNT(*) FROM retro_assessments {cond} "
                f"GROUP BY tool_name ORDER BY COUNT(*) DESC LIMIT 10", params
            ).fetchall():
                by_tool[row[0]] = row[1]

            # 违规维度统计（需要解析 JSON）
            viol_filter = ("AND" if baseline_id else "WHERE") + \
                          " violations IS NOT NULL AND violations != '[]'"
            viol_records = conn.execute(
                f"SELECT violations FROM retro_assessments {cond} {viol_filter}",
                params
            ).fetchall()

        from collections import Counter
        dim_counter: Counter = Counter()
        for row in viol_records:
            try:
                for v in json.loads(row[0]):
                    dim = v.get("dimension", "")
                    if dim and dim != "phantom_variable":
                        dim_counter[dim] += 1
            except Exception:
                pass

        return {
            "total":           total,
            "by_decision":     by_decision,
            "by_tool":         by_tool,
            "top_violations":  dim_counter.most_common(8),
            "source":          "retroactive",   # 永远标注来源
        }

    def as_call_records(
        self,
        baseline_id: Optional[str] = None,
        limit: int = 500,
    ) -> List[Any]:
        """
        把追溯评估结果转换为 CallRecord 格式，
        供 ContractQuality.evaluate() 和 DimensionDiscovery.analyze() 使用。

        注意：返回的 CallRecord 里 intent_contract 是空合约，
        violations 是用当前合约回放得到的结果，
        调用方需要了解这是追溯数据。
        """
        from ystar.governance.metalearning import CallRecord
        from ystar.kernel.dimensions import IntentContract

        empty_contract = IntentContract()
        call_records   = []

        with self._conn() as conn:
            cond   = "WHERE baseline_id=?" if baseline_id else ""
            params_q = (baseline_id,) if baseline_id else ()
            rows = conn.execute(
                f"SELECT tool_name, event_type, params_json, violations "
                f"FROM retro_assessments {cond} "
                f"ORDER BY created_at LIMIT ?",
                (*params_q, limit)
            ).fetchall()

        for i, row in enumerate(rows):
            try:
                params     = json.loads(row["params_json"] or "{}")
                violations = json.loads(row["violations"]  or "[]")
                # 把 violation dict 转成 Violation 对象
                from ystar.kernel.engine import Violation
                viol_objs = [
                    Violation(
                        dimension=v.get("dimension", ""),
                        field="",
                        message=v.get("message", ""),
                        severity=0.8,
                    )
                    for v in violations
                ]
                call_records.append(CallRecord(
                    seq=i,
                    func_name=row["event_type"] or row["tool_name"],
                    params=params,
                    result={},
                    violations=viol_objs,
                    intent_contract=empty_contract,
                ))
            except Exception:
                pass

        return call_records

    def count(self) -> int:
        """返回追溯评估记录总数。"""
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM retro_assessments"
            ).fetchone()[0]
