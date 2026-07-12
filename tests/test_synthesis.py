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
        {"domain": "growth", "answer": {
            "facet": "growth",
            "growth": {"growth": {"revenue_yoy": 0.33, "fcf_margin": 0.32,
                                  "rule_of_40": 65.0,
                                  "rule_of_40_basis": "yoy_growth_plus_fcf_margin"}},
        }, "error": None},
        {"domain": "expectations", "answer": {
            "facet": "expectations",
            "expectations": {
                "implied": {"fcf_growth_10y": 0.42, "clamped": None, "status": "ok"},
                "assumptions": {"discount_rate": 0.095, "terminal_growth": 0.025,
                                "horizon_years": 10},
            },
        }, "error": None},
        {"domain": "news", "answer": {
            "facet": "news",
            "news": {"news": {"items": [{"title": "PLTR surges"}],
                              "sentiment": {"band": "positive", "estimated": True}}},
            "earnings": {"earnings": {"next_date": "2025-07-20", "days_until": 5,
                                      "future_date_known": True}},
        }, "error": None},
        {"domain": "thesis", "answer": {
            "facet": "thesis",
            "plan": {"has_plan": True,
                     "plan": {"thesis": "AIP land-and-expand", "target": 180.0,
                              "stop": 95.0, "updated_at": "2025-06-20T10:00:00"}},
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


def test_synthesis_requests_light_tier_via_chat():
    # goal(analyze-cost) H4: light tier measured -39.6% median tokens with
    # quality holding on the conflict case; the deep tier is one constant away.
    llm = _ChatCapturingLLM()
    out = synthesize_analysis(llm, "PLTR", _results())
    assert out == "SYNTH: multi-facet prose here."
    assert llm.tiers == ["light"]
    # system/user separation is preserved on the chat path
    roles = [m["role"] for m in llm.messages[0]]
    assert roles == ["system", "user"]
    assert "HOLD_AND_SELL_CALL" in llm.messages[0][1]["content"]


# ------------------------------------------------------------ domain-generic prompt

def test_system_prompt_is_domain_generic():
    import re

    llm = _ChatCapturingLLM()
    synthesize_analysis(llm, "PLTR", _results())
    system = llm.messages[0][0]["content"]
    # the core contract never names concrete domains — they travel on cards
    # (word-boundary match: "thesis" must not trip on "synthesis")
    for domain_word in ("technical", "fundamental", "thesis", "earnings", "portfolio"):
        assert not re.search(rf"\b{domain_word}\b", system, re.I), domain_word


def test_card_hints_reach_prompt_only_for_present_domains():
    llm = _ChatCapturingLLM()
    hints = {
        "news": "EARNINGS GATE: a report within 7 days gates act-now advice.",
        "thesis": "Weigh close/sell calls against the stored plan.",
        "absent-domain": "must never appear",
    }
    synthesize_analysis(llm, "PLTR", _results(), hints=hints)
    system = llm.messages[0][0]["content"]
    assert "DOMAIN GUIDANCE" in system
    assert "EARNINGS GATE" in system
    assert "Weigh close/sell calls" in system
    assert "must never appear" not in system


def test_no_hints_means_no_guidance_block():
    llm = _ChatCapturingLLM()
    synthesize_analysis(llm, "PLTR", _results(), hints={})
    assert "DOMAIN GUIDANCE" not in llm.messages[0][0]["content"]


def test_facet_cards_carry_their_synthesis_rules():
    # The rules that used to live in the prompt now travel on the cards.
    from mira.orchestration.specialists.facets import NEWS_CARD, THESIS_CARD

    assert "days_until" in NEWS_CARD.synthesis_hint
    assert "BROKEN or INTACT" in THESIS_CARD.synthesis_hint


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
    # readable, grounded, and multi-domain — not raw JSON
    assert "HOLD_AND_SELL_CALL" in out
    assert "P/E 210.5" in out
    assert "sentiment lean positive" in out
    assert "earnings 2025-07-20 in 5d" in out
    assert "revenue YoY 33%" in out and "Rule of 40 65" in out
    assert "market implies ~42% FCF growth" in out
    assert "target 180.0 / stop 95.0" in out


def test_fallback_negative_fcf_and_no_plan_phrasings():
    results = [
        {"domain": "expectations", "answer": {
            "facet": "expectations",
            "expectations": {"implied": {"fcf_growth_10y": None, "clamped": None,
                                         "status": "negative_fcf"}},
        }, "error": None},
        {"domain": "thesis", "answer": {
            "facet": "thesis",
            "plan": {"has_plan": False, "plan": None, "journal": []},
        }, "error": None},
    ]
    out = synthesize_analysis(None, "PLTR", results)
    assert "implied growth undefined: negative FCF" in out
    assert "no thesis on file" in out


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
    assert "No analysis domains" in synthesize_analysis(_CapturingLLM(), "PLTR", [])


def test_facet_error_kept_visible_in_fallback():
    results = [{"domain": "news", "answer": {}, "error": "specialist blew up"}]
    out = synthesize_analysis(None, "PLTR", results)
    assert "news: error — specialist blew up" in out
