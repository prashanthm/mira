"""Minimal LangGraph runtime behind provider Protocols (ADR-007, ADR-017)."""

from __future__ import annotations

import base64
import pickle
from collections.abc import Mapping
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from mira.orchestration.interrupts import annotate_graph_interrupt, is_graph_paused
from mira.providers.protocols import ILLMProvider, IStateStore


class RuntimeState(TypedDict, total=False):
    prompt: str
    response: str
    approval: str
    tool_calls: list[dict[str, Any]]


class StateStoreCheckpointer(InMemorySaver):
    """LangGraph checkpointer that persists thread bundles via IStateStore.

    **Phase-1 / trusted-store only.** This adapter currently:

    * couples to ``InMemorySaver`` private internals (``self.storage``,
      ``self.writes``, ``self.blobs``) which are NOT part of LangGraph's public
      checkpointer API — hence the pinned upper bound on ``langgraph`` in
      ``pyproject.toml``. ``test_checkpointer_internal_attrs_present`` fails
      loudly if a LangGraph upgrade moves these attributes (M1).
    * serializes bundles with ``pickle`` (M2). ``pickle.loads`` is unsafe on
      attacker-influenced input, so this is acceptable only behind a trusted,
      single-tenant ``IStateStore`` (e.g. ``LocalStateStore``). Replace with a
      JSON/msgpack schema before any shared/multi-tenant store backend lands.
    """

    def __init__(self, store: IStateStore, *, key_prefix: str = "mira:lg:") -> None:
        super().__init__()
        self._store = store
        self._key_prefix = key_prefix
        self._loaded_threads: set[str] = set()

    def _bundle_key(self, thread_id: str) -> str:
        return f"{self._key_prefix}{thread_id}"

    def _ensure_loaded(self, thread_id: str) -> None:
        if thread_id in self._loaded_threads:
            return
        raw = self._store.get(self._bundle_key(thread_id))
        if raw:
            storage, writes, blobs = pickle.loads(base64.b64decode(raw.encode()))
            self.storage[thread_id] = storage
            self.writes.update(writes)
            self.blobs.update(blobs)
        self._loaded_threads.add(thread_id)

    def _persist(self, thread_id: str) -> None:
        writes = {key: value for key, value in self.writes.items() if key[0] == thread_id}
        blobs = {key: value for key, value in self.blobs.items() if key[0] == thread_id}
        bundle = (dict(self.storage.get(thread_id, {})), writes, blobs)
        encoded = base64.b64encode(pickle.dumps(bundle)).decode()
        self._store.set(self._bundle_key(thread_id), encoded)

    def get_tuple(self, config):  # type: ignore[no-untyped-def]
        thread_id = config["configurable"]["thread_id"]
        self._ensure_loaded(thread_id)
        return super().get_tuple(config)

    def put(self, config, checkpoint, metadata, new_versions):  # type: ignore[no-untyped-def]
        thread_id = config["configurable"]["thread_id"]
        self._ensure_loaded(thread_id)
        result = super().put(config, checkpoint, metadata, new_versions)
        self._persist(thread_id)
        return result

    def put_writes(self, config, writes, task_id, task_path: str = "") -> None:  # type: ignore[no-untyped-def]
        thread_id = config["configurable"]["thread_id"]
        self._ensure_loaded(thread_id)
        super().put_writes(config, writes, task_id, task_path)
        self._persist(thread_id)


class AgentRuntime:
    """Minimal durable graph: prepare → LLM (via ILLMProvider) → human gate (interrupt).

    ``tools`` are the LangChain tools discovered from the MCP registry
    (:func:`mira.orchestration.mcp_tools.load_mcp_tools`). When present, the LLM node binds
    them via :class:`GatewayChatModel` so the model can *select* a tool, and any selected
    tool calls are surfaced on the result as ``tool_calls`` (autonomous *execution* of a
    multi-turn tool loop is the ``ReasoningLoop``'s job — this runtime exposes the
    selection). With no tools, the node keeps the original text-only ``complete`` path so
    existing behavior is byte-for-byte unchanged.
    """

    def __init__(
        self,
        llm: ILLMProvider,
        state_store: IStateStore,
        *,
        tools: list[Any] | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools or []
        self._checkpointer = StateStoreCheckpointer(state_store)
        self._app = self._build_graph().compile(checkpointer=self._checkpointer)

    def _build_graph(self) -> StateGraph:
        llm = self._llm
        tools = self._tools

        def prepare(state: RuntimeState) -> dict[str, str]:
            return {"prompt": state.get("prompt", "")}

        def call_llm(state: RuntimeState) -> dict[str, Any]:
            # Defensive .get to match prepare()'s style and avoid a latent
            # KeyError if the graph topology changes (L1).
            prompt = state.get("prompt", "")
            if not tools:
                return {"response": llm.complete(prompt)}
            # Tools present: bind them so the model can select one. Built here (not in
            # __init__) to keep the langchain adapter on the orchestration hot path only.
            from mira.orchestration.model_adapter import GatewayChatModel
            from langchain_core.messages import HumanMessage

            bound = GatewayChatModel(llm).bind_tools(tools)
            message = bound.invoke([HumanMessage(content=prompt)])
            selected = [
                {"name": call["name"], "args": call.get("args", {})}
                for call in getattr(message, "tool_calls", []) or []
            ]
            return {"response": str(message.content), "tool_calls": selected}

        def human_gate(state: RuntimeState) -> dict[str, str]:
            approval = interrupt({"response": state.get("response", "")})
            return {"approval": str(approval)}

        graph = StateGraph(RuntimeState)
        graph.add_node("prepare", prepare)
        graph.add_node("call_llm", call_llm)
        graph.add_node("human_gate", human_gate)
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "call_llm")
        graph.add_edge("call_llm", "human_gate")
        graph.add_edge("human_gate", END)
        return graph

    def invoke(
        self,
        state: RuntimeState | Mapping[str, Any],
        *,
        thread_id: str,
    ) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        result = self._app.invoke(dict(state), config)
        return annotate_graph_interrupt(self._app, result, config)

    def resume(self, value: Any, *, thread_id: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        result = self._app.invoke(Command(resume=value), config)
        return annotate_graph_interrupt(self._app, result, config)

    @staticmethod
    def is_paused(result: Mapping[str, Any]) -> bool:
        return is_graph_paused(result)
