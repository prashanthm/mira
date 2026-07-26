"""Durable LLM-call + turn persistence (core/persistence.py) and the gateway
capture chokepoint (model/gateway.py). SQLite-on-disk when MIRA_DATA_DIR is
set; a RAM shim otherwise — both exercised here."""
from __future__ import annotations

import sqlite3

from mira.core.persistence import Persistence
from mira.model.gateway import Gateway, call_context
from mira.providers.bundle import ProviderBundle


def _rows(p, table):
    with p._conn() as c:  # noqa: SLF001 — test reads the raw table
        return [dict(r) for r in c.execute(f"SELECT * FROM {table}").fetchall()]


def test_persistence_durable_roundtrip(tmp_path):
    p = Persistence(tmp_path)
    assert p.durable
    p.record_llm_call(op="classify", agent="synthesis", model="deepseek-v4-flash",
                      request="route this", response="advisor",
                      prompt_tokens=12, completion_tokens=3, total_tokens=15,
                      cost_usd=0.0001, latency_ms=42.0)
    (row,) = _rows(p, "llm_calls")
    assert row["op"] == "classify" and row["total_tokens"] == 15
    assert row["request"] == "route this" and row["response"] == "advisor"
    # kv backing survives a fresh handle on the same dir (durability)
    p.kv_set("thread:abc", "state-blob")
    assert Persistence(tmp_path).kv_get("thread:abc") == "state-blob"


def test_persistence_ram_shim_without_dir():
    p = Persistence(None)
    assert not p.durable
    p.record_llm_call(op="x", request="q", response="a")   # no-op, no raise
    p.kv_set("k", "v")
    assert p.kv_get("k") == "v"                              # RAM kv still works


def test_gateway_captures_every_call(tmp_path, monkeypatch):
    """A gateway call on the deployed fast path (no router) still records the
    request/response/op/latency to the durable log."""
    import mira.core.persistence as persistence_mod
    store = Persistence(tmp_path)
    monkeypatch.setattr(persistence_mod, "_INSTANCE", store)

    class _Echo:
        def complete(self, prompt, *, model=None):
            return f"echo:{prompt}"
    gw = Gateway(ProviderBundle(llm=_Echo(), secrets=None, object_store=None,
                                state_store=None, observability=None))
    with call_context("turn_synthesis", correlation_id="corr-1"):
        assert gw.complete("hello", agent="synthesis") == "echo:hello"
    (row,) = _rows(store, "llm_calls")
    assert row["op"] == "turn_synthesis" and row["correlation_id"] == "corr-1"
    assert row["request"] == "hello" and row["response"] == "echo:hello"
    assert row["agent"] == "synthesis" and row["latency_ms"] is not None


def test_gateway_records_a_failed_call_then_reraises(tmp_path, monkeypatch):
    import mira.core.persistence as persistence_mod
    store = Persistence(tmp_path)
    monkeypatch.setattr(persistence_mod, "_INSTANCE", store)

    class _Boom:
        def complete(self, prompt, *, model=None):
            raise RuntimeError("provider down")
    gw = Gateway(ProviderBundle(llm=_Boom(), secrets=None, object_store=None,
                                state_store=None, observability=None))
    import pytest
    with pytest.raises(RuntimeError):
        gw.complete("hello")
    (row,) = _rows(store, "llm_calls")
    assert "provider down" in (row["error"] or "")


def test_record_turn_stores_input_reply_and_sections(tmp_path):
    p = Persistence(tmp_path)
    p.record_turn(correlation_id="c1", thread_id="t1", kind="routed",
                  routed_domain="advisor", query="am I over-allocated?",
                  reply_text='{"headline":"h","sections":[{"kind":"prose","text":"you are"}]}',
                  reply_sections=[{"kind": "prose", "text": "you are"}],
                  claims=[{"x": 1}])
    (row,) = _rows(p, "turns")
    assert row["query"] == "am I over-allocated?" and row["kind"] == "routed"
    assert "you are" in row["reply_text"]
    import json
    assert json.loads(row["reply_sections"])[0]["kind"] == "prose"
    assert row["correlation_id"] == "c1"


def test_chat_cli_routes_through_gateway_and_persists(tmp_path, monkeypatch):
    """mira-chat now wraps the raw provider in a Gateway, so its LLM calls hit
    the same _persist_call chokepoint (SQLite + gen_ai span) as every other
    entry point — no bypass."""
    import mira.core.persistence as persistence_mod
    store = Persistence(tmp_path)
    monkeypatch.setattr(persistence_mod, "_INSTANCE", store)

    from mira.model.gateway import Gateway, call_context
    from mira.providers.bundle import ProviderBundle
    from mira.providers.openai_compatible import ChatResult, ToolCall

    class _FakeChatProvider:
        def chat(self, messages, *, model=None, tools=None, tool_choice="auto"):
            return ChatResult(text="hi", tool_calls=(),
                              usage={"prompt_tokens": 5, "completion_tokens": 2,
                                     "total_tokens": 7})
    gw = Gateway(ProviderBundle(llm=_FakeChatProvider(), secrets=None,
                                object_store=None, state_store=None, observability=None))
    with call_context("chat_cli", correlation_id="chat-1"):
        res = gw.chat([{"role": "user", "content": "hello"}], agent="chat")
    assert res.text == "hi"
    (row,) = _rows(store, "llm_calls")
    assert row["op"] == "chat_cli" and row["total_tokens"] == 7
    assert row["correlation_id"] == "chat-1" and row["response"] == "hi"
