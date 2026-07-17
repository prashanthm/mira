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

# ── decision journal (analysis / position_actions) ──────────────────────────
# Two losing positions eligible to CLOSE_AND_BOOK_LOSS — one wash-safe (BBAI,
# like the live journal) and one wash-BLOCKED (SNAP) — plus one
# HOLD_AND_SELL_CALL (PLTR) so the advisor can narrate the persisted playbook.
# Numbers mirror the engine's action_detail shape verbatim (the advisor repeats
# them, never recomputes).


def _conviction(label: str, score: float) -> dict[str, Any]:
    return {"label": label, "score": score}


_DECISIONS: list[dict[str, Any]] = [
    {
        "symbol": "BBAI",
        "as_of": "2025-07-15",
        "current_price": 3.53,
        "conviction": _conviction("freefall", -1.0),
        "recommendation": "CLOSE_AND_BOOK_LOSS",
        "rule": "rule2_freefall_close",
        "rationale": (
            "BBAI broke support with momentum (conviction freefall -1.00); the "
            "decline is structural. Book the loss (wash-safe) and redeploy."
        ),
        "evidence": {
            "nearest_support": {"price": 3.47, "strength": 3.0, "kind": "support"},
            "nearest_resistance": {"price": 3.65, "strength": 6.0, "kind": "resistance"},
            "broke_support_with_momentum": True,
            "conviction": _conviction("freefall", -1.0),
        },
        "action_detail": {
            "kind": "close",
            "unrealized_loss": -367.0,
            "wash_blocked": False,
            "wash_reason": None,
            "wash_clears_on": None,
            "est_weekly_credit": 4.22,
            "weeks_to_offset_at_est_credit": 87.0,
        },
    },
    {
        "symbol": "SNAP",
        "as_of": "2025-07-15",
        "current_price": 8.10,
        "conviction": _conviction("freefall", -0.9),
        "recommendation": "CLOSE_AND_BOOK_LOSS",
        "rule": "rule2_freefall_close",
        "rationale": (
            "SNAP broke support with momentum (conviction freefall -0.90). The "
            "loss is real but a recent repurchase makes the sale wash-blocked — "
            "closing now defers the loss."
        ),
        "evidence": {
            "nearest_support": {"price": 7.90, "strength": 4.0, "kind": "support"},
            "nearest_resistance": {"price": 8.60, "strength": 3.0, "kind": "resistance"},
            "broke_support_with_momentum": True,
            "conviction": _conviction("freefall", -0.9),
        },
        "action_detail": {
            "kind": "close",
            "unrealized_loss": -512.0,
            "wash_blocked": True,
            "wash_reason": "IRA bought SNAP on Jul 2 (auto-invest)",
            "wash_clears_on": "2025-08-02",
            "est_weekly_credit": 6.10,
            "weeks_to_offset_at_est_credit": 84.0,
        },
    },
    {
        "symbol": "PLTR",
        "as_of": "2025-07-15",
        "current_price": 129.30,
        "conviction": _conviction("strong", 0.7),
        "recommendation": "HOLD_AND_SELL_CALL",
        "rule": "rule1_strong_at_support",
        "rationale": (
            "PLTR reads STRONG at support and basing (conviction +0.70). Sell a "
            "~7-DTE OTM call at $132.56 for an estimated $444 credit."
        ),
        "evidence": {
            "nearest_support": {"price": 128.63, "strength": 2.0, "kind": "support"},
            "nearest_resistance": {"price": 132.56, "strength": 3.0, "kind": "resistance"},
            "broke_support_with_momentum": False,
            "conviction": _conviction("strong", 0.7),
        },
        "action_detail": {
            "kind": "sell_call",
            "suggested_strike": 132.56,
            "strike_basis": "near resistance",
            "expiry_dte": 7,
            "est_credit": 444.44,
            "contracts": 2,
            "current_net_cost": 3285.0,
            "projected_net_cost": 2840.56,
            "basis_reduction": 444.44,
        },
    },
]

ANALYSIS_RESULT = _envelope(
    "analysis",
    date="2025-07-15",
    generated_at=AS_OF,
    symbol=None,
    decisions=[json.loads(json.dumps(d)) for d in _DECISIONS],
)

POSITION_ACTIONS_RESULT = _envelope(
    "position_actions",
    date="2025-07-15",
    symbol=None,
    actions=[
        {
            "symbol": d["symbol"],
            "conviction": d["conviction"],
            "recommendation": d["recommendation"],
            "rationale": d["rationale"],
            "action_detail": d["action_detail"],
            # V3 position context: sizing is decision-critical for add/close
            "position_context": {
                "weight_pct": 6.2, "value": 12_679.0, "x_median_position": 3.1,
            },
        }
        for d in _DECISIONS
    ],
)

