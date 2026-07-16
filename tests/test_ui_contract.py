"""The A2UI output contract — one canonical structured-output shape emitted by
the analyst specialists and rendered generically by the Vantage SPA."""
from mira.orchestration.ui_contract import (
    A2UI_OUTPUT_CONTRACT,
    SECTION_KINDS,
    with_contract,
)
from mira.orchestration.specialists.trade_analyst import TRADE_ANALYST_CARD
from mira.orchestration.specialists.journal_analyst import JOURNAL_ANALYST_CARD


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
    # the journal analyst still leads with SWOT; the trade analyst does not force it
    assert "swot" in JOURNAL_ANALYST_CARD.synthesis_hint.lower()


def test_contract_forbids_invention_and_allows_prose_fallback():
    assert "never invent" in A2UI_OUTPUT_CONTRACT.lower()
    assert "plain prose" in A2UI_OUTPUT_CONTRACT.lower()
