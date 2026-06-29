"""Structured output contract for an insight run."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Insight(BaseModel):
    """One concrete observation, grounded in the data."""
    topic: str = Field(..., description="Short label, e.g. 'bull_put_credit in pass_bearish'")
    detail: str = Field(..., description="What was observed and why it matters")
    evidence: str = Field("", description="The data that supports this (counts, grades, win-rates)")


class InsightReport(BaseModel):
    """The advisory report the panel produces. Never an instruction to trade."""
    summary: str = Field(..., description="2-3 sentence executive summary")
    what_worked: list[Insight] = Field(default_factory=list)
    what_didnt: list[Insight] = Field(default_factory=list)
    adjustments: list[str] = Field(
        default_factory=list,
        description="Advisory suggestions for the playbook/process — NOT auto-applied",
    )
    confidence: str = Field("low", description="low | medium | high — given the sample size")
    caveats: str = Field("", description="Data limitations the reader should weigh")


# JSON schema handed to the model for structured output.
INSIGHT_JSON_SCHEMA = InsightReport.model_json_schema()
