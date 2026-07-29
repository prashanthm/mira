"""0DTE SPX playbook: templated draft, LLM polish, provider fetch, degrade."""

from __future__ import annotations

from mira.orchestration.playbook import build_playbook_result, cached_playbook_provider
from mira.orchestration.synthesis import playbook_template, synthesize_playbook


def _scaffold():
    return {
        "symbol": "SPX", "session": "2026-07-08",
        "regime": {"gamma": "positive", "spot": 7503.9, "vix": 16.1,
                   "vix_band": "normal", "vwap_regime": "above VWAP (buyers in control)"},
        "level_ladder": [
            {"price": 7550.0, "kind": "GEX call wall (resistance)", "source": "GEX"},
            {"price": 7500.0, "kind": "max pain (pin)", "source": "GEX"},
            {"price": 7481.0, "kind": "gamma flip (regime line)", "source": "GEX"},
            {"price": 7450.0, "kind": "GEX put wall (support)", "source": "GEX"},
        ],
        "setups": [
            {"trigger": "SPX holds above the gamma flip 7481", "bias": "mean-reversion",
             "structure": "Fade the extremes: an iron condor roughly 7450/7550 plays the range.",
             "levels": {"put_wall": 7450, "call_wall": 7550}},
            {"trigger": "SPX breaks BELOW the gamma flip 7481 with momentum", "bias": "momentum",
             "structure": "Long puts toward 7450.", "levels": {"put_wall": 7450}},
        ],
        "catalysts": {"available": True, "today": "CPI", "next_session": None},
        "opex": {"today_is_triple_witching": False},
        "edges": {"gex_regime_next_day_range": {"read": "Positive-gamma days averaged 53.8pt (n=2)."}},
        "caveats": ["The GEX read is 0DTE-blind.", "Context not a signal (ADR-008). Not advice."],
    }


class _CapturingLLM:
    def __init__(self, reply="SIMPLE PLAYBOOK PROSE"):
        self.reply = reply; self.prompts = []; self.models = []

    def complete(self, prompt, *, model=None):
        self.prompts.append(prompt); self.models.append(model); return self.reply

    def embed(self, text):
        return [0.0]


# ------------------------------------------------------------ templated draft

def test_template_is_grounded_and_complete():
    d = playbook_template(_scaffold())
    assert "2026-07-08" in d
    assert "positive" in d and "7481" in d          # regime + flip level
    assert "iron condor" in d and "7450" in d             # setup verbatim
    assert "CPI" in d                                # catalyst
    assert "0DTE-blind" in d and "ADR-008" in d      # caveats preserved


def test_template_never_invents():
    # a minimal scaffold: the draft must not add levels that aren't there
    d = playbook_template({"session": "X", "level_ladder": [], "setups": [], "caveats": []})
    assert "7481" not in d and "iron condor" not in d


# ------------------------------------------------------------ LLM polish

def test_polish_requests_light_tier_via_chat():
    class _ChatLLM:
        def __init__(self):
            self.tiers = []

        def chat(self, messages, *, model=None, tools=None, tool_choice="auto", tier=None):
            self.tiers.append(tier)

            class _Reply:
                text = "SIMPLE PLAYBOOK PROSE"
                tool_calls = ()

            return _Reply()

        def embed(self, text):
            return [0.0]

    llm = _ChatLLM()
    out = synthesize_playbook(llm, _scaffold())
    assert out == "SIMPLE PLAYBOOK PROSE"
    assert llm.tiers == ["light"]  # polish rides the cheap tier


def test_polish_passes_the_draft_and_numbers():
    llm = _CapturingLLM()
    out = synthesize_playbook(llm, _scaffold())
    assert out == "SIMPLE PLAYBOOK PROSE"
    p = llm.prompts[0]
    assert "iron condor" in p and "7450" in p and "7481" in p  # the draft reached the model


def test_polish_degrades_to_draft_on_no_llm():
    out = synthesize_playbook(None, _scaffold())
    assert "iron condor" in out and "7450" in out  # the templated draft itself


def test_polish_degrades_to_draft_on_llm_error():
    class _Boom:
        def complete(self, prompt, *, model=None):
            raise RuntimeError("down")

        def embed(self, text):
            return [0.0]

    out = synthesize_playbook(_Boom(), _scaffold())
    assert "iron condor" in out and "7450" in out  # fell back, never blanked


# ------------------------------------------------------------ provider (MCP fetch)

class _FakeTool:
    def __init__(self, name, result):
        self.name = name

        class _C:  # contract.name
            pass
        self.contract = _C(); self.contract.name = name
        self._result = result

    def handler(self, payload):
        return self._result


def _envelope(scaffold):
    return {"available": True, "source": "fixture", "as_of": "x",
            "playbook": {"date": "2026-07-07", "session": scaffold.get("session"),
                         "scaffold": scaffold, "narrative": None},
            "provenance": {"source_type": "vantage", "source_id": "d#spx_playbook"}}


def test_provider_fetches_and_narrates():
    tool = _FakeTool("vantage.spx_playbook", _envelope(_scaffold()))
    out = build_playbook_result([tool], llm=_CapturingLLM("PROSE"))
    assert out["available"] is True
    assert out["session"] == "2026-07-08"
    assert out["narrative"] == "PROSE"
    assert "iron condor" in out["draft"] and "7450" in out["draft"]


def test_provider_degrades_when_tool_absent():
    out = build_playbook_result([], llm=None)
    assert out["available"] is False
    assert "not available" in out["reason"]


def test_provider_degrades_when_no_playbook():
    tool = _FakeTool("vantage.spx_playbook", {"available": False, "no_playbook": True})
    out = build_playbook_result([tool], llm=None)
    assert out["available"] is False


def test_cached_provider_caches_and_refreshes():
    calls = {"n": 0}

    class _CountingTool:
        name = "vantage.spx_playbook"

        def __init__(self):
            class _C: pass
            self.contract = _C(); self.contract.name = self.name

        def handler(self, payload):
            calls["n"] += 1
            return _envelope(_scaffold())

    provider = cached_playbook_provider([_CountingTool()], llm=None)
    provider(None)
    assert calls["n"] == 1
    provider(None)             # cached
    assert calls["n"] == 1
    provider(None, refresh=True)  # regenerate
    assert calls["n"] == 2


class _RaisingTool:
    """A tool that raises — models vantage raising PlaybookStale/Unavailable."""
    name = "vantage.spx_playbook"

    def __init__(self, calls):
        self._calls = calls
        class _C: pass
        self.contract = _C(); self.contract.name = self.name

    def handler(self, payload):
        self._calls["n"] += 1
        raise RuntimeError("stale: served '2026-07-27' expected '2026-07-28'")


def test_provider_surfaces_tool_error_not_quiet_empty():
    # a raising tool (stale/missing intraday map) must surface as `error`, NOT be
    # narrated and NOT collapse into the benign `reason` degrade.
    out = build_playbook_result([_RaisingTool({"n": 0})], llm=_CapturingLLM())
    assert out["available"] is False
    assert "error" in out and "stale" in out["error"]
    assert "narrative" not in out          # never narrated around a stale plan
    assert "reason" not in out             # not the benign "nothing yet" path


def test_cache_never_freezes_an_error():
    # the no-TTL cache must re-ask on every call while the tool is failing — a
    # frozen error would poison the whole session until a manual refresh.
    calls = {"n": 0}
    provider = cached_playbook_provider([_RaisingTool(calls)], llm=None)
    assert provider(None)["error"]
    assert provider(None)["error"]         # NOT served from cache
    assert calls["n"] == 2                 # re-fetched both times