# ── trade analytics (roundtrips / trade_stats) ───────────────────────────────
# Shapes copied verbatim from the Vantage ML surface (api.py /api/ml/*). The
# numbers mirror the real built data: baseline win-rate 37.8%, profit factor
# 0.77, and exactly ONE defensible edge (day_of_week=Thursday, win 75%, n=8, CI
# clears baseline → significant). A second notable row (a thin bucket that
# separates but n<min_n) is included with significant=False so tests can prove
# a small-n bucket is NEVER promoted to a lesson/edge.

ROUNDTRIPS_RESULT = _envelope(
    "roundtrips",
    account="all",
    symbol=None,
    roundtrips_as_of="2025-07-15",
    roundtrips=[
        {
            "symbol": "PLTR",
            "kind": "option",
            "open_date": "2025-06-30",
            "close_date": "2025-07-03",
            "holding_days": 3,
            "realized_pnl": 444.0,
            "realized_pct": 13.5,
            "win": True,
            "mfe": 520.0,
            "mae": -60.0,
            "mfe_capture": 0.85,
            "entry_unknown": False,
        },
        {
            "symbol": "SNAP",
            "kind": "equity",
            "open_date": "2025-06-24",
            "close_date": "2025-07-01",
            "holding_days": 7,
            "realized_pnl": -512.0,
            "realized_pct": -6.1,
            "win": False,
            "mfe": 80.0,
            "mae": -540.0,
            "mfe_capture": -0.20,
            "entry_unknown": False,
        },
    ],
    summary={
        "count": 37,
        "wins": 14,
        "losses": 23,
        "win_rate": 0.3784,
        "avg_win": 543.21,
        "avg_loss": -427.07,
        "gross_profit": 7605.0,
        "gross_loss": 9822.61,
        "profit_factor": 0.7742,
        "avg_holding_days": 7.19,
        "avg_mfe_capture": -0.2478,
        "entry_unknown": 6,
        "by_kind": {
            "equity": {"count": 9, "win_rate": 0.1111, "profit_factor": 0.0396},
            "option": {"count": 28, "win_rate": 0.4643, "profit_factor": 0.8312},
        },
    },
)

TRADE_STATS_RESULT = _envelope(
    "trade_stats",
    account="all",
    dimension=None,
    trade_stats_as_of="2025-07-15",
    baseline_win_rate=0.378378,
    buckets=[
        {
            "dimension": "__baseline__",
            "value": "all_trades",
            "n": 37,
            "wins": 14,
            "losses": 23,
            "win_rate": 0.378378,
            "ci_low": 0.25,
            "ci_high": 0.52,
            "ci": 0.90,
            "avg_pnl": -59.9,
            "total_pnl": -2217.61,
        },
        {
            "dimension": "day_of_week",
            "value": "Thursday",
            "n": 8,
            "wins": 6,
            "losses": 2,
            "win_rate": 0.75,
            "ci_low": 0.450358,
            "ci_high": 0.902253,
            "ci": 0.90,
            "avg_pnl": 210.0,
            "total_pnl": 1680.0,
        },
        {
            # A THIN bucket that separates but is too small — must never be a lesson.
            "dimension": "moneyness",
            "value": "deep_itm",
            "n": 2,
            "wins": 2,
            "losses": 0,
            "win_rate": 1.0,
            "ci_low": 0.34,
            "ci_high": 0.99,
            "ci": 0.90,
            "avg_pnl": 300.0,
            "total_pnl": 600.0,
        },
    ],
    notable=[
        {
            "dimension": "day_of_week",
            "value": "Thursday",
            "n": 8,
            "wins": 6,
            "losses": 2,
            "win_rate": 0.75,
            "ci_low": 0.450358,
            "ci_high": 0.902253,
            "ci": 0.90,
            "avg_pnl": 210.0,
            "total_pnl": 1680.0,
            "kind": "edge",
            "edge": 0.371622,
            "significant": True,
        },
        {
            # Present in notable (it separates) but significant=False (n<min_n).
            "dimension": "moneyness",
            "value": "deep_itm",
            "n": 2,
            "wins": 2,
            "losses": 0,
            "win_rate": 1.0,
            "ci_low": 0.34,
            "ci_high": 0.99,
            "ci": 0.90,
            "avg_pnl": 300.0,
            "total_pnl": 600.0,
            "kind": "edge",
            "edge": 0.621622,
            "significant": False,
            "note": "n<min, not significant",
        },
    ],
)

