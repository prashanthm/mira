"""Tests for layered memory (ADR-017)."""

from __future__ import annotations

from mira.core.memory import (
    InMemoryLongTermMemory,
    LongTermMemory,
    SessionMemory,
    summarize,
)


class InMemoryStateStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value


def test_session_memory_round_trip() -> None:
    store = InMemoryStateStore()
    session = SessionMemory(store)

    session.save("thread-1", '{"turns": 3}')
    assert session.get("thread-1") == '{"turns": 3}'
    assert session.get("missing") is None


def test_long_term_write_and_retrieve() -> None:
    memory: LongTermMemory = InMemoryLongTermMemory()
    memory.write("well-a", "Permeability is 120 mD in the A zone.")
    memory.write("well-b", "Water cut rising in B zone.")

    results = memory.retrieve("permeability")
    assert results == ["Permeability is 120 mD in the A zone."]

    by_key = memory.retrieve("well-b")
    assert results != by_key
    assert "Water cut" in by_key[0]


def test_summarize_shrinks_long_history() -> None:
    history = [
        "Turn one discusses baseline pressure.",
        "Turn two adds decline curve context.",
        "Turn three notes water breakthrough timing.",
        "Turn four requests updated forecast.",
    ]
    compressed = summarize(history, max_tokens=10)

    assert len(compressed) < len(history)
    assert sum(len(item.split()) for item in compressed) <= 10
    assert compressed[-1] == history[-1]
    assert compressed[0].startswith("[Summarized")


def test_summarize_keeps_marker_on_tight_budget() -> None:
    # latest fits (3 words <= 4) but the full summary line does not -> a minimal
    # marker is still retained so collapse is never silent (M2).
    history = ["older turn one", "older turn two", "newest tight turn"]
    compressed = summarize(history, max_tokens=4)

    assert compressed[-1] == "newest tight turn"
    assert compressed[0] == "[…]"
    assert len(compressed) == 2


def test_local_state_store_matches_canonical_protocol() -> None:
    # Guards the duplicated IStateStore seam against drift (M1): the local test
    # store and SessionMemory's expected shape must stay structurally compatible.
    from mira.core.memory import IStateStore

    store = InMemoryStateStore()
    assert isinstance(store, IStateStore)
