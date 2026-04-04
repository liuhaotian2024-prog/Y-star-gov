# Layer: Foundation
"""
ystar.cieu_store  —  CIEU Durable Backend (SQLite)
====================================================

JSONL append-only ログの限界を超えた、本番レベルの CIEU 永続化ストア。

なぜ SQLite か：
  - Python 標準ライブラリ（外部依存ゼロ）
  - WAL モードで concurrent write-safe
  - ACID 保証でクラッシュ安全
  - 全文検索（FTS5）でイベント検索
  - Y* のどの環境にも `pip install` なしで動く

使用方法：
    from ystar.governance.cieu_store import CIEUStore

    # デフォルト（.ystar_cieu.db）
    store = CIEUStore()
    store.write(rec)              # CIEU レコードを書き込む
    store.query("evil.com")       # キーワード検索
    store.stats()                 # 統計サマリー
    store.replay(session_id="x") # セッション再生
    store.export_jsonl("out.jsonl") # バックアップ

    # ystar-dev cieu persist の代わりに使う
    store.ingest_from_session()   # セッション内 CIEU を一括移行
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import sqlite3
import time
import uuid
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

_log = logging.getLogger(__name__)

_DEFAULT_DB = Path(".ystar_cieu.db")

# Size caps for raw snapshots — large payloads are truncated, never silently dropped.
_PARAMS_JSON_MAX_BYTES = 8_192   # 8 KB
_RESULT_JSON_MAX_BYTES = 4_096   # 4 KB

# ── SQLite スキーマ ────────────────────────────────────────────────────
_SCHEMA = """
PRAGMA journal_mode = WAL;        -- concurrent write-safe
PRAGMA synchronous  = NORMAL;     -- crash-safe, high performance

CREATE TABLE IF NOT EXISTS cieu_events (
    -- 主キー・順序
    rowid        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT    NOT NULL UNIQUE,    -- UUID (dedup key)
    seq_global   INTEGER NOT NULL,           -- μs timestamp (global order)
    created_at   REAL    NOT NULL,           -- Unix timestamp

    -- エージェント・セッション
    session_id   TEXT    NOT NULL,
    agent_id     TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,

    -- 決定
    decision     TEXT    NOT NULL,           -- allow / deny / escalate
    passed       INTEGER NOT NULL DEFAULT 0, -- 1=passed, 0=violated

    -- 違反・ドリフト
    violations   TEXT,                       -- JSON array
    drift_detected INTEGER NOT NULL DEFAULT 0,
    drift_details TEXT,
    drift_category TEXT,

    -- 対象
    file_path    TEXT,
    command      TEXT,
    url          TEXT,
    skill_name   TEXT,
    skill_source TEXT,
    task_description TEXT,

    -- 合約
    contract_hash TEXT,
    chain_depth   INTEGER DEFAULT 0,

    -- [FIX-1] 完整调用现场快照 ─────────────────────────────────────────
    -- params_json: 原始输入参数的 JSON 快照（上限 8KB，超出截断并标注）
    -- result_json: 函数返回值的 JSON 快照（上限 4KB）
    -- human_initiator: 触发此调用的人工操作者 ID（满足合规追溯要求）
    -- lineage_path: 完整委托链路径，JSON array，如 ["owner","manager","rd"]
    params_json       TEXT,
    result_json       TEXT,
    human_initiator   TEXT,
    lineage_path      TEXT,

    -- 監査
    sealed       INTEGER NOT NULL DEFAULT 0  -- 1=sealed (tamper-evident)
);

-- 高速検索インデックス
CREATE INDEX IF NOT EXISTS idx_session  ON cieu_events(session_id);
CREATE INDEX IF NOT EXISTS idx_agent    ON cieu_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_decision ON cieu_events(decision);
CREATE INDEX IF NOT EXISTS idx_created  ON cieu_events(created_at);
CREATE INDEX IF NOT EXISTS idx_event_type ON cieu_events(event_type);