# ── analysis facets (bars / fundamentals / news) ─────────────────────────────
# Shapes copied from the Vantage MCP surface: vantage.bars (levels), the new
# vantage.fundamentals (valuation, nulls for ETFs), and vantage.news (aggregated
# headlines + a headline sentiment lean, estimated=true).

BARS_RESULT = _envelope(
    "bars",
    symbol="PLTR",
    timeframe="daily",
    no_bars=False,
    bars=[
        {"date": "2025-07-14", "open": 128.0, "high": 130.1, "low": 127.5,
         "close": 129.3, "volume": 41_000_000},
    ],
    levels={
        "support": [{"price": 128.63, "strength": 2.0, "kind": "support"}],
        "resistance": [{"price": 132.56, "strength": 3.0, "kind": "resistance"}],
    },
    first_bar="2015-07-15",
    last_bar="2025-07-14",
    bar_count=2517,
)

FUNDAMENTALS_RESULT = _envelope(
    "fundamentals",
    symbol="PLTR",
    no_data=False,
    fundamentals={
        "symbol": "PLTR",
        "name": "Palantir Technologies Inc.",
        "sector": "Technology",
        "market_cap": 295_000_000_000.0,
        "pe": 210.5,
        "forward_pe": 180.2,
        "week52_low": 20.33,
        "week52_high": 133.49,
        "target_mean": 98.4,
        "dividend_yield": None,
        "beta": 2.65,
    },
)

NEWS_RESULT = _envelope(
    "news",
    symbol="PLTR",
    no_news=False,
    news={
        "symbol": "PLTR",
        "items": [
            {
                "title": "Palantir surges after record profit and raised guidance",
                "summary": "Strong quarter beats estimates.",
                "publisher": "Reuters",
                "published": "2025-07-14T13:00:00Z",
                "url": "https://example.com/pltr-1",
                "source": "yfinance",
            },
            {
                "title": "Analysts debate Palantir's rich valuation",
                "summary": "Bulls and bears weigh in.",
                "publisher": "Bloomberg",
                "published": "2025-07-13T18:30:00Z",
                "url": "https://example.com/pltr-2",
                "source": "yfinance",
            },
        ],
        "sentiment": {
            "score": 0.5,
            "band": "positive",
            "n_headlines": 2,
            "method": "lexicon",
            "estimated": True,
        },
    },
)

GROWTH_RESULT = _envelope(
    "growth",
    symbol="PLTR",
    no_data=False,
    growth={
        "symbol": "PLTR",
        "revenue_ttm": 3_800_000_000.0,
        "revenue_yoy": 0.33,
        "revenue_yoy_basis": "ttm",
        "gross_margin": 0.80,
        "operating_margin": 0.14,
        "fcf_ttm": 1_200_000_000.0,
        "fcf_margin": 0.32,
        "sbc_ttm": 600_000_000.0,
        "sbc_pct_revenue": 0.16,
        "rule_of_40": 65.0,
        "rule_of_40_basis": "yoy_growth_plus_fcf_margin",
        "period_end": "2025-06-30",
    },
)

EXPECTATIONS_RESULT = _envelope(
    "expectations",
    symbol="PLTR",
    no_data=False,
    inputs={
        "fcf_ttm": 1_200_000_000.0,
        "market_cap": 295_000_000_000.0,
        "enterprise_value": 291_000_000_000.0,
        "value_basis": "enterprise_value",
        "price": 126.79,
        "shares_outstanding": 2_400_000_000.0,
    },
    assumptions={
        "discount_rate": 0.095,
        "terminal_growth": 0.025,
        "horizon_years": 10,
        "model": "two_stage_fcf_reverse_dcf",
    },
    implied={"fcf_growth_10y": 0.42, "clamped": None, "status": "ok"},
    scenarios=[
        {"growth": 0.0, "fair_value": 21_000_000_000.0,
         "fair_value_per_share": 8.75, "vs_price_pct": -93.1},
        {"growth": 0.10, "fair_value": 34_000_000_000.0,
         "fair_value_per_share": 14.17, "vs_price_pct": -88.8},
        {"growth": 0.20, "fair_value": 57_000_000_000.0,
         "fair_value_per_share": 23.75, "vs_price_pct": -81.3},
        {"growth": 0.30, "fair_value": 96_000_000_000.0,
         "fair_value_per_share": 40.0, "vs_price_pct": -68.5},
    ],
)

