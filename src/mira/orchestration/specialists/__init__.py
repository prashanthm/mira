"""Domain specialist builders."""

from mira.orchestration.specialists.domains import FINANCE_DOMAIN, RESEARCH_DOMAIN
from mira.orchestration.specialists.finance import (
    REPRESENTATIVE_FINANCE_QUERY,
    build_finance_specialist,
)
from mira.orchestration.specialists.research import (
    REPRESENTATIVE_RESEARCH_QUERY,
    build_research_specialist,
)

__all__ = [
    "FINANCE_DOMAIN",
    "RESEARCH_DOMAIN",
    "REPRESENTATIVE_FINANCE_QUERY",
    "REPRESENTATIVE_RESEARCH_QUERY",
    "build_finance_specialist",
    "build_research_specialist",
]
