"""Tests for role-based storage behind Protocols (ADR-021).

Asserts the factory resolves all four storage roles for both a cloud-style
profile and an on-prem profile, and that every resolved engine conforms to its
role Protocol — without importing any cloud SDK.
"""

import pytest

from mira.config.profiles import load_profile
from mira.fabric.storage import (
    IGraphStore,
    IRelationalStore,
    IStateCache,
    IVectorIndex,
    StorageBundle,
    get_storage,
)

# A cloud-style profile (platform == "aws") and an on-prem profile; both resolve
# all four roles through the portable default today (ADR-021).
CLOUD_PROFILE = "saas"
ON_PREM_PROFILE = "outposts"


def test_cloud_profile_resolves_all_four_roles():
    bundle = get_storage(CLOUD_PROFILE)

    assert isinstance(bundle, StorageBundle)
    assert isinstance(bundle.graph, IGraphStore)
    assert isinstance(bundle.vector, IVectorIndex)
    assert isinstance(bundle.state, IStateCache)
    assert isinstance(bundle.relational, IRelationalStore)


def test_on_prem_profile_resolves_all_four_roles():
    bundle = get_storage(ON_PREM_PROFILE)

    assert isinstance(bundle, StorageBundle)
    assert isinstance(bundle.graph, IGraphStore)
    assert isinstance(bundle.vector, IVectorIndex)
    assert isinstance(bundle.state, IStateCache)
    assert isinstance(bundle.relational, IRelationalStore)


def test_get_storage_accepts_resolved_profile_object():
    profile = load_profile(ON_PREM_PROFILE)
    bundle = get_storage(profile)
    assert isinstance(bundle.graph, IGraphStore)


def test_get_storage_rejects_unknown_profile():
    with pytest.raises(ValueError):
        get_storage("not-a-profile")


def test_graph_store_round_trips_nodes_and_edges():
    bundle = get_storage(ON_PREM_PROFILE)
    bundle.graph.add_node("well-a", kind="well")
    bundle.graph.add_node("log-1", kind="log")
    bundle.graph.add_edge("well-a", "log-1", "has_log")

    assert bundle.graph.neighbors("well-a") == ["log-1"]
    assert bundle.graph.neighbors("log-1") == []


def test_vector_index_search_ranks_by_similarity():
    bundle = get_storage(ON_PREM_PROFILE)
    bundle.vector.upsert("near", [1.0, 0.0])
    bundle.vector.upsert("far", [0.0, 1.0])

    assert bundle.vector.search([1.0, 0.0], top_k=1) == ["near"]


def test_state_cache_get_set():
    bundle = get_storage(ON_PREM_PROFILE)
    assert bundle.state.get("session:1") is None
    bundle.state.set("session:1", "active")
    assert bundle.state.get("session:1") == "active"


def test_relational_store_insert_and_filtered_select():
    bundle = get_storage(ON_PREM_PROFILE)
    bundle.relational.insert("evals", {"run": "r1", "score": 0.9})
    bundle.relational.insert("evals", {"run": "r2", "score": 0.4})

    assert bundle.relational.select("evals", run="r1") == [{"run": "r1", "score": 0.9}]
    assert len(bundle.relational.select("evals")) == 2


def test_bundles_are_isolated_per_resolution():
    """Each get_storage call returns fresh engines (no shared mutable state)."""
    first = get_storage(ON_PREM_PROFILE)
    first.state.set("k", "v")
    second = get_storage(ON_PREM_PROFILE)
    assert second.state.get("k") is None