-- 全文検索（FTS5）
CREATE VIRTUAL TABLE IF NOT EXISTS cieu_fts USING fts5(
    event_id UNINDEXED,
    session_id,
    agent_id,
    event_type,
    decision,
    file_path,
    command,
    url,
    task_description,
    violations,
    drift_details,
    content     = 'cieu_events',
    content_rowid = 'rowid'
);

-- FTS 同期トリガー
CREATE TRIGGER IF NOT EXISTS cieu_ai AFTER INSERT ON cieu_events BEGIN
    INSERT INTO cieu_fts(rowid, event_id, session_id, agent_id, event_type,
                          decision, file_path, command, url,
                          task_description, violations, drift_details)
    VALUES (new.rowid, new.event_id, new.session_id, new.agent_id,
            new.event_type, new.decision, new.file_path, new.command,
            new.url, new.task_description, new.violations, new.drift_details);
END;

-- [FIX-3] 封印会话的密码学证明表 ──────────────────────────────────────
-- 每次 seal_session() 在此写入一行，包含该 session 所有 event_id 的
-- Merkle root（SHA-256），并链接到前一次封印的 root，形成哈希链。
-- 这使 sealed 从"逻辑标记"升级为"可独立验证的密码学承诺"。
CREATE TABLE IF NOT EXISTS sealed_sessions (
    session_id   TEXT    PRIMARY KEY,
    sealed_at    REAL    NOT NULL,           -- Unix timestamp
    event_count  INTEGER NOT NULL,           -- 封印时的事件数量
    merkle_root  TEXT    NOT NULL,           -- SHA-256(sorted event_ids)
    prev_root    TEXT,                       -- 前一次封印的 merkle_root（哈希链）
    db_path      TEXT                        -- 记录来自哪个 DB 文件
);
"""

# 新列列表：用于对已有 DB 做无损迁移（ALTER TABLE ADD COLUMN 幂等）
_NEW_COLUMNS = [
    ("params_json",     "TEXT"),
    ("result_json",     "TEXT"),
    ("human_initiator", "TEXT"),
    ("lineage_path",    "TEXT"),
    ("evidence_grade",  "TEXT DEFAULT 'decision'"),
]


@dataclass
class CIEUQueryResult:
    """クエリ結果の一行。"""
    event_id:         str
    seq_global:       int
    created_at:       float
    session_id:       str
    agent_id:         str
    event_type:       str
    decision:         str
    violations:       List[dict]
    drift_detected:   bool
    drift_details:    Optional[str]
    file_path:        Optional[str]
    command:          Optional[str]
    url:              Optional[str]
    # [FIX-1] 新增审计字段
    params_json:      Optional[str] = None   # 原始输入参数快照
    result_json:      Optional[str] = None   # 返回值快照
    human_initiator:  Optional[str] = None   # 人工操作者
    lineage_path:     Optional[str] = None   # 完整委托链（JSON array）
    # [P2-3] 证据分级
    evidence_grade:   str = "decision"       # decision / governance / advisory / ops

    def display(self) -> str:
        ts  = time.strftime("%m-%d %H:%M:%S", time.localtime(self.created_at))
        dec = self.decision
        tgt = self.file_path or self.command or self.url or self.event_type
        viol_str = f"  [{self.violations[0]['dimension']}]" if self.violations else ""
        human_str = f"  by={self.human_initiator}" if self.human_initiator else ""
        return f"{ts}  {dec:10} {self.agent_id[:15]:16} {tgt[:35]}{viol_str}{human_str}"


class CIEUStore:
    """
    Y* CIEU の SQLite-backed 永続化ストア。

    特徴：
    - WAL モード（同時書き込み安全）
    - ACID（クラッシュ後も整合性保証）
    - FTS5 全文検索
    - event_id による重複排除
    - [FIX-1] params_json / result_json / human_initiator / lineage_path — 完整调用现场
    - [FIX-3] seal_session() — 基于 SHA-256 Merkle root 的密码学封印，形成哈希链
    """

    def __init__(self, db_path: str = str(_DEFAULT_DB)):
        self.db_path = Path(db_path)
        # [FIX] SQLite :memory: creates a fresh empty DB for every new connection.
        # For in-memory databases we keep one persistent connection for the
        # lifetime of the store object; for file-backed DBs we open/close per op.
        self._is_memory = (str(db_path) == ":memory:")
        self._mem_conn: Optional[sqlite3.Connection] = None
        if self._is_memory:
            import sqlite3 as _sq3
            self._mem_conn = _sq3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            # [FIX-1] 对已有列做无损迁移，在同一连接内执行（:memory: DB 安全）
            existing = {row[1] for row in conn.execute("PRAGMA table_info(cieu_events)")}
            for col_name, col_type in _NEW_COLUMNS:
                if col_name not in existing:
                    conn.execute(
                        f"ALTER TABLE cieu_events ADD COLUMN {col_name} {col_type}"
                    )

    def _migrate_db(self) -> None:
        """已合并入 _init_db，保留此方法供外部工具显式调用。"""
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        if self._is_memory:
            # Yield the persistent in-memory connection; never close it.
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

    # ── [FIX-1] JSON 快照辅助 ─────────────────────────────────────────

    @staticmethod
    def _sanitize_json(value: Any, max_bytes: int) -> Optional[str]:
        """
        将任意值序列化为 JSON 字符串，并做以下处理：
        1. 非 JSON 可序列化的值转为 str()
        2. 超过 max_bytes 截断，并在末尾注明 [TRUNCATED]
        3. 如果 value 为 None 或空 dict/list，返回 None（不写库）
        """
        if value is None:
            return None
        if isinstance(value, dict) and not value:
            return None
        try:
            raw = json.dumps(value, default=str, ensure_ascii=False)
        except Exception as e:
            _log.warning("JSON serialization failed for snapshot, using str(): %s", e)
            raw = str(value)
        if len(raw.encode()) > max_bytes:
            # 截断到字节上限后注明
            truncated = raw.encode()[:max_bytes].decode(errors="ignore")
            return truncated + ' [TRUNCATED]'
        return raw

    # ── 書き込み ──────────────────────────────────────────────────────

    def write(self, record: Any) -> bool:
        """
        CIEU レコードを永続化する（どのアダプタから送られたものでも受け付ける）。

        event_id による重複排除あり（二重書き込みは無視）。
        Returns True if written, False if duplicate.
        """
        try:
            d = record.to_dict() if hasattr(record, 'to_dict') else record
            self._insert_dict(d)
            return True
        except sqlite3.IntegrityError:
            # Duplicate event_id — expected behavior, not an error
            return False

    def write_dict(self, d: dict) -> bool:
        """dict 形式の CIEU レコードを書き込む（JSONL からの移行用）。"""
        try:
            self._insert_dict(d)
            return True
        except sqlite3.IntegrityError:
            # Duplicate event_id — expected behavior, not an error
            return False

    def _insert_dict(self, d: dict) -> None:
        violations_raw = d.get("violations", [])
        # Guard: if violations is already a JSON string, don't double-encode
        if isinstance(violations_raw, str):
            violations_json = violations_raw
        else:
            violations_json = json.dumps(violations_raw)
        # [FIX-1] 提取新审计字段
        params_json   = self._sanitize_json(d.get("params"),  _PARAMS_JSON_MAX_BYTES)
        result_json   = self._sanitize_json(d.get("result"),  _RESULT_JSON_MAX_BYTES)
        human_init    = d.get("human_initiator") or d.get("human_user")
        lineage_raw   = d.get("lineage_path") or d.get("lineage")
        lineage_json  = (
            json.dumps(lineage_raw) if isinstance(lineage_raw, list)
            else lineage_raw  # 已是 JSON 字符串则直接存
        ) if lineage_raw else None
        # [P2-3] 证据分级
        evidence_grade = d.get("evidence_grade", "decision")

        with self._conn() as conn:
            conn.execute("""
                INSERT INTO cieu_events
                    (event_id, seq_global, created_at,
                     session_id, agent_id, event_type,
                     decision, passed,
                     violations, drift_detected, drift_details, drift_category,
                     file_path, command, url, skill_name, skill_source,
                     task_description, contract_hash, chain_depth,
                     params_json, result_json, human_initiator, lineage_path,
                     evidence_grade)
                VALUES
                    (?, ?, ?,   ?, ?, ?,   ?, ?,   ?, ?, ?, ?,
                     ?, ?, ?, ?, ?,   ?, ?, ?,
                     ?, ?, ?, ?,
                     ?)
            """, (
                d.get("event_id") or str(uuid.uuid4()),
                d.get("seq_global") or int(time.time() * 1_000_000),
                d.get("created_at") or d.get("timestamp") or time.time(),
                d.get("session_id", ""),
                d.get("agent_id", ""),
                d.get("event_type", ""),
                d.get("decision", "unknown"),
                1 if d.get("passed", True) else 0,
                violations_json,
                1 if d.get("drift_detected") else 0,
                d.get("drift_details"),
                d.get("drift_category"),
                d.get("file_path") or d.get("file"),
                d.get("command"),
                d.get("url"),
                d.get("skill_name"),
                d.get("skill_source"),
                d.get("task_description"),
                d.get("contract_hash"),
                d.get("chain_depth", 0),
                params_json,
                result_json,
                human_init,
                lineage_json,
                evidence_grade,
            ))

    def ingest_from_session(
        self,
        clear_after: bool = False,
        log_provider: Optional[Any] = None,
        clear_provider: Optional[Any] = None,
    ) -> int:
        """
        セッション内の CIEU ログ（メモリ内）を DB に移行する。
        ystar-dev cieu persist の高信頼版。

        P0 修復: CIEUStore は Governance Services 層であり、
        Ecosystem Adapter を直接 import してはならない（アーキテクチャ境界）。
        log_provider / clear_provider を注入することで依存方向を逆転する。

        使用方法（任意の適配層から呼ぶ場合）:
            store.ingest_from_session(
                log_provider=get_cieu_log,     # 適配層が提供する関数
                clear_provider=clear_cieu_log, # 適配層が提供する関数
            )

        log_provider を省略した場合、後方互換のため lazy import を試みる。
        """
        if log_provider is None:
            # log_provider が省略された場合は何もしない（fail-safe）。
            # 呼び出し側が log_provider を明示的に注入すること。
            # 例: store.ingest_from_session(log_provider=get_cieu_log)
            # CIEUStore はいかなる適配層も直接 import しない（アーキテクチャ境界）。
            return 0

        log     = log_provider()
        written = 0
        for rec in log:
            if self.write(rec):
                written += 1
        if clear_after and clear_provider:
            clear_provider()
        return written

    def ingest_from_jsonl(self, path: str) -> int:
        """既存の JSONL ファイルを SQLite に移行する。"""
        p = Path(path)
        if not p.exists():
            return 0
        written = 0
        for line in p.read_text().splitlines():
            try:
                d = json.loads(line)
                if self.write_dict(d):
                    written += 1
            except Exception as e:
                _log.warning("Failed to parse JSONL line during ingest: %s", e)
                pass
        return written

    # ── 検索・クエリ ──────────────────────────────────────────────────

    def query(
        self,
        keyword:   Optional[str] = None,
        session_id: Optional[str] = None,
        agent_id:   Optional[str] = None,
        decision:   Optional[str] = None,
        event_type: Optional[str] = None,
        since:      Optional[float] = None,  # Unix timestamp
        limit:      int = 50,
    ) -> List[CIEUQueryResult]:
        """
        多条件検索。keyword は FTS5 全文検索を使用。
        """
        if keyword:
            return self._fts_query(keyword, decision, agent_id, limit)

        conditions = []
        params: List[Any] = []

        if session_id:
            conditions.append("session_id = ?"); params.append(session_id)
        if agent_id:
            conditions.append("agent_id = ?");   params.append(agent_id)
        if decision:
            conditions.append("decision = ?");   params.append(decision)
        if event_type:
            conditions.append("event_type = ?"); params.append(event_type)
        if since:
            conditions.append("created_at >= ?"); params.append(since)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM cieu_events
                {where}
                ORDER BY seq_global DESC
                LIMIT ?
            """, params).fetchall()

        return [self._row_to_result(r) for r in rows]

    def _fts_query(
        self,
        keyword: str,
        decision: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[CIEUQueryResult]:
        """FTS5 全文検索。特殊文字を自動エスケープ。"""
        # FTS5 の特殊文字をエスケープ（"." "/" などが構文エラーになるため）
        import re as _re
        safe_keyword = _re.sub(r'[^a-zA-Z0-9]', ' ', keyword).strip()
        if not safe_keyword:
            return []
        conditions = ["cieu_fts MATCH ?"]
        params: List[Any] = [safe_keyword]
        if decision:
            conditions.append("e.decision = ?"); params.append(decision)
        if agent_id:
            conditions.append("e.agent_id = ?"); params.append(agent_id)
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT e.* FROM cieu_events e
                JOIN cieu_fts ON cieu_fts.event_id = e.event_id
                WHERE {' AND '.join(conditions)}
                ORDER BY e.seq_global DESC
                LIMIT ?
            """, params).fetchall()

        return [self._row_to_result(r) for r in rows]

    def _row_to_result(self, row: sqlite3.Row) -> CIEUQueryResult:
        try:
            violations = json.loads(row["violations"] or "[]")
        except Exception as e:
            _log.warning("Failed to parse violations JSON in query result: %s", e)
            violations = []
        # Safely access new columns — may be absent in very old DBs
        def _safe(col: str) -> Optional[str]:
            try:
                return row[col]
            except IndexError:
                # Column not present in old schema — expected
                return None
        return CIEUQueryResult(
            event_id        = row["event_id"],
            seq_global      = row["seq_global"],
            created_at      = row["created_at"],
            session_id      = row["session_id"],
            agent_id        = row["agent_id"],
            event_type      = row["event_type"],
            decision        = row["decision"],
            violations      = violations,
            drift_detected  = bool(row["drift_detected"]),
            drift_details   = row["drift_details"],
            file_path       = row["file_path"],
            command         = row["command"],
            url             = row["url"],
            params_json     = _safe("params_json"),
            result_json     = _safe("result_json"),
            human_initiator = _safe("human_initiator"),
            lineage_path    = _safe("lineage_path"),
            evidence_grade  = _safe("evidence_grade") or "decision",
        )

    # ── 統計 ──────────────────────────────────────────────────────────

    def stats(
        self,
        since: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """
        CIEU ログの統計サマリー。

        Returns:
            total, by_decision, by_event_type, top_violations,
            drift_rate, escalation_rate, deny_rate, sessions
        """
        where_parts = []
        params: List[Any] = []
        if since:
            where_parts.append("created_at >= ?"); params.append(since)
        if session_id:
            where_parts.append("session_id = ?"); params.append(session_id)
        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        with self._conn() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM cieu_events {where}", params
            ).fetchone()[0]

            by_decision = dict(conn.execute(
                f"SELECT decision, COUNT(*) FROM cieu_events {where} "
                f"GROUP BY decision", params
            ).fetchall())

            by_event_type = dict(conn.execute(
                f"SELECT event_type, COUNT(*) FROM cieu_events {where} "
                f"GROUP BY event_type ORDER BY COUNT(*) DESC LIMIT 10", params
            ).fetchall())

            drift_sql = f"SELECT COUNT(*) FROM cieu_events {where} " + (
                "AND drift_detected=1" if where else "WHERE drift_detected=1"
            )
            drift_count = conn.execute(drift_sql, params).fetchone()[0] if total else 0

            # 違反次元のカウント（JSONを解析）
            all_viols: Dict[str, int] = {}
            # 当已有 WHERE 子句时，用 AND 追加；否则用 WHERE
            viol_filter = ("AND" if where else "WHERE") + \
                          " violations IS NOT NULL AND violations != '[]'"
            rows = conn.execute(
                f"SELECT violations FROM cieu_events {where} {viol_filter}", params
            ).fetchall()
            for row in rows:
                try:
                    parsed = json.loads(row[0])
                    # Handle double-encoded data: json.dumps(str(list))
                    # produces a JSON string whose value is a Python repr.
                    if isinstance(parsed, str):
                        try:
                            parsed = ast.literal_eval(parsed)
                        except (ValueError, SyntaxError):
                            continue
                    for v in parsed:
                        if isinstance(v, dict):
                            dim = v.get("dimension", "")
                            if dim and dim != "phantom_variable":
                                all_viols[dim] = all_viols.get(dim, 0) + 1
                except Exception as e:
                    _log.warning("Failed to parse violation data in stats: %s", e)

            sessions = conn.execute(
                f"SELECT COUNT(DISTINCT session_id) FROM cieu_events {where}", params
            ).fetchone()[0]

        deny_n  = by_decision.get("deny", 0)
        esc_n   = by_decision.get("escalate", 0)

        return {
            "total":           total,
            "sessions":        sessions,
            "by_decision":     by_decision,
            "by_event_type":   by_event_type,
            "top_violations":  sorted(all_viols.items(), key=lambda x: -x[1])[:10],
            "drift_count":     drift_count,
            "drift_rate":      round(drift_count / total, 3) if total else 0,
            "deny_rate":       round(deny_n / total, 3) if total else 0,
            "escalation_rate": round(esc_n / total, 3) if total else 0,
        }

    # ── [FIX-3] 密码学封印（Merkle root 哈希链） ──────────────────────

    def seal_session(self, session_id: str) -> dict:
        """
        [FIX-3] 对指定 session 的所有记录进行密码学封印。

        做两件事：
        1. 将该 session 所有行的 sealed 标志置为 1（逻辑标记，向后兼容）。
        2. 计算该 session 所有 event_id（按 seq_global 排序）的 SHA-256，
           写入 sealed_sessions 表，并链接到上一次封印的 merkle_root。

        这使封印从"逻辑标记"升级为"可独立验证的密码学承诺"：
        - 任何人持有 event_id 列表即可重算 merkle_root 验证完整性。
        - prev_root 形成哈希链，防止历史记录被整体替换。

        Returns dict with:
            session_id, event_count, merkle_root, prev_root, sealed_at
        """
        now = time.time()

        with self._conn() as conn:
            # 1. 获取该 session 所有 event_id，按 seq_global 排序
            rows = conn.execute(
                "SELECT event_id FROM cieu_events "
                "WHERE session_id = ? ORDER BY seq_global ASC",
                (session_id,)
            ).fetchall()

            event_ids = [r["event_id"] for r in rows]
            event_count = len(event_ids)

            if event_count == 0:
                return {
                    "session_id": session_id,
                    "event_count": 0,
                    "merkle_root": None,
                    "prev_root": None,
                    "sealed_at": now,
                    "warning": "no events found for this session",
                }

            # 2. 计算 merkle root：SHA-256(event_id_0 \n event_id_1 \n ...)
            payload = "\n".join(event_ids).encode("utf-8")
            merkle_root = hashlib.sha256(payload).hexdigest()

            # 3. 获取前一次封印的 root（哈希链连接）
            prev_row = conn.execute(
                "SELECT merkle_root FROM sealed_sessions ORDER BY sealed_at DESC LIMIT 1"
            ).fetchone()
            prev_root = prev_row["merkle_root"] if prev_row else None

            # 4. 写入 sealed_sessions（REPLACE 幂等：重复封印更新记录）
            conn.execute("""
                INSERT OR REPLACE INTO sealed_sessions
                    (session_id, sealed_at, event_count, merkle_root, prev_root, db_path)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, now, event_count, merkle_root, prev_root, str(self.db_path)))

            # 5. 更新逻辑 sealed 标志（向后兼容）
            conn.execute(
                "UPDATE cieu_events SET sealed=1 WHERE session_id=?",
                (session_id,)
            )

        return {
            "session_id":   session_id,
            "event_count":  event_count,
            "merkle_root":  merkle_root,
            "prev_root":    prev_root,
            "sealed_at":    now,
        }

    def verify_session_seal(self, session_id: str) -> dict:
        """
        [FIX-3] 验证某个 session 的封印完整性。

        重新计算当前 DB 中该 session 的 merkle_root，
        与 sealed_sessions 表中记录的 root 对比。

        Returns dict with:
            session_id, valid (bool), stored_root, computed_root,
            event_count, tamper_evidence (str if mismatch)
        """
        with self._conn() as conn:
            # 从 sealed_sessions 读取存档的 root
            seal_row = conn.execute(
                "SELECT * FROM sealed_sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()

            if seal_row is None:
                return {
                    "session_id": session_id,
                    "valid": False,
                    "error": "session has never been sealed",
                }

            stored_root  = seal_row["merkle_root"]
            stored_count = seal_row["event_count"]

            # 重新计算当前 event_ids
            rows = conn.execute(
                "SELECT event_id FROM cieu_events "
                "WHERE session_id = ? ORDER BY seq_global ASC",
                (session_id,)
            ).fetchall()
            current_ids   = [r["event_id"] for r in rows]
            current_count = len(current_ids)

            payload       = "\n".join(current_ids).encode("utf-8")
            computed_root = hashlib.sha256(payload).hexdigest()

        valid = (computed_root == stored_root)
        result: Dict[str, Any] = {
            "session_id":    session_id,
            "valid":         valid,
            "stored_root":   stored_root,
            "computed_root": computed_root,
            "stored_count":  stored_count,
            "current_count": current_count,
            "sealed_at":     seal_row["sealed_at"],
        }
        if not valid:
            if current_count != stored_count:
                result["tamper_evidence"] = (
                    f"event count mismatch: sealed={stored_count}, "
                    f"current={current_count} "
                    f"({'events added' if current_count > stored_count else 'events deleted'})"
                )
            else:
                result["tamper_evidence"] = (
                    "event_id content mismatch with same count "
                    "(possible event replacement)"
                )
        return result

    # ── エクスポート ──────────────────────────────────────────────────

    def export_jsonl(self, path: str, session_id: Optional[str] = None) -> int:
        """JSONL 形式でエクスポート（バックアップ・互換性）。"""
        conditions = []
        params: List[Any] = []
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM cieu_events {where} ORDER BY seq_global", params
            ).fetchall()

        written = 0
        with open(path, "w") as f:
            for row in rows:
                d = dict(row)
                try:
                    d["violations"] = json.loads(d.get("violations") or "[]")
                except Exception as e:
                    _log.warning("Failed to parse violations during JSONL export: %s", e)
                    d["violations"] = []
                f.write(json.dumps(d, default=str) + "\n")
                written += 1
        return written

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM cieu_events").fetchone()[0]

    # ── [P2-3] CIEU Evidence Grading ──────────────────────────────────────

    def count_by_grade(self, session_id: Optional[str] = None) -> dict:
        """
        [P2-3] 按证据分级统计 CIEU 事件数量。

        Returns: {"decision": 120, "governance": 8, "advisory": 5, "ops": 42}
        """
        where_parts = []
        params: List[Any] = []
        if session_id:
            where_parts.append("session_id = ?")
            params.append(session_id)
        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT evidence_grade, COUNT(*) FROM cieu_events {where} "
                f"GROUP BY evidence_grade", params
            ).fetchall()
            return dict(rows)

    def query_by_grade(
        self,
        grade: str,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[CIEUQueryResult]:
        """
        [P2-3] 按证据分级查询 CIEU 事件。

        Args:
            grade: "decision" | "governance" | "advisory" | "ops"
            session_id: 可选，过滤特定 session
            limit: 返回数量上限

        Returns: List[CIEUQueryResult]
        """
        conditions = ["evidence_grade = ?"]
        params: List[Any] = [grade]
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)

        where = "WHERE " + " AND ".join(conditions)
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM cieu_events
                {where}
                ORDER BY seq_global DESC
                LIMIT ?
            """, params).fetchall()

        return [self._row_to_result(r) for r in rows]

    def query_violations_by_agent(
        self,
        agent_id: str,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[CIEUQueryResult]:
        """
        查询特定 agent 的所有 violations（governance analysis 必备）。

        Args:
            agent_id: Agent identifier
            session_id: 可选，过滤特定 session
            limit: 返回数量上限

        Returns: List[CIEUQueryResult] 包含 violations 的事件
        """
        conditions = ["agent_id = ?", "passed = 0"]
        params: List[Any] = [agent_id]
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)

        where = "WHERE " + " AND ".join(conditions)
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM cieu_events
                {where}
                ORDER BY seq_global DESC
                LIMIT ?
            """, params).fetchall()

        return [self._row_to_result(r) for r in rows]

    def query_escalations(
        self,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[CIEUQueryResult]:
        """
        查询所有 escalation 决策（用于 governance health 分析）。

        Args:
            session_id: 可选，过滤特定 session
            limit: 返回数量上限

        Returns: List[CIEUQueryResult] decision = "escalate" 的事件
        """
        conditions = ["decision = 'escalate'"]
        params: List[Any] = []
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)

        where = "WHERE " + " AND ".join(conditions)
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM cieu_events
                {where}
                ORDER BY seq_global DESC
                LIMIT ?
            """, params).fetchall()

        return [self._row_to_result(r) for r in rows]

    def query_governance_actions(
        self,
        action_type: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[CIEUQueryResult]:
        """
        查询 governance 相关动作（omission, intervention, causal 等）。

        Args:
            action_type: 可选，过滤特定 event_type（如 "omission_violation", "intervention_pulse"）
            session_id: 可选，过滤特定 session
            limit: 返回数量上限

        Returns: List[CIEUQueryResult]
        """
        conditions = ["evidence_grade = 'governance'"]
        params: List[Any] = []
        if action_type:
            conditions.append("event_type = ?")
            params.append(action_type)
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)

        where = "WHERE " + " AND ".join(conditions)
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(f"""
                SELECT * FROM cieu_events
                {where}
                ORDER BY seq_global DESC
                LIMIT ?
            """, params).fetchall()

        return [self._row_to_result(r) for r in rows]


# ── [FIX-2] NullCIEUStore — 显式 no-op 替代 None ─────────────────────────
class NullCIEUStore:
    """
    [FIX-2] 空操作的 CIEUStore 替代品。

    用于取代 OmissionEngine / InterventionEngine 等组件中的 cieu_store=None 默认值。
    使用 NullCIEUStore 的好处：
    - 消除所有 `if self.cieu_store is None: return` 守卫
    - 保持接口一致（调用方不需要判断 None）
    - 明确"我知道不需要持久化"的意图，区别于"忘记配置"的意外 None

    注意：实例化时会发出 UserWarning，提醒开发者 CIEU 事件不会被持久化。
    如果你确实不需要持久化（如单元测试），可以 `warnings.filterwarnings("ignore", ...)`。
    """

    def __init__(self, silent: bool = False) -> None:
        if not silent:
            warnings.warn(
                "NullCIEUStore is active: CIEU events will NOT be persisted. "
                "Pass a real CIEUStore(db_path=...) to enable audit logging.",
                UserWarning,
                stacklevel=2,
            )

    def write(self, record: Any) -> bool:
        return False

    def write_dict(self, d: dict) -> bool:
        return False

    def query(self, **kwargs) -> list:
        return []

    def stats(self, **kwargs) -> dict:
        return {"total": 0, "note": "NullCIEUStore — no data persisted"}

    def seal_session(self, session_id: str) -> dict:
        return {"session_id": session_id, "event_count": 0, "merkle_root": None,
                "warning": "NullCIEUStore — nothing to seal"}

    def verify_session_seal(self, session_id: str) -> dict:
        return {"session_id": session_id, "valid": False,
                "error": "NullCIEUStore — no seal data"}

    def export_jsonl(self, path: str, session_id: Optional[str] = None) -> int:
        return 0

    def count(self) -> int:
        return 0

    def ingest_from_session(self, **kwargs) -> int:
        return 0

    def ingest_from_jsonl(self, path: str) -> int:
        return 0


# ── グローバルストア ──────────────────────────────────────────────────
_default_store: Optional[CIEUStore] = None

def get_store(db_path: str = str(_DEFAULT_DB)) -> CIEUStore:
    """デフォルトの CIEUStore を取得（シングルトン）。"""
    global _default_store
    if _default_store is None or str(_default_store.db_path) != db_path:
        _default_store = CIEUStore(db_path)
    return _default_store