# days_until=5 exercises the synthesis earnings gate (report within a week).
EARNINGS_RESULT = _envelope(
    "earnings",
    symbol="PLTR",
    no_data=False,
    earnings={
        "next_date": "2025-07-20",
        "days_until": 5,
        "last_date": "2025-05-05",
        "days_since": 71,
        "recent": [
            {"date": "2025-07-20", "eps_estimate": 0.09, "eps_actual": None},
            {"date": "2025-05-05", "eps_estimate": 0.08, "eps_actual": 0.10},
        ],
        "dates_as_of": "2025-07-14",
        "future_date_known": True,
        "catalyst_path": {
            "events": [
                {"kind": "opex", "date": "2025-07-18", "days_until": 3,
                 "note": "monthly OpEx — dealer positioning rolls off"},
                {"kind": "earnings", "date": "2025-07-20", "days_until": 5,
                 "note": "quarterly earnings report — biggest single-name catalyst"},
            ],
            "next": {"kind": "opex", "date": "2025-07-18", "days_until": 3,
                     "note": "monthly OpEx — dealer positioning rolls off"},
            "horizon_days": 90,
        },
        "next_catalyst": {"kind": "opex", "date": "2025-07-18", "days_until": 3,
                          "note": "monthly OpEx — dealer positioning rolls off"},
    },
)

TICKER_PLAN_RESULT = _envelope(
    "ticker_plan",
    symbol="PLTR",
    has_plan=True,
    risk_reward={
        "price": 126.79, "target": 180.0, "stop": 95.0,
        "upside": 53.21, "downside": 31.79, "rr_ratio": 1.67,
        "upside_pct": 42.0, "downside_pct": 25.1, "status": "ok",
    },
    plan={
        "thesis": "AIP land-and-expand converts gov credibility into commercial "
                  "growth; hold while US commercial revenue accelerates.",
        "target": 180.0,
        "stop": 95.0,
        "notes": "Re-evaluate if US commercial growth decelerates two quarters running.",
        "updated_at": "2025-06-20T10:00:00",
    },
    journal=[
        {"created_at": "2025-06-20T10:00:00", "kind": "note",
         "payload": {"text": "Trimmed 10% into strength at 142."}},
    ],
)

RELATIVE_STRENGTH_RESULT = _envelope(
    "relative_strength",
    symbol="PLTR",
    no_data=False,
    relative_strength={
        "symbol": "PLTR", "sector_etf": "XLK",
        "r_1w": -0.06, "r_1m": -0.12, "r_3m": -0.05,
        "spy_r_1w": -0.01, "spy_r_1m": -0.02, "spy_r_3m": 0.03,
        "sector_r_1w": -0.02, "sector_r_1m": -0.04, "sector_r_3m": 0.01,
        "beta_spy": 1.8, "idio_r_1m": -0.084,
        "basis": "idio_r_1m = r_1m - beta_spy * spy_r_1m (daily closes)",
        "benchmark_available": True,
    },
)

REC_SCORECARD_RESULT = _envelope(
    "rec_scorecard",
    no_data=False,
    scorecard={
        "rules": [
            {"rule": "rule2_freefall_close", "recommendation": "CLOSE_AND_BOOK_LOSS",
             "n_scored": 34, "hit_rate": 0.62, "n_calls": 34,
             "avg_fwd_5d": -0.012, "avg_fwd_20d": -0.031},
            {"rule": "rule1_strong_at_support", "recommendation": "HOLD_AND_SELL_CALL",
             "n_scored": 21, "hit_rate": 0.71, "n_calls": 21,
             "avg_fwd_5d": 0.004, "avg_fwd_20d": 0.018},
        ],
        "n_pending": 5,
        "hit_basis": "bearish calls (CLOSE_*) hit when +20d return < 0; "
                     "constructive calls (HOLD_*) hit when +20d >= 0; "
                     "MONITOR excluded from hit rates",
        "horizons_days": [5, 20],
    },
)

# ── replay forecast grading (vantage.replay_forecasts) ───────────────────────
# The graded-run bundle a forecast_grader reads: forecasts WITH their CODE-computed
# scores + the deterministic calibration. The grader NARRATES these numbers — it
# never computes them — so the fixture ships the scores already resolved. One
# bucket (premarket) is deliberately below the min sample → insufficient, to prove
# the grader says "insufficient sample" and never fabricates a rate.

