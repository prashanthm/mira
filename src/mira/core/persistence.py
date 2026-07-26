"""Durable local persistence for Mira — SQLite on a mounted volume, mirroring
the Vantage engine's db.py idiom (one _SCHEMA blob, a version constant, WAL,
additive ALTER migrations). Everything Mira learns or emits about an LLM call
lands here so it survives restarts and is queryable:

  * ``llm_calls``  — one row per model call at the gateway chokepoint: the
    request, the response, real token usage, cost, latency, agent/tier/op.
  * ``turns``      — one row per /turn or /analyze: the user input, the final
    reply (text + A2UI sections), routed domain, correlation_id.
  * ``kv``         — a durable key→value table backing IStateStore (thread
    checkpoints) so conversation memory survives restarts too.

Local infra was 100% RAM (no volume in compose) — this is the first durable
store in the service. Absent a data dir / disk, everything degrades to a
no-op in-memory shim so tests and the echo profile never require a file.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DB_FILENAME = "mira.db"
ENV_DATA_DIR = "MIRA_DATA_DIR"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- one row per LLM call at the gateway chokepoint (Gateway.complete/chat)
CREATE TABLE IF NOT EXISTS llm_calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT NOT NULL,          -- ISO8601
    op             TEXT,                   -- classify | turn_synthesis | analyze_synthesis | premortem | playbook | runtime_turn | ...
    agent          TEXT,
    tenant         TEXT,
    tier           TEXT,
    provider       TEXT,
    model          TEXT,
    request        TEXT,                   -- the prompt / flattened messages
    response       TEXT,                   -- the raw model reply text
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    total_tokens       INTEGER,
    cost_usd       REAL,                   -- usage-derived when tokens known, else route estimate
    latency_ms     REAL,
    correlation_id TEXT,                   -- links to turns.correlation_id when set
    error          TEXT                    -- set when the call failed
);
CREATE INDEX IF NOT EXISTS ix_llm_calls_corr ON llm_calls(correlation_id);
CREATE INDEX IF NOT EXISTS ix_llm_calls_created ON llm_calls(created_at);

-- one row per user-facing turn (/turn, /analyze): input + the reply we sent
CREATE TABLE IF NOT EXISTS turns (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT NOT NULL,
    correlation_id TEXT,
    thread_id      TEXT,
    kind           TEXT,                   -- routed | llm_routed | runtime | analyze
    routed_domain  TEXT,
    query          TEXT,                   -- the user input
    reply_text     TEXT,                   -- the final synthesized answer as sent
    reply_sections TEXT,                   -- JSON: the A2UI sections when structured
    claims         TEXT,                   -- JSON: grounding claims
    plan_steps     TEXT                    -- JSON: tool/reasoning steps
);
CREATE INDEX IF NOT EXISTS ix_turns_corr ON turns(correlation_id);
CREATE INDEX IF NOT EXISTS ix_turns_thread ON turns(thread_id);

-- durable KV backing IStateStore (thread checkpoints, session memory)
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def data_dir() -> Path | None:
    """The durable data dir (MIRA_DATA_DIR) or None when unset — None means run
    in-memory (tests, echo profile), never touch disk."""
    d = os.environ.get(ENV_DATA_DIR)
    return Path(d) if d else None


class Persistence:
    """Thread-safe SQLite persistence. When no data dir is configured it runs a
    pure in-memory shim (durable=False) so the service works with zero config."""

    def __init__(self, dir_: Path | None = None) -> None:
        self._dir = dir_ if dir_ is not None else data_dir()
        self._lock = threading.Lock()
        self._mem: dict[str, str] = {}          # kv shim when not durable
        self.durable = self._dir is not None
        if self.durable:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._path = str(self._dir / DB_FILENAME)
            self._init_schema()

    # ── connection / schema ────────────────────────────────────────────────
    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._conn() as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT INTO meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),))

    # ── llm_calls ───────────────────────────────────────────────────────────
    def record_llm_call(self, **f: Any) -> None:
        """Best-effort insert of one gateway call. Never raises — persistence
        must not break the answer path."""
        if not self.durable:
            return
        cols = ("created_at", "op", "agent", "tenant", "tier", "provider", "model",
                "request", "response", "prompt_tokens", "completion_tokens",
                "total_tokens", "cost_usd", "latency_ms", "correlation_id", "error")
        row = {c: f.get(c) for c in cols}
        row["created_at"] = row["created_at"] or _now()
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    f"INSERT INTO llm_calls({','.join(cols)}) "
                    f"VALUES({','.join('?' for _ in cols)})",
                    tuple(row[c] for c in cols))
        except sqlite3.Error:
            pass

    # ── turns ───────────────────────────────────────────────────────────────
    def record_turn(self, **f: Any) -> None:
        if not self.durable:
            return
        cols = ("created_at", "correlation_id", "thread_id", "kind", "routed_domain",
                "query", "reply_text", "reply_sections", "claims", "plan_steps")
        row = {c: f.get(c) for c in cols}
        row["created_at"] = row["created_at"] or _now()
        for j in ("reply_sections", "claims", "plan_steps"):
            if row[j] is not None and not isinstance(row[j], str):
                row[j] = json.dumps(row[j], default=str)
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    f"INSERT INTO turns({','.join(cols)}) "
                    f"VALUES({','.join('?' for _ in cols)})",
                    tuple(row[c] for c in cols))
        except sqlite3.Error:
            pass

    # ── kv (IStateStore backing) ────────────────────────────────────────────
    def kv_get(self, key: str) -> str | None:
        if not self.durable:
            return self._mem.get(key)
        try:
            with self._lock, self._conn() as conn:
                r = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
                return r["value"] if r else None
        except sqlite3.Error:
            return None

    def kv_set(self, key: str, value: str) -> None:
        if not self.durable:
            self._mem[key] = value
            return
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    "INSERT INTO kv(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value))
        except sqlite3.Error:
            pass


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


#: process-wide singleton — one db handle for the service.
_INSTANCE: Persistence | None = None


def get_persistence() -> Persistence:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Persistence()
    return _INSTANCE
