"""Fake ``vantage.*`` tools for offline tests/evals — never a live server.

Result shapes are copied from the Vantage engine's MCP surface
(``vantage_server/mcp_server.py`` + ``engine.py``): every result is the
``envelope`` dict (``as_of``/``source``/``stale`` + dataset payload) carrying
the provenance block ``{"source_type": "vantage", "source_id":
"<data-dir>#<dataset>"}``. Two entry points:

* :func:`fake_vantage_registered_tools` — scaffold-bindable
  :class:`RegisteredTool` list (as the MCP bridge would produce), with a shared
  ``calls`` log and optional per-tool failure injection;
* :func:`fake_vantage_mcp_tools` — langchain-adapter-shaped tool objects
  (``.name`` / ``.description`` / ``.invoke`` returning JSON text) for code
  paths that bridge raw discovery output (``build_live_registry``, the CLI).
"""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from mira.orchestration.specialist_scaffold import RegisteredTool
from mira.tools.contract import ToolContract

DATA_DIR = "/data/vantage"
AS_OF = "2025-07-15T09:30:00"


def _provenance(dataset: str) -> dict[str, str]:
    return {"source_type": "vantage", "source_id": f"{DATA_DIR}#{dataset}"}


def _envelope(dataset: str, **data: Any) -> dict[str, Any]:
    return {
        "as_of": AS_OF,
        "source": "fixture",
        "stale": False,
        **data,
        "provenance": _provenance(dataset),
    }


def _wash_entry(
    symbol: str,
    *,
    blocked: bool,
    reason: str | None = None,
    clears_on: str | None = None,
    clears_on_date: str | None = None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "blocked": blocked,
        "reason": reason,
        "clears_on": clears_on,
        "clears_on_date": clears_on_date,
        "future_risk": None,
    }


WASH_STATUS_RESULT = _envelope(
    "wash_status",
    window_days=30,
    wash={
        "VOO": _wash_entry(
            "VOO",
            blocked=True,
            reason="IRA bought SPY on Jul 1 (auto-invest)",
            clears_on="Aug 1",
            clears_on_date="2025-08-01",
        ),
        "VXUS": _wash_entry("VXUS", blocked=False),
        "BND": _wash_entry("BND", blocked=False),
    },
)

TLH_CANDIDATES_RESULT = _envelope(
    "tlh_candidates",
    threshold_usd=200.0,
    threshold_pct=3.0,
    candidates=[
        {
            "lot": {
                "account": "brokerage",
                "symbol": "VXUS",
                "date": "2024-11-02",
                "shares": 40.0,
                "cost_per_share": 62.10,
            },
            "account": {
                "id": "brokerage",
                "name": "Household Brokerage",
                "short": "Brokerage",
                "type": "taxable",
                "taxable": True,
                "last_sync": AS_OF,
            },
            "unrealized": -310.0,
            "loss_pct": 12.5,
            "status": "clear",
            "wash": _wash_entry("VXUS", blocked=False),
            "replacement": "IXUS",
        },
        {
            "lot": {
                "account": "brokerage",
                "symbol": "VOO",
                "date": "2025-01-10",
                "shares": 5.0,
                "cost_per_share": 560.0,
            },
            "account": {
                "id": "brokerage",
                "name": "Household Brokerage",
                "short": "Brokerage",
                "type": "taxable",
                "taxable": True,
                "last_sync": AS_OF,
            },
            "unrealized": -245.0,
            "loss_pct": 8.75,
            "status": "blocked",
            "wash": _wash_entry(
                "VOO",
                blocked=True,
                reason="IRA bought SPY on Jul 1 (auto-invest)",
                clears_on="Aug 1",
                clears_on_date="2025-08-01",
            ),
            "replacement": "VTI",
        },
    ],
)

ALLOCATION_RESULT = _envelope(
    "allocation",
    account="all",
    total=100_000.0,
    by_class={
        "usEquity": {"value": 60_000.0, "pct": 60.0},
        "intlEquity": {"value": 20_000.0, "pct": 20.0},
        "bonds": {"value": 15_000.0, "pct": 15.0},
        "cash": {"value": 5_000.0, "pct": 5.0},
    },
)

