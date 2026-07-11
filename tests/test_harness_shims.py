"""Shim identity tests (ADR-050): old paths re-export the same objects.

The pre-existing test files keep importing the old paths — that is the
behavioral compat proof; these tests pin object *identity* so a shim can
never silently fork.
"""

from __future__ import annotations

import importlib

import pytest

SHIMS = [
    ("mira.model.versioning", "mira_harness.versioning"),
    ("evals.trace_scoring", "mira_harness.scoring"),
    ("mira.tools.contract", "mira_contracts.tooling"),
    ("mira.model.cost_attribution", "mira_harness.cost"),
]

# Not a pure shim — guardrails keeps the middleware halves — but every
# extracted detector name must still be the mira_harness.policy object.
DETECTOR_NAMES = (
    "GuardrailViolation",
    "ViolationFinding",
    "InjectionDetector",
    "ToolAbuseDetector",
    "GroundednessChecker",
    "TopicDriftDetector",
    "INJECTION_CODE",
    "UNGROUNDED_CODE",
    "TOPIC_DRIFT_CODE",
)


def test_guardrails_reexports_policy_detectors():
    guardrails = importlib.import_module("mira.core.guardrails")
    policy = importlib.import_module("mira_harness.policy")
    for name in DETECTOR_NAMES:
        assert getattr(guardrails, name) is getattr(policy, name)


@pytest.mark.parametrize("old_path,new_path", SHIMS, ids=[old for old, _ in SHIMS])
def test_shim_reexports_identical_objects(old_path, new_path):
    old = importlib.import_module(old_path)
    new = importlib.import_module(new_path)
    assert old.__all__, f"{old_path} shim must declare an explicit __all__"
    for name in old.__all__:
        assert getattr(old, name) is getattr(new, name), (
            f"{old_path}.{name} is not the object from {new_path} — shims must "
            "re-export, never fork (ADR-050)"
        )
