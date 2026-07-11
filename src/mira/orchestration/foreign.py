"""Foreign-specialist wrapper: any EnvelopeRunner becomes routable (ADR-051).

``ForeignSpecialist`` fronts a non-Mira agent with the governance plane,
fail-closed at every step: policy-in detectors run *before* the foreign
agent is ever called; the dispatch envelope and the returned trace are both
contract-validated (an out-of-contract trace degrades to a structured error,
never a crash); self-reported foreign costs are recorded into the cost
ledger under the foreign domain; and the converted ``SpecialistResult`` then
flows through the same groundedness/drift/scoring surface as a native
specialist. Registration is one ``registry.register`` call — the supervisor
never changes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mira_contracts.agent import EnvelopeRunner
from mira_contracts.envelope import BudgetSpec, ContractViolation, validate_envelope
from mira_contracts.trace import validate_trace
from mira_harness.cost import AttributedSpan, CostLedger
from mira_harness.policy import InjectionDetector, TextDetector
from mira_harness.stub_agent import StubEchoAgent

from mira.orchestration.agent_cards import AgentCard, AgentCardRegistry
from mira.orchestration.contracts_bridge import (
    envelope_for_dispatch,
    specialist_result_from_trace,
)
from mira.orchestration.specialist_scaffold import DomainSpec, SpecialistResult


class ForeignSpecialist:
    """A :class:`~mira.orchestration.agent_cards.RoutableAgent` over a foreign runner."""

    def __init__(
        self,
        runner: EnvelopeRunner,
        spec: DomainSpec,
        *,
        budget: BudgetSpec | None = None,
        policy: Sequence[TextDetector] | None = None,
        ledger: CostLedger | None = None,
        tenant: str = "",
    ) -> None:
        self._runner = runner
        self._spec = spec
        self._budget = budget if budget is not None else BudgetSpec()
        self._policy: tuple[TextDetector, ...] = (
            tuple(policy) if policy is not None else (InjectionDetector(),)
        )
        self._ledger = ledger
        self._tenant = tenant

    @property
    def domain_spec(self) -> DomainSpec:
        return self._spec

    def _error(self, query: str, message: str) -> SpecialistResult:
        return SpecialistResult(
            domain=self._spec.domain_id, query=query, answer={}, error=message
        )

    def invoke(
        self,
        query: str,
        *,
        thread_id: str,
        context: Mapping[str, Any] | None = None,  # noqa: ARG002 — parity with scaffold
        max_iterations: int = 1,
        require_hitl: bool = False,
    ) -> SpecialistResult:
        # 1. Policy-in: the foreign agent is never called on a flagged query.
        for detector in self._policy:
            finding = detector.check(query)
            if finding is not None:
                return self._error(query, f"{finding.code}: {finding.snippet}")

        # 2. Build + validate the dispatch envelope (fail-closed).
        try:
            envelope = validate_envelope(
                envelope_for_dispatch(
                    query,
                    self._spec,
                    task_id=f"{self._spec.domain_id}:{thread_id}",
                    budget=self._budget,
                    tenant=self._tenant,
                    require_hitl=require_hitl,
                    max_iterations=max_iterations,
                )
            )
        except ContractViolation as exc:
            return self._error(query, f"invalid envelope: {exc.message}")

        # 3. Run the foreign agent; its failures degrade to structured errors.
        try:
            raw = self._runner.run(envelope)
        except Exception as exc:  # noqa: BLE001 — fail-degraded, never crash the graph
            return self._error(query, f"foreign agent error: {exc}")

        # 4. An out-of-contract trace is an error result, not a crash.
        try:
            trace = validate_trace(raw)
        except ContractViolation as exc:
            return self._error(query, f"invalid trace: {exc.message}")
        except Exception as exc:  # noqa: BLE001 — non-trace return values land here
            return self._error(query, f"invalid trace: {exc}")

        # 5. Foreign spend is attributed like native spend (self_reported flagged
        #    in the records themselves — ADR-042/051).
        if self._ledger is not None:
            for record in trace.costs:
                self._ledger.record(
                    AttributedSpan.from_span(
                        record,
                        tenant=self._tenant,
                        domain=self._spec.domain_id,
                        tool=record.tool,
                        correlation_id=envelope.correlation_id,
                    )
                )

        # 6. Lower to the supervisor contract; the routed domain owns the result
        #    regardless of what the runner called itself (the trace keeps the
        #    runner's own AgentRef).
        result = specialist_result_from_trace(trace, query=query)
        result.domain = self._spec.domain_id
        return result


def foreign_card(
    runner: EnvelopeRunner,
    *,
    keywords: Sequence[str],
    description: str | None = None,
) -> AgentCard:
    """Build the discovery card for a foreign runner from its own card()."""
    card = runner.card()
    capabilities = card.get("capabilities") or {}
    return AgentCard(
        name=str(card["name"]),
        description=description if description is not None else str(card["description"]),
        tool_prefixes=frozenset(str(p) for p in capabilities.get("tool_prefixes", ())),
        keywords=frozenset(k.strip().lower() for k in keywords if k.strip()),
    )


def register_foreign_stub(
    registry: AgentCardRegistry,
    *,
    ledger: CostLedger | None = None,
) -> AgentCard:
    """Register the ADR-051 stub foreign agent as a routable specialist."""
    runner = StubEchoAgent()
    card = foreign_card(runner, keywords=("delegate", "external", "partner", "echo"))
    spec = DomainSpec(domain_id=card.name, tool_prefixes=card.tool_prefixes)
    registry.register(card, lambda: ForeignSpecialist(runner, spec, ledger=ledger))
    return card


__all__ = ["ForeignSpecialist", "foreign_card", "register_foreign_stub"]
