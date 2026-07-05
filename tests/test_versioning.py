import pytest

from mira.model.versioning import (
    EvalGateFailed,
    KillSwitchError,
    PromotionError,
    Registry,
    VersionNotFound,
)


def _registry_with_prompts() -> Registry:
    registry = Registry()
    registry.register("prompt/well-summary", "v1", {"template": "Summarize {well_id}"})
    registry.register("prompt/well-summary", "v2", {"template": "Detail {well_id} with logs"})
    return registry


def test_resolve_returns_active_version_in_env():
    registry = _registry_with_prompts()
    registry.promote("prompt/well-summary", "v1", "dev", eval_gate=lambda: True)

    artifact = registry.resolve("prompt/well-summary", "dev")

    assert artifact.version == "v1"
    assert artifact.content["template"] == "Summarize {well_id}"


def test_resolve_raises_when_no_active_version():
    registry = _registry_with_prompts()

    with pytest.raises(VersionNotFound):
        registry.resolve("prompt/well-summary", "dev")


def test_promote_advances_dev_to_staging_to_prod_when_eval_passes():
    registry = _registry_with_prompts()
    registry.promote("prompt/well-summary", "v1", "dev", eval_gate=lambda: True)
    registry.promote("prompt/well-summary", "v1", "staging", eval_gate=lambda: True)
    registry.promote("prompt/well-summary", "v1", "prod", eval_gate=lambda: True)

    assert registry.resolve("prompt/well-summary", "prod").version == "v1"


def test_promote_to_staging_requires_dev_active():
    registry = _registry_with_prompts()

    with pytest.raises(PromotionError):
        registry.promote("prompt/well-summary", "v1", "staging", eval_gate=lambda: True)


def test_promote_to_prod_requires_staging_active():
    registry = _registry_with_prompts()
    registry.promote("prompt/well-summary", "v1", "dev", eval_gate=lambda: True)
    registry.promote("prompt/well-summary", "v1", "staging", eval_gate=lambda: True)

    with pytest.raises(PromotionError):
        registry.promote("prompt/well-summary", "v2", "prod", eval_gate=lambda: True)


def test_promote_rejects_when_eval_gate_fails():
    registry = _registry_with_prompts()
    registry.promote("prompt/well-summary", "v1", "dev", eval_gate=lambda: True)

    with pytest.raises(EvalGateFailed):
        registry.promote("prompt/well-summary", "v1", "staging", eval_gate=lambda: False)

    with pytest.raises(VersionNotFound):
        registry.resolve("prompt/well-summary", "staging")


def test_kill_switch_reverts_to_last_good_without_redeploy():
    registry = _registry_with_prompts()
    registry.promote("prompt/well-summary", "v1", "dev", eval_gate=lambda: True)
    registry.promote("prompt/well-summary", "v1", "staging", eval_gate=lambda: True)
    registry.promote("prompt/well-summary", "v2", "dev", eval_gate=lambda: True)
    registry.promote("prompt/well-summary", "v2", "staging", eval_gate=lambda: True)

    assert registry.resolve("prompt/well-summary", "staging").version == "v2"

    registry.kill_switch("prompt/well-summary", "staging")

    assert registry.resolve("prompt/well-summary", "staging").version == "v1"


def test_kill_switch_raises_when_no_last_good():
    registry = _registry_with_prompts()
    registry.promote("prompt/well-summary", "v1", "dev", eval_gate=lambda: True)

    with pytest.raises(KillSwitchError):
        registry.kill_switch("prompt/well-summary", "dev")


def test_register_rejects_duplicate_version_immutable():
    registry = _registry_with_prompts()

    with pytest.raises(PromotionError, match="already registered"):
        registry.register("prompt/well-summary", "v1", {"template": "tampered"})

    # original content is untouched
    registry.promote("prompt/well-summary", "v1", "dev", eval_gate=lambda: True)
    assert registry.resolve("prompt/well-summary", "dev").content["template"] == "Summarize {well_id}"


def test_promote_to_prod_rejected_when_eval_gate_fails():
    registry = _registry_with_prompts()
    registry.promote("prompt/well-summary", "v1", "dev", eval_gate=lambda: True)
    registry.promote("prompt/well-summary", "v1", "staging", eval_gate=lambda: True)

    with pytest.raises(EvalGateFailed):
        registry.promote("prompt/well-summary", "v1", "prod", eval_gate=lambda: False)

    with pytest.raises(VersionNotFound):
        registry.resolve("prompt/well-summary", "prod")
