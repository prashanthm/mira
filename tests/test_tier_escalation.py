"""Tests for the model-tier escalating specialist wrapper (ADR-052)."""

from __future__ import annotations

import pytest

from mira_harness.quality import EscalationTrigger

from mira.model.routing import BudgetExceeded
from mira.orchestration.specialist_scaffold import SpecialistResult
from mira.orchestration.tier_escalation import (
    MODEL_TIER_CONTEXT_KEY,
    TierEscalatingSpecialist,
)

GROUNDED = {
    "value": 1,
    "provenance": {"source_type": "docs.section", "source_id": "handbook#x"},
}
PLAN = [{"event": "plan_step", "phase": "plan", "detail": "p", "index": 0}]


def _good(domain="d", query="q") -> SpecialistResult:
    return SpecialistResult(
        domain=domain, query=query, answer=dict(GROUNDED), plan_steps=list(PLAN)
    )


def _ungrounded(domain="d", query="q") -> SpecialistResult:
    return SpecialistResult(
        domain=domain, query=query, answer={"value": 1}, plan_steps=list(PLAN)
    )


class ScriptedSpecialist:
    """Inner routable that replays scripted results and records its calls."""

    def __init__(self, script):
        self._script = list(script)
        self.calls: list[dict] = []

    def invoke(self, query, *, thread_id, context=None, **kwargs):
        self.calls.append({"thread_id": thread_id, "context": dict(context or {})})
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def test_good_result_passes_through_without_retry():
    inner = ScriptedSpecialist([_good()])
    result = TierEscalatingSpecialist(inner, start_tier="light").invoke(
        "q", thread_id="t"
    )
    assert len(inner.calls) == 1
    assert result.decisions == []


def test_triggered_result_retries_exactly_once_with_tier_context():
    inner = ScriptedSpecialist([_ungrounded(), _good()])
    result = TierEscalatingSpecialist(inner, start_tier="light").invoke(
        "q", thread_id="t7"
    )
    assert len(inner.calls) == 2
    assert inner.calls[0]["context"] == {}
    assert inner.calls[1]["thread_id"] == "t7:tier-escalated"
    assert inner.calls[1]["context"][MODEL_TIER_CONTEXT_KEY] == "standard"
    # The improved retry is kept and carries the audit decision.
    assert result.answer == GROUNDED
    (decision,) = result.decisions
    assert decision["kind"] == "escalation"
    assert decision["detail"]["trigger"] == "ungrounded_answer"
    assert decision["detail"]["escalated"] is True
    assert decision["detail"]["improved"] is True
    assert (decision["detail"]["from_tier"], decision["detail"]["to_tier"]) == (
        "light",
        "standard",
    )


def test_non_improving_retry_keeps_the_first_result():
    """A deterministic inner reproduces the same result — no oscillation."""
    inner = ScriptedSpecialist([_ungrounded(), _ungrounded()])
    result = TierEscalatingSpecialist(inner, start_tier="light").invoke(
        "q", thread_id="t"
    )
    assert len(inner.calls) == 2
    (decision,) = result.decisions
    assert decision["detail"]["improved"] is False


def test_no_stronger_tier_records_decision_without_retry():
    inner = ScriptedSpecialist([_ungrounded()])
    result = TierEscalatingSpecialist(inner, start_tier="deep").invoke(
        "q", thread_id="t"
    )
    assert len(inner.calls) == 1
    (decision,) = result.decisions
    assert decision["detail"]["escalated"] is False
    assert decision["detail"]["detail"] == "no stronger tier configured"


def test_budget_exceeded_on_retry_keeps_first_result():
    inner = ScriptedSpecialist([_ungrounded(), BudgetExceeded("cap")])
    result = TierEscalatingSpecialist(inner, start_tier="light").invoke(
        "q", thread_id="t"
    )
    assert result.answer == {"value": 1}  # the first attempt
    (decision,) = result.decisions
    assert decision["detail"]["escalated"] is False
    assert decision["detail"]["detail"] == "budget"


def test_stricter_trigger_is_injectable():
    inner = ScriptedSpecialist([_good(), _good()])
    wrapper = TierEscalatingSpecialist(
        inner,
        trigger=EscalationTrigger(min_trace_score=1.1),  # nothing passes
        start_tier="light",
    )
    result = wrapper.invoke("q", thread_id="t")
    assert len(inner.calls) == 2  # retried despite a good first result
    assert result.decisions


def test_decisions_round_trip_through_the_contracts_bridge():
    from mira.orchestration.contracts_bridge import (
        specialist_result_from_trace,
        trace_from_specialist_result,
    )

    inner = ScriptedSpecialist([_ungrounded(), _good()])
    result = TierEscalatingSpecialist(inner, start_tier="light").invoke(
        "q", thread_id="t"
    )
    trace = trace_from_specialist_result(result, task_id="t1")
    back = specialist_result_from_trace(trace, query=result.query)
    assert back.to_dict() == result.to_dict()


def test_registry_wrap_factories_applies_decoration():
    from mira.orchestration.agent_cards import AgentCard, AgentCardRegistry

    registry = AgentCardRegistry()
    card = AgentCard(name="d", description="x", model_hint="light")
    registry.register(card, lambda: ScriptedSpecialist([_good()]))
    registry.wrap_factories(
        lambda c, factory: (
            lambda: TierEscalatingSpecialist(
                factory(), start_tier=c.model_hint or "light"
            )
        )
    )
    resolved = registry.resolve("d")
    assert isinstance(resolved, TierEscalatingSpecialist)


def test_app_flag_wiring_requires_both_flags(monkeypatch, tmp_path):
    import json

    from mira.app import _registry_with_tier_escalation
    from mira.config.profiles import load_profile
    from mira.orchestration.agent_cards import AgentCard, AgentCardRegistry
    from mira.orchestration.tier_escalation import TierEscalatingSpecialist as TES

    def fresh_registry():
        registry = AgentCardRegistry()
        registry.register(
            AgentCard(name="d", description="x", model_hint="light"),
            lambda: ScriptedSpecialist([_good()]),
        )
        return registry

    routes = json.dumps([{"provider": "p", "model": "m", "tier": "light"}])

    # Neither flag: untouched.
    monkeypatch.delenv("MODEL_ROUTES", raising=False)
    monkeypatch.delenv("ENABLE_TIER_ESCALATION", raising=False)
    registry = fresh_registry()
    assert not isinstance(
        _registry_with_tier_escalation(registry, load_profile("kubernetes")).resolve("d"),
        TES,
    )

    # Routes but no flag: untouched.
    monkeypatch.setenv("MODEL_ROUTES", routes)
    registry = fresh_registry()
    assert not isinstance(
        _registry_with_tier_escalation(registry, load_profile("kubernetes")).resolve("d"),
        TES,
    )

    # Both: wrapped.
    monkeypatch.setenv("ENABLE_TIER_ESCALATION", "1")
    registry = fresh_registry()
    assert isinstance(
        _registry_with_tier_escalation(registry, load_profile("kubernetes")).resolve("d"),
        TES,
    )

    # None registry stays None.
    assert _registry_with_tier_escalation(None, load_profile("kubernetes")) is None
