"""Langfuse export is opt-in + fail-open: a pure no-op unless LANGFUSE_* is set
and the SDK is present, and never raises regardless."""
from __future__ import annotations

import mira.model.langfuse_export as lf


def _reset():
    lf._CLIENT = None
    lf._TRIED = False


def test_disabled_without_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    _reset()
    assert lf.enabled() is False
    # every entry point is a safe no-op when disabled
    lf.export_call(op="classify", agent="synthesis", model="m", provider="p",
                   request="q", response="a", usage={"prompt_tokens": 1},
                   cost_usd=0.001, latency_ms=10.0, correlation_id="c", error=None)
    lf.score("c", "hit", 1.0)


def test_configured_but_sdk_absent_stays_noop(monkeypatch):
    """Keys set but the langfuse SDK not installed → still a no-op, no crash."""
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    _reset()
    # SDK isn't installed in the test env, so client init fails → disabled
    assert lf.enabled() is False
    lf.export_call(op="turn_synthesis", agent="synthesis", model="m", provider="p",
                   request="q", response="a", usage=None, cost_usd=None,
                   latency_ms=5.0, correlation_id=None, error="boom")
