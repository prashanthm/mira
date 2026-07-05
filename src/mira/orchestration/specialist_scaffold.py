"""Reusable domain specialist subgraph scaffold (ADR-014, ADR-013).

Wraps :class:`ReasoningLoop` with per-domain tool allow-listing, namespaced
checkpointer thread ids, and a supervisor-consumable :class:`SpecialistResult`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from mira.orchestration.reasoning import ReasoningBudget, ReasoningLoop, ToolFn
from mira.tools.contract import ToolContract

ToolHandler = Callable[[dict[str, Any]], Any]

# Per-domain query-inference hook: takes the loop's ``act:`` action string and the
# domain-filtered tool registry, returns a handler result to serve as the
# observation, or None to fall through to the structured noop.
QueryInference = Callable[[str, dict[str, "RegisteredTool"]], "dict[str, Any] | None"]


@dataclass(frozen=True, slots=True)
class DomainSpec:
    """Domain identity plus MCP tool name prefixes this specialist may bind."""

    domain_id: str
    tool_prefixes: frozenset[str]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    """MCP contract paired with an in-process handler for tests and local wiring."""

    contract: ToolContract
    handler: ToolHandler


@dataclass
class SpecialistResult:
    """Structured payload a supervisor collects after a specialist run."""

    domain: str
    query: str
    answer: dict[str, Any]
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    bound_exceeded: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "query": self.query,
            "answer": self.answer,
            "plan_steps": self.plan_steps,
            "bound_exceeded": self.bound_exceeded,
            "error": self.error,
        }


class SpecialistSubgraph:
    """Invocable specialist wrapping a compiled ADR-013 reasoning loop."""

    def __init__(self, domain_spec: DomainSpec, loop: ReasoningLoop) -> None:
        self._domain = domain_spec
        self._loop = loop

    @property
    def domain_spec(self) -> DomainSpec:
        return self._domain

    @property
    def reasoning_loop(self) -> ReasoningLoop:
        return self._loop

    def invoke(
        self,
        query: str,
        *,
        thread_id: str,
        context: Mapping[str, Any] | None = None,
        max_iterations: int = 1,
        require_hitl: bool = False,
    ) -> SpecialistResult:
        if not self._domain.tool_prefixes:
            return SpecialistResult(
                domain=self._domain.domain_id,
                query=query,
                answer={},
                error="no tools allowed for domain",
            )

        namespaced_thread = f"{self._domain.domain_id}:{thread_id}"
        state: dict[str, Any] = {
            "query": query,
            "max_iterations": max_iterations,
            "require_hitl": require_hitl,
        }
        if context:
            state.update(dict(context))

        try:
            result = self._loop.invoke(state, thread_id=namespaced_thread)
        except PermissionError as exc:
            return SpecialistResult(
                domain=self._domain.domain_id,
                query=query,
                answer={},
                error=str(exc),
            )

        return _to_specialist_result(self._domain.domain_id, query, result)


def filter_tools_by_domain(
    tools: list[RegisteredTool],
    domain_spec: DomainSpec,
) -> list[RegisteredTool]:
    """Keep only tools whose contract name starts with an allowed prefix."""
    if not domain_spec.tool_prefixes:
        return []
    allowed = domain_spec.tool_prefixes
    return [
        tool
        for tool in tools
        if any(tool.contract.name.startswith(prefix) for prefix in allowed)
    ]


def build_specialist_subgraph(
    domain_spec: DomainSpec,
    tools: list[RegisteredTool],
    *,
    budget: ReasoningBudget | None = None,
    query_inference: QueryInference | None = None,
) -> SpecialistSubgraph:
    """Build a domain specialist subgraph over filtered tools and ReasoningLoop."""
    filtered = filter_tools_by_domain(tools, domain_spec)
    registry = {tool.contract.name: tool for tool in filtered}
    tool_fn = _make_scoped_dispatcher(registry, domain_spec, query_inference=query_inference)
    resolved_budget = budget or ReasoningBudget(max_steps=10)
    loop = ReasoningLoop(resolved_budget, tool_fn=tool_fn)
    return SpecialistSubgraph(domain_spec, loop)


def _make_scoped_dispatcher(
    registry: dict[str, RegisteredTool],
    domain_spec: DomainSpec,
    *,
    query_inference: QueryInference | None = None,
) -> ToolFn:
    infer = query_inference if query_inference is not None else _no_inference

    def tool_fn(action: str) -> str:
        explicit = _parse_explicit_tool_call(action)
        if explicit is not None:
            name, payload = explicit
            if name not in registry:
                raise PermissionError(
                    f"tool {name!r} not allowed for domain {domain_spec.domain_id!r}"
                )
            try:
                result = registry[name].handler(payload)
            except PermissionError:
                raise  # authorization failures stay fail-closed (surfaced as error)
            except Exception as exc:  # noqa: BLE001 — fail-degraded, never crash the graph
                # A failing handler (e.g. a remote MCP tool behind the bridge)
                # becomes a structured observation the specialist can reason
                # over / surface, instead of an exception escaping the graph.
                return json.dumps({"status": "tool_error", "tool": name, "detail": str(exc)})
            return json.dumps(result, default=str)

        inferred = infer(action, registry)
        if inferred is not None:
            return json.dumps(inferred, default=str)

        return json.dumps({"status": "noop", "detail": action})

    return tool_fn


def _parse_explicit_tool_call(action: str) -> tuple[str, dict[str, Any]] | None:
    marker = ":tool:"
    if marker not in action:
        return None
    rest = action.split(marker, 1)[1]
    name, sep, payload_raw = rest.partition(":")
    if not sep:
        return None
    payload_raw = payload_raw.strip()
    payload: dict[str, Any] = json.loads(payload_raw) if payload_raw.startswith("{") else {}
    return name, payload


def _no_inference(
    action: str,
    registry: dict[str, RegisteredTool],
) -> dict[str, Any] | None:
    """Default query-inference hook: never infers — domains opt in explicitly.

    Each domain supplies its own ``query_inference`` (see the demo specialists);
    without one, non-explicit actions fall through to the structured noop.
    """
    return None


def _to_specialist_result(
    domain: str,
    query: str,
    loop_result: Mapping[str, Any],
) -> SpecialistResult:
    observation = str(loop_result.get("observation") or "")
    answer: dict[str, Any]
    try:
        parsed = json.loads(observation)
        answer = parsed if isinstance(parsed, dict) else {"raw": observation}
    except json.JSONDecodeError:
        answer = {"raw": observation}

    bound = loop_result.get("bound_exceeded")
    return SpecialistResult(
        domain=domain,
        query=query,
        answer=answer,
        plan_steps=list(loop_result.get("plan_steps") or []),
        bound_exceeded=dict(bound) if isinstance(bound, Mapping) else None,
    )


__all__ = [
    "DomainSpec",
    "QueryInference",
    "RegisteredTool",
    "SpecialistResult",
    "SpecialistSubgraph",
    "build_specialist_subgraph",
    "filter_tools_by_domain",
]
