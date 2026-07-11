"""Shim (ADR-050): trace scoring moved to :mod:`mira_harness.scoring`.

Re-exports only — never fork this module; new symbols land in the new home.
"""

from __future__ import annotations

from mira_harness.scoring import DIMENSIONS, TraceScore, score_run, score_trace

__all__ = ["DIMENSIONS", "TraceScore", "score_run", "score_trace"]