_REPLAY_STEPS = [
    {"id": 1, "as_of": "2026-07-16T09:35:00-04:00", "time_bucket": "open (09:30-11:00)",
     "price_at": 7500.0, "bias": "up", "target": 7525.0, "invalidation": 7480.0,
     "tier": "A+", "verdict": "hit target", "moved_pt": 26.0, "hit": True},
    {"id": 2, "as_of": "2026-07-16T10:05:00-04:00", "time_bucket": "open (09:30-11:00)",
     "price_at": 7522.0, "bias": "up", "target": 7540.0, "invalidation": 7505.0,
     "tier": "A+", "verdict": "hit target", "moved_pt": 19.0, "hit": True},
    {"id": 3, "as_of": "2026-07-16T10:35:00-04:00", "time_bucket": "open (09:30-11:00)",
     "price_at": 7538.0, "bias": "up", "target": 7555.0, "invalidation": 7520.0,
     "tier": "none", "verdict": "direction correct", "moved_pt": 11.0, "hit": True},
    {"id": 4, "as_of": "2026-07-16T12:05:00-04:00", "time_bucket": "midday (11:00-14:00)",
     "price_at": 7548.0, "bias": "up", "target": 7565.0, "invalidation": 7530.0,
     "tier": "none", "verdict": "invalidated", "moved_pt": -22.0, "hit": False},
    {"id": 5, "as_of": "2026-07-16T13:05:00-04:00", "time_bucket": "midday (11:00-14:00)",
     "price_at": 7526.0, "bias": "down", "target": 7505.0, "invalidation": 7545.0,
     "tier": "B", "verdict": "hit target", "moved_pt": -24.0, "hit": True},
    {"id": 6, "as_of": "2026-07-16T15:05:00-04:00", "time_bucket": "close (14:00-16:00)",
     "price_at": 7503.0, "bias": "down", "target": 7488.0, "invalidation": 7520.0,
     "tier": "B", "verdict": "direction wrong", "moved_pt": 9.0, "hit": False},
]

_REPLAY_BUNDLE = {
    "run_id": "rf-SPX-2026-07-16-demo",
    "day": "2026-07-16",
    "underlying": "SPX",
    "n_forecasts": 6,
    "n_scored": 6,
    "scores": {
        "overall": {"n": 6, "wins": 4, "hit_rate": 0.667},
        "by_time": {
            "open (09:30-11:00)": {"n": 3, "wins": 3, "hit_rate": 1.0},
            "midday (11:00-14:00)": {"n": 2, "insufficient": True},
            "close (14:00-16:00)": {"n": 1, "insufficient": True},
        },
        "by_bias": {
            "up": {"n": 4, "wins": 3, "hit_rate": 0.75},
            "down": {"n": 2, "insufficient": True},
        },
        "by_tier": {
            "A+": {"n": 2, "insufficient": True},
            "B": {"n": 2, "insufficient": True},
            "none": {"n": 2, "insufficient": True},
        },
    },
    "steps": _REPLAY_STEPS,
    "prior": None,
}

REPLAY_FORECASTS_RESULT = _envelope(
    "replay_forecasts",
    bundle=_REPLAY_BUNDLE,
    prompt=(
        "You are grading a REPLAY FORECAST run: the SPX-analyst was asked 'what "
        "will price do?' at each interval step through SPX on 2026-07-16 "
        "(6 forecasts, 6 resolved). SCORES — ALREADY COMPUTED IN CODE. Read and "
        "narrate them; NEVER compute, alter, or invent a score or hit-rate."
    ),
)

RESULTS: dict[str, dict[str, Any]] = {
    "vantage.positions": POSITIONS_RESULT,
    "vantage.allocation": ALLOCATION_RESULT,
    "vantage.wash_status": WASH_STATUS_RESULT,
    "vantage.tlh_candidates": TLH_CANDIDATES_RESULT,
    "vantage.lots": LOTS_RESULT,
    "vantage.quotes": QUOTES_RESULT,
    "vantage.analysis": ANALYSIS_RESULT,
    "vantage.position_actions": POSITION_ACTIONS_RESULT,
    "vantage.roundtrips": ROUNDTRIPS_RESULT,
    "vantage.trade_stats": TRADE_STATS_RESULT,
    "vantage.bars": BARS_RESULT,
    "vantage.fundamentals": FUNDAMENTALS_RESULT,
    "vantage.news": NEWS_RESULT,
    "vantage.growth": GROWTH_RESULT,
    "vantage.expectations": EXPECTATIONS_RESULT,
    "vantage.earnings": EARNINGS_RESULT,
    "vantage.ticker_plan": TICKER_PLAN_RESULT,
    "vantage.relative_strength": RELATIVE_STRENGTH_RESULT,
    "vantage.rec_scorecard": REC_SCORECARD_RESULT,
    "vantage.replay_forecasts": REPLAY_FORECASTS_RESULT,
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
