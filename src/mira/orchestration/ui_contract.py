"""The A2UI output contract — one canonical structured-output schema that Mira's
analyst/synthesis paths emit and the Vantage SPA (``src/mira-render.jsx``)
renders generically.

Standardizing on ONE shape (rather than a bespoke JSON per specialist) is what
lets a generic renderer — and, ahead, an agent-to-UI (A2UI) layer — turn any
Mira output into rich UI without per-section code. Prose stays the graceful
fallback: the renderer shows clean text whenever the model doesn't return valid
JSON, so emitting the contract is a best-effort upgrade, never a hard dependency.

The schema (mirror of the SPA renderer's ``parseMira``/``MiraRender``):

    {
      "headline": "<one-line takeaway>",
      "sections": [
        {"kind": "prose",     "title?": "...", "text": "paragraph(s)"},
        {"kind": "list",      "title": "...", "items": [{"point": "...", "cites?": ["..."]}]},
        {"kind": "keyvals",   "title": "...", "rows": [{"k": "...", "v": "...", "tone?": "good|bad|warn"}]},
        {"kind": "callout",   "title": "...", "text": "...", "tone?": "good|bad|warn"},
        {"kind": "donext",    "title?": "Do next", "items": [{"title": "...", "detail?": "..."}]},
        {"kind": "swot",      "swot": {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []}},
        {"kind": "scorecard", "rows": [{"label": "...", "score": 0-100}]}
      ]
    }

SWOT is just one section kind — nothing is forced into a SWOT. A specialist picks
the section kinds that fit its output.
"""
from __future__ import annotations

#: The section kinds the SPA renderer understands (keep in sync with
#: ``src/mira-render.jsx`` ``isRenderableSection``).
SECTION_KINDS = ("prose", "list", "keyvals", "callout", "donext", "swot", "scorecard")

#: The shared instruction fragment appended to a specialist's synthesis_hint when
#: it should emit the A2UI contract. Compact on purpose — the per-specialist hint
#: still says WHAT to analyze; this says HOW to shape the output.
A2UI_OUTPUT_CONTRACT = (
    "OUTPUT FORMAT — return ONE JSON object and nothing else (no prose outside "
    "it, no markdown fences):\n"
    '{"headline":"<one-line takeaway>","sections":[ ... ]}\n'
    "Each section is one of these kinds (use the ones that fit; omit the rest):\n"
    '  {"kind":"prose","title?":"..","text":".."}\n'
    '  {"kind":"list","title":"..","items":[{"point":"..","cites?":["trade label"]}]}\n'
    '  {"kind":"keyvals","title":"..","rows":[{"k":"..","v":"..","tone?":"good|bad|warn"}]}\n'
    '  {"kind":"callout","title":"..","text":"..","tone?":"good|bad|warn"}\n'
    '  {"kind":"donext","items":[{"title":"..","detail?":".."}]}\n'
    '  {"kind":"swot","swot":{"strengths":[{"point":"..","cites?":[..]}],"weaknesses":[],"opportunities":[],"threats":[]}}\n'
    '  {"kind":"scorecard","rows":[{"label":"..","score":0-100}]}\n'
    "Cite ONLY real figures/labels from the grounded results — never invent one. "
    "If you cannot produce valid JSON, write the answer as plain prose instead "
    "(it will still render)."
)


def with_contract(hint: str) -> str:
    """Append the A2UI output contract to a specialist's synthesis hint."""
    hint = (hint or "").rstrip()
    return f"{hint}\n\n{A2UI_OUTPUT_CONTRACT}"
