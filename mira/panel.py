"""The deepagents sub-agent research panel.

A main orchestrator (synthesizer) delegates to two specialist sub-agents:
  - options-analyst: reads recommendations + grades + scorecard
  - actions-analyst: reads the equity trade journal + decision log
then synthesizes a single advisory InsightReport.

Built on deepagents.create_deep_agent over a local LangChain chat model.
"""
from __future__ import annotations

from .schema import InsightReport

_ORCHESTRATOR_INSTRUCTIONS = """\
You are Mira, a careful trading-process analyst. You are given read-only tools to pull
performance data, and two specialist sub-agents. Your job is to evaluate what was
recommended and what was actually done, against how it was graded, and produce a concise,
evidence-grounded, ADVISORY report.

Rules:
- Ground every claim in the data (cite counts, grades, win-rates, P&L). Do not invent numbers.
- These are decision-support insights, NOT instructions to trade. Never tell the user to
  place a trade. Suggestions are advisory only.
- Be honest about sample size: with few graded/final outcomes, say confidence is low.
- Long options are negative-EV on average; don't claim a directional edge that isn't shown.

Process:
1. Use the `options-analyst` sub-agent to analyze the options recommendations, their A–D
   grades, and the scorecard (which structures/states are tracking well or poorly).
2. Use the `actions-analyst` sub-agent to analyze the agent's actual equity trades and
   decisions (entries/exits, win/loss, regime adherence).
3. Synthesize both into one report: a short summary, what worked, what didn't, advisory
   adjustments, a confidence level, and caveats.

Return ONLY a JSON object matching the InsightReport schema.
"""

# deepagents SubAgent spec uses: name, description, system_prompt (+ optional model, tools).
_OPTIONS_ANALYST = {
    "name": "options-analyst",
    "description": "Analyzes options recommendations, their A–D grades, and the scorecard.",
    "system_prompt": (
        "Analyze the options-intelligence data. Use read_resource on 'recommendations', "
        "'grades', and 'scorecard'. Identify which strategies/regime-states are grading well "
        "vs poorly, where grades diverge from the structure-quality score, and any notable "
        "A/D patterns. Cite the actual counts and grades. Be concise."
    ),
}

_ACTIONS_ANALYST = {
    "name": "actions-analyst",
    "description": "Analyzes the agent's actual equity trades and decision log.",
    "system_prompt": (
        "Analyze the equity agent's behavior. Use read_resource on 'equity_trades' and "
        "'equity_actions'. Summarize realized outcomes (win/loss, exit reasons), and whether "
        "actions followed the regime/bias. Cite real numbers. Be concise."
    ),
}


def build_insight_panel(model, tools: list, subagent_model_settings: dict | None = None):
    """Construct the deep agent with the two sub-agents. `model` is a LangChain chat model.

    subagent_model_settings (optional) may carry a {"model": <str|object>} to run the
    sub-agents on a different model; by default they inherit the main model.
    """
    from deepagents import create_deep_agent

    options_sub = dict(_OPTIONS_ANALYST)
    actions_sub = dict(_ACTIONS_ANALYST)
    if subagent_model_settings and subagent_model_settings.get("model"):
        options_sub["model"] = subagent_model_settings["model"]
        actions_sub["model"] = subagent_model_settings["model"]

    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=_ORCHESTRATOR_INSTRUCTIONS,
        subagents=[options_sub, actions_sub],
    )


def report_request() -> str:
    """The user message that drives the panel, including the schema to fill."""
    import json
    schema = json.dumps(InsightReport.model_json_schema()["properties"], indent=0)[:1500]
    return (
        "Evaluate the latest recommendations, grades, scorecard, and the agent's actions. "
        "Produce one InsightReport JSON object with keys: summary, what_worked, what_didnt, "
        "adjustments, confidence, caveats. "
        f"InsightReport fields: {schema}"
    )
