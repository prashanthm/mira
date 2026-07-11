"""LLM synthesis over analyze results: grounding passed, model routed, degrade-safe."""

from __future__ import annotations

from mira.orchestration.synthesis import synthesize_analysis


class _CapturingLLM:
    """Records the prompt it received; returns a fixed synthesized answer."""

    def __init__(self, reply="SYNTH: multi-facet prose here."):
        self.reply = reply
        self.prompts: list[str] = []
        self.models: list[str | None] = []

    def complete(self, prompt: str, *, model: str | None = None) -> str:
        self.prompts.append(prompt)
        self.models.append(model)
        return self.reply

    def embed(self, text):
        return [0.0]


def _results():
    return [
        {"domain": "technical", "answer": {
            "facet": "technical",
            "analysis": {"decisions": [{"symbol": "PLTR", "recommendation": "HOLD_AND_SELL_CALL",
                                        "rule": "rule1_strong_at_support"}]},
            "levels": {"levels": {"support": [{"price": 128.63}]}, "bars": [1, 2, 3]},
        }, "error": None},
        {"domain": "fundamental", "answer": {
            "facet": "fundamental",
            "fundamentals": {"fundamentals": {"pe": 210.5, "target_mean": 98.4}},
        }, "error": None},
        {"domain": "news", "answer": {
            "facet": "news",
            "news": {"news": {"items": [{"title": "PLTR surges"}],
                              "sentiment": {"band": "positive", "estimated": True}}},
        }, "error": None},
    ]


# ------------------------------------------------------------ LLM path

def test_synthesis_calls_llm_with_grounded_facets():
    llm = _CapturingLLM()
    out = synthesize_analysis(llm, "PLTR", _results(), question="what should I do?")
    assert out == "SYNTH: multi-facet prose here."
    prompt = llm.prompts[0]
    # the user's question + each facet's grounded fact reached the model
    assert "what should I do?" in prompt
    assert "HOLD_AND_SELL_CALL" in prompt
    assert "210.5" in prompt
    assert "positive" in prompt


class _ChatCapturingLLM:
    """Gateway-shaped fake: records the messages and tier ``chat`` received."""

    def __init__(self, reply="SYNTH: multi-facet prose here."):
        self.reply = reply
        self.messages: list[list[dict]] = []
        self.tiers: list[str | None] = []

    def chat(self, messages, *, model=None, tools=None, tool_choice="auto", tier=None):
        self.messages.append(messages)
        self.tiers.append(tier)

        class _Reply:
            text = self.reply
            tool_calls = ()

        return _Reply()

    def complete(self, prompt, *, model=None):
        raise AssertionError("chat-capable provider must be used via chat")

    def embed(self, text):
        return [0.0]


def test_synthesis_requests_deep_tier_via_chat():
    llm = _ChatCapturingLLM()
    out = synthesize_analysis(llm, "PLTR", _results())
    assert out == "SYNTH: multi-facet prose here."
    assert llm.tiers == ["deep"]
    # system/user separation is preserved on the chat path
    roles = [m["role"] for m in llm.messages[0]]
    assert roles == ["system", "user"]
    assert "HOLD_AND_SELL_CALL" in llm.messages[0][1]["content"]


def test_synthesis_trims_heavy_bar_arrays():
    llm = _CapturingLLM()
    synthesize_analysis(llm, "PLTR", _results())
    # raw bars are omitted from the prompt (kept bounded)
    assert "bars omitted" in llm.prompts[0]


def test_synthesis_folds_context_for_followups():
    llm = _CapturingLLM()
    synthesize_analysis(llm, "PLTR", _results(),
                        question="what do you mean?", context="Earlier: PLTR reads MONITOR.")
    assert "Earlier: PLTR reads MONITOR." in llm.prompts[0]


# ------------------------------------------------------------ degrade / fallback

def test_no_llm_falls_back_to_readable_digest():
    out = synthesize_analysis(None, "PLTR", _results())
    assert "deterministic" in out
    # readable, grounded, and multi-facet — not raw JSON
    assert "HOLD_AND_SELL_CALL" in out
    assert "P/E 210.5" in out
    assert "sentiment lean positive" in out


def test_llm_error_degrades_to_fallback():
    class _BoomLLM:
        def complete(self, prompt, *, model=None):
            raise RuntimeError("model down")

        def embed(self, text):
            return [0.0]

    out = synthesize_analysis(_BoomLLM(), "PLTR", _results())
    assert "deterministic" in out  # fell back, never blanked
    assert "PLTR" in out


def test_empty_results_message():
    assert "No analysis facets" in synthesize_analysis(_CapturingLLM(), "PLTR", [])


def test_facet_error_kept_visible_in_fallback():
    results = [{"domain": "news", "answer": {}, "error": "specialist blew up"}]
    out = synthesize_analysis(None, "PLTR", results)
    assert "news: error — specialist blew up" in out
