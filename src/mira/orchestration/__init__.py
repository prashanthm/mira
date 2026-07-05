"""Agent orchestration — the only layer that may import langchain / langgraph."""

from mira.orchestration.specialist_scaffold import (
    DomainSpec,
    RegisteredTool,
    SpecialistResult,
    SpecialistSubgraph,
    build_specialist_subgraph,
)
from mira.orchestration.agent_cards import (
    AgentCard,
    AgentCardRegistry,
    card_for_domain,
)
from mira.orchestration.specialists.finance import build_finance_specialist
from mira.orchestration.specialists.research import build_research_specialist
from mira.orchestration.supervisor import Supervisor, SupervisorResult

__all__ = [
    "AgentCard",
    "AgentCardRegistry",
    "DomainSpec",
    "RegisteredTool",
    "SpecialistResult",
    "SpecialistSubgraph",
    "Supervisor",
    "SupervisorResult",
    "build_finance_specialist",
    "build_research_specialist",
    "build_specialist_subgraph",
    "card_for_domain",
]
