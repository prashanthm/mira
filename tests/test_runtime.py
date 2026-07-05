"""Tests for LangGraph runtime, ILLMProvider seam, and IStateStore checkpointer."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mira.orchestration.runtime import AgentRuntime, StateStoreCheckpointer
from mira.providers.protocols import ILLMProvider, IStateStore


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        self.calls.append(prompt)
        return f"reply:{prompt}"

    def embed(self, text: str) -> list[float]:
        return [0.0]


class DictStateStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value


def test_runtime_calls_llm_and_persists_pause_for_resume() -> None:
    llm = FakeLLM()
    store = DictStateStore()
    runtime = AgentRuntime(llm, store)

    paused = runtime.invoke({"prompt": "hello"}, thread_id="run-1")
    assert AgentRuntime.is_paused(paused)
    assert llm.calls == ["hello"]
    assert paused["response"] == "reply:hello"
    assert any(key.startswith("mira:lg:run-1") for key in store._data)

    resumed_runtime = AgentRuntime(llm, store)
    finished = resumed_runtime.resume("approved", thread_id="run-1")
    assert finished["response"] == "reply:hello"
    assert finished["approval"] == "approved"
    assert "__interrupt__" not in finished


def test_no_langgraph_import_outside_orchestration() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    saa_root = repo_root / "src" / "mira"
    orchestration_prefixes = ("langchain", "langgraph")

    violations: list[str] = []
    for path in sorted(saa_root.rglob("*.py")):
        if "orchestration" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            for module in modules:
                if module.startswith(orchestration_prefixes):
                    violations.append(f"{path}: {module}")
    assert not violations, "framework imports outside orchestration/: " + ", ".join(violations)


def test_protocol_conformance() -> None:
    llm = FakeLLM()
    store = DictStateStore()
    assert isinstance(llm, ILLMProvider)
    assert isinstance(store, IStateStore)
    AgentRuntime(llm, store)


def test_checkpointer_internal_attrs_present() -> None:
    # M1 guard: StateStoreCheckpointer reaches into InMemorySaver internals.
    # If a LangGraph upgrade moves these, this fails loudly instead of silently
    # breaking persistence at runtime.
    cp = StateStoreCheckpointer(DictStateStore())
    for attr in ("storage", "writes", "blobs"):
        assert hasattr(cp, attr), f"InMemorySaver no longer exposes {attr!r}"


class FakeToolAwareLLM:
    """LLM exposing the tool-aware ``chat`` seam so the runtime binds + selects tools."""

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        return f"reply:{prompt}"

    def embed(self, text: str) -> list[float]:
        return [0.0]

    def chat(self, messages, *, model=None, tools=None, tool_choice="auto"):
        from mira.providers.openai_compatible import ChatResult, ToolCall

        return ChatResult(
            text="",
            tool_calls=(ToolCall(id="c1", name="catalog_search", arguments='{"kind":"well"}'),),
        )


def test_runtime_with_tools_surfaces_selected_tool_calls() -> None:
    from langchain_core.tools import tool

    @tool
    def catalog_search(kind: str) -> str:
        """Search Catalog records by kind."""
        return f"searched {kind}"

    runtime = AgentRuntime(FakeToolAwareLLM(), DictStateStore(), tools=[catalog_search])
    result = runtime.invoke({"prompt": "find wells"}, thread_id="tools-1")

    assert result.get("tool_calls") == [{"name": "catalog_search", "args": {"kind": "well"}}]


def test_runtime_without_tools_is_text_only_path() -> None:
    # No tools → original byte-for-byte text path (no tool_calls key).
    llm = FakeLLM()
    runtime = AgentRuntime(llm, DictStateStore())
    result = runtime.invoke({"prompt": "hi"}, thread_id="notools-1")
    assert result["response"] == "reply:hi"
    assert "tool_calls" not in result


def test_resume_unknown_thread_does_not_fabricate_completion() -> None:
    # L2: resuming a thread that was never paused must not silently return a
    # *completed* run carrying an approval it never legitimately received. It may
    # raise or re-enter the graph (pausing again), but it must not fabricate a
    # finished result with the resume value applied as if a human had approved.
    runtime = AgentRuntime(FakeLLM(), DictStateStore())
    try:
        result = runtime.resume("approved", thread_id="never-started")
    except Exception:
        return  # raising is an acceptable contract
    assert AgentRuntime.is_paused(result), (
        "resume on an unknown thread must not produce a completed run"
    )
    assert "approval" not in result or AgentRuntime.is_paused(result)
