import pytest

from mira.config.profiles import PROFILE_ENV, Profile, load_profile


@pytest.fixture(autouse=True)
def _clear_profile_env(monkeypatch):
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    for key in ("PLATFORM", "AUTH_MODE", "MCP_BASE_URL", "AWS_REGION", "OTLP_ENDPOINT", "LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(
    ("name", "platform", "auth_mode"),
    [
        ("saas", "aws", "gateway-injected-tenant"),
        ("standalone", "aws", "customer-idp"),
        ("kubernetes", "aws", "customer-idp"),
        ("outposts", "aws", "customer-idp"),
    ],
)
def test_each_profile_resolves(name, platform, auth_mode):
    profile = load_profile(name)
    assert isinstance(profile, Profile)
    assert profile.name == name
    assert profile.platform == platform
    assert profile.auth_mode == auth_mode
    assert profile.region
    assert profile.observability.log_level == "info"


def test_local_profile_is_dev_default_set():
    # `local` is the dev shape: local infra + skip-auth + localhost MCP server as MCP endpoint.
    profile = load_profile("local")
    assert profile.name == "local"
    assert profile.platform == "local"
    assert profile.auth_mode == "skip"
    assert profile.mcp_endpoint == "http://localhost:8000/mcp"
    assert profile.observability.log_level == "debug"


def test_local_profile_axes_remain_overridable(monkeypatch):
    # Each axis is an independent override over the profile default-set (ADR-047):
    # keep local infra but point the model + MCP elsewhere.
    monkeypatch.setenv("MCP_BASE_URL", "https://saas.example/mcp")
    profile = load_profile("local")
    assert profile.platform == "local"  # unchanged default
    assert profile.mcp_endpoint == "https://saas.example/mcp"  # overridden


def test_outposts_sets_degraded_mode_flag():
    profile = load_profile("outposts")
    assert profile.flags["degraded_mode"] is True


def test_edi_saas_is_multi_tenant():
    profile = load_profile("saas")
    assert profile.flags["multi_tenant"] is True


def test_load_profile_reads_deployment_profile_env(monkeypatch):
    monkeypatch.setenv(PROFILE_ENV, "standalone")
    profile = load_profile()
    assert profile.name == "standalone"


def test_env_overrides_win_over_defaults(monkeypatch):
    monkeypatch.setenv("PLATFORM", "local")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("MCP_BASE_URL", "https://mcp.example")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    profile = load_profile("kubernetes")

    assert profile.platform == "local"
    assert profile.region == "eu-west-1"
    assert profile.mcp_endpoint == "https://mcp.example"
    assert profile.observability.log_level == "debug"


def test_enable_env_overrides_semantic_flag_key(monkeypatch):
    # ENABLE_MULTI_TENANT must override the `multi_tenant` default flag, not
    # add a divergent `ENABLE_MULTI_TENANT` key (ADR-047 feature-flag semantics).
    monkeypatch.setenv("ENABLE_MULTI_TENANT", "false")

    profile = load_profile("saas")

    assert profile.flags["multi_tenant"] is False
    assert "ENABLE_MULTI_TENANT" not in profile.flags


def test_enable_env_adds_new_flag(monkeypatch):
    monkeypatch.setenv("ENABLE_EXPERIMENTAL", "on")

    profile = load_profile("standalone")

    assert profile.flags["experimental"] is True


def test_unknown_profile_raises():
    with pytest.raises(ValueError, match="unknown deployment profile"):
        load_profile("does-not-exist")


def test_unset_deployment_profile_raises(monkeypatch):
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    with pytest.raises(ValueError, match=f"{PROFILE_ENV} is unset"):
        load_profile()


def test_empty_deployment_profile_raises(monkeypatch):
    monkeypatch.setenv(PROFILE_ENV, "")
    with pytest.raises(ValueError, match=f"{PROFILE_ENV} is unset"):
        load_profile()
