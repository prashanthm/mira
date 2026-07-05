"""Tests for the aggregate-vs-federate policy (ADR-019)."""

import pytest

from mira.fabric.policy import AGGREGATE, FEDERATE, decide


@pytest.mark.parametrize(
    "source",
    ["warehouse", "Warehouse", "stream", "ledger", "docs", "timeseries"],
)
def test_immovable_sources_federate(source):
    # Operational / immovable / system-of-record sources federate regardless of
    # data kind (ADR-019 Rule 1) — including for analytical data kinds.
    assert decide(source, "records") == FEDERATE
    assert decide(source, "embeddings") == FEDERATE


@pytest.mark.parametrize(
    "data_kind",
    ["embeddings", "rag", "rag-corpus", "session", "eval", "eval-goldens"],
)
def test_analytical_data_kinds_aggregate(data_kind):
    # Analytical / RAG / session / eval data kinds aggregate when the source is
    # not itself immovable (ADR-019 Rule 2).
    assert decide("scratch-export", data_kind) == AGGREGATE


def test_source_takes_precedence_over_data_kind():
    # An immovable source overrides an aggregate-leaning data kind.
    assert decide("ledger", "embeddings") == FEDERATE


def test_unknown_defaults_to_federate():
    # Conservative default keeps data at the source (ADR-019 Rule 3).
    assert decide("mystery-system", "unknown-kind") == FEDERATE


def test_classification_is_case_insensitive():
    assert decide("TIMESERIES", "EMBEDDINGS") == FEDERATE  # source rule wins
    assert decide("Snowflake", "EvAl") == AGGREGATE


def test_decision_values_are_the_two_literals():
    result = decide("docs", "sections")
    assert result in {"federate", "aggregate"}
    assert FEDERATE == "federate"
    assert AGGREGATE == "aggregate"