POSITIONS_RESULT = _envelope(
    "positions",
    account="all",
    positions=[
        {
            "symbol": "VOO",
            "shares": 100.0,
            "value": 55_000.0,
            "cost": 45_000.0,
            "unrealized": 10_000.0,
            "day_pl": 275.0,
            "weight": 55.0,
            "accounts": ["brokerage"],
            "lots": [
                {
                    "account": "brokerage",
                    "symbol": "VOO",
                    "date": "2023-03-01",
                    "shares": 100.0,
                    "cost_per_share": 450.0,
                }
            ],
            "overlap": {"label": "US large blend", "symbols": ["VOO", "SPY"]},
        },
        {
            "symbol": "VXUS",
            "shares": 320.0,
            "value": 20_000.0,
            "cost": 20_310.0,
            "unrealized": -310.0,
            "day_pl": -40.0,
            "weight": 20.0,
            "accounts": ["brokerage"],
            "lots": [],
            "overlap": None,
        },
    ],
)

LOTS_RESULT = _envelope(
    "lots",
    account="all",
    lots=[
        {
            "account": "brokerage",
            "symbol": "VOO",
            "date": "2023-03-01",
            "shares": 100.0,
            "cost_per_share": 450.0,
        },
        {
            "account": "brokerage",
            "symbol": "VXUS",
            "date": "2024-11-02",
            "shares": 40.0,
            "cost_per_share": 62.10,
        },
    ],
)

QUOTES_RESULT = _envelope(
    "quotes",
    quotes={
        "VOO": {
            "symbol": "VOO",
            "name": "Vanguard S&P 500 ETF",
            "price": 550.0,
            "day_pct": 0.5,
            "asset_class": "usEquity",
        },
        "VXUS": {
            "symbol": "VXUS",
            "name": "Vanguard Total International",
            "price": 62.5,
            "day_pct": -0.2,
            "asset_class": "intlEquity",
        },
    },
)

RESULTS: dict[str, dict[str, Any]] = {
    "vantage.positions": POSITIONS_RESULT,
    "vantage.allocation": ALLOCATION_RESULT,
    "vantage.wash_status": WASH_STATUS_RESULT,
    "vantage.tlh_candidates": TLH_CANDIDATES_RESULT,
    "vantage.lots": LOTS_RESULT,
    "vantage.quotes": QUOTES_RESULT,
}

_PERMISSIVE_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": True}


def fake_vantage_registered_tools(
    *,
    failing: Collection[str] = (),
    calls: list[tuple[str, dict[str, Any]]] | None = None,
) -> list[RegisteredTool]:
    """Scaffold-bindable fake vantage tools with realistic engine result shapes.

    ``failing`` names tools whose handler raises (simulating a remote MCP
    failure behind the bridge); ``calls`` (when given) records every
    ``(tool_name, payload)`` dispatch for assertion.
    """
    call_log = calls if calls is not None else []
    tools: list[RegisteredTool] = []
    for name, result in RESULTS.items():
        def handler(
            payload: dict[str, Any],
            _name: str = name,
            _result: dict[str, Any] = result,
        ) -> dict[str, Any]:
            call_log.append((_name, dict(payload)))
            if _name in failing:
                raise ConnectionError(f"MCP tool {_name!r} invocation failed: server gone")
            return json.loads(json.dumps(_result))  # defensive deep copy

        tools.append(
            RegisteredTool(
                contract=ToolContract(
                    name=name,
                    description=f"Fake {name} with the Vantage engine result shape.",
                    inputSchema=dict(_PERMISSIVE_SCHEMA),
                    required_entitlement=f"mcp:{name}",
                    readOnlyHint=True,
                ),
                handler=handler,
            )
        )
    return tools


@dataclass
class FakeMcpTool:
    """Langchain-adapter-shaped discovery result (``.name`` / ``.invoke``)."""

    name: str
    description: str = "a fake vantage MCP tool"
    args_schema: Any = None
    metadata: Any = None
    error: Exception | None = None
    calls: list[Any] = field(default_factory=list)

    def invoke(self, payload: Any) -> str:
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return json.dumps(RESULTS[self.name])


def fake_vantage_mcp_tools() -> list[FakeMcpTool]:
    """One langchain-shaped fake per vantage tool, for bridge-level code paths."""
    return [FakeMcpTool(name=name) for name in RESULTS]
