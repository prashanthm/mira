"""The A2UI output contract — one canonical structured-output shape emitted by
the analyst specialists and rendered generically by the Vantage SPA."""
from mira.orchestration.ui_contract import (
    A2UI_OUTPUT_CONTRACT,
    SECTION_KINDS,
    with_contract,
)
from mira.orchestration.specialists.trade_analyst import TRADE_ANALYST_CARD
from mira.orchestration.specialists.journal_analyst import JOURNAL_ANALYST_CARD
from mira.orchestration.specialists.forecast_grader import FORECAST_GRADER_CARD


def test_contract_lists_every_section_kind():
    # the SPA renderer (src/mira-render.jsx isRenderableSection) understands these
    for kind in ("prose", "list", "keyvals", "callout", "donext", "swot", "scorecard"):
        assert kind in SECTION_KINDS
        assert f'"kind":"{kind}"' in A2UI_OUTPUT_CONTRACT


def test_with_contract_appends_and_preserves_hint():
    out = with_contract("Analyze the thing.")
    assert out.startswith("Analyze the thing.")
    assert "OUTPUT FORMAT" in out
    assert '"headline"' in out and '"sections"' in out


def test_analysts_emit_the_contract():
    # both analyst specialists must carry the shared contract so their output is
    # A2UI-renderable (prose fallback still handled by the SPA renderer)
    assert "OUTPUT FORMAT" in TRADE_ANALYST_CARD.synthesis_hint
    assert "OUTPUT FORMAT" in JOURNAL_ANALYST_CARD.synthesis_hint
    assert "OUTPUT FORMAT" in FORECAST_GRADER_CARD.synthesis_hint
    # the journal analyst still leads with SWOT; the trade analyst does not force it
    assert "swot" in JOURNAL_ANALYST_CARD.synthesis_hint.lower()
    # the forecast grader leads with a scorecard and forbids inventing scores
    hint = FORECAST_GRADER_CARD.synthesis_hint.lower()
    assert "scorecard" in hint
    assert "never compute" in hint or "never" in hint and "invent" in hint


def test_contract_forbids_invention_and_allows_prose_fallback():
    assert "never invent" in A2UI_OUTPUT_CONTRACT.lower()
    assert "plain prose" in A2UI_OUTPUT_CONTRACT.lower()


def test_both_model_synthesizers_carry_the_contract():
    """The A2UI contract lives in BOTH model synthesizer system prompts (solo
    /turn + equity fan-out) — so every chat/advisor/facet answer is A2UI-
    capable, not only the specialists that wrap per-card."""
    from mira.orchestration.supervisor import _TURN_SYSTEM_PROMPT
    from mira.orchestration.synthesis import _SYSTEM_PROMPT
    assert "OUTPUT FORMAT" in _TURN_SYSTEM_PROMPT
    assert "OUTPUT FORMAT" in _SYSTEM_PROMPT


def test_fanout_guidance_strips_the_duplicated_contract():
    """A card hint that carries the contract (trade_analyst) is de-duped in the
    fan-out guidance block — the schema is stated once (system prompt), not per
    present domain."""
    from mira.orchestration.synthesis import _guidance_block
    from mira.orchestration.ui_contract import with_contract
    results = [{"domain": "d", "answer": {"x": 1}}]
    hints = {"d": with_contract("Analyze the thing.")}
    block = _guidance_block(results, hints)
    assert "Analyze the thing." in block
    assert "OUTPUT FORMAT" not in block   # stripped — lives in the system prompt
