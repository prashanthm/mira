"""One-step interactive chatbot: agent ⇄ MCP tools ⇄ LLM (entry point ``mira-chat``).

Just run ``mira-chat``. With Ollama running and an MCP server on the default port, it
auto-configures and starts — no env vars required. Type a prompt; the model calls tools
discovered from the MCP server, the harness executes them, and loops until it answers.

Zero-config defaults (each overridable by flag or env):
  model : first tool-capable model on a local Ollama (http://localhost:11434/v1)
  mcp   : http://localhost:8000/mcp
Override: ``mira-chat --mcp URL --model NAME --token $JWT`` (``mira-chat --help`` for all).

This is a thin app entrypoint (like ``__main__``); the langchain-touching work lives in
``orchestration`` (``aload_mcp_tools`` / ``to_openai_specs``), so this module stays
framework-free per ADR-007.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.request

from mira.connectors.mcp_registry import McpServerSpec
from mira.orchestration.mcp_tools import aload_mcp_tools, to_openai_specs
from mira.providers.openai_compatible import OpenAICompatibleLLMProvider

DEFAULT_LLM_BASE_URL = "http://localhost:11434/v1"  # local Ollama
DEFAULT_MCP_URL = "http://localhost:8000/mcp"
# Ollama families known to support tool calling, best-first — used to auto-pick a model.
_TOOL_MODEL_HINTS = ("qwen2.5", "qwen3", "llama3.1", "llama3.2", "mistral", "command-r")
MAX_TOOL_ROUNDS = 6
SYSTEM_PROMPT = (
    "You are a data assistant. You have tools discovered from the connected MCP tool "
    "servers (search, record retrieval, documents, files). When the user asks for "
    "data, CALL the appropriate tool rather than describing it. After a tool returns, "
    "summarize the result for the user."
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mira-chat",
        description="One-step chatbot: LLM + MCP tools. Run with no args for local defaults.",
    )
    p.add_argument(
        "--mcp",
        default=os.environ.get("MCP_BASE_URL", DEFAULT_MCP_URL),
        help=f"MCP server URL (default: $MCP_BASE_URL or {DEFAULT_MCP_URL})",
    )
    p.add_argument(
        "--llm-url",
        default=os.environ.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        help=f"OpenAI-compatible LLM endpoint (default: $LLM_BASE_URL or {DEFAULT_LLM_BASE_URL})",
    )
    p.add_argument(
        "--model",
        default=os.environ.get("LLM_MODEL"),
        help="model id (default: $LLM_MODEL, else auto-detect a tool-capable Ollama model)",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("MCP_TOKEN"),
        help="bearer token for the MCP server (default: $MCP_TOKEN)",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("LLM_API_KEY", "not-needed"),
        help="LLM API key (default: $LLM_API_KEY; ignored by Ollama)",
    )
    return p.parse_args(argv)


def _root_cause(exc: BaseException) -> str:
    """Unwrap ExceptionGroup/TaskGroup nesting to the most informative leaf message.

    MCP discovery failures (e.g. a 401) arrive wrapped in a TaskGroup ExceptionGroup; the
    bare group message hides the cause, so descend to the innermost exception.
    """
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None:
        exceptions = getattr(current, "exceptions", None)
        if exceptions:
            current = exceptions[0]
            continue
        seen.append(current)
        current = current.__cause__ or current.__context__
    leaf = seen[-1] if seen else exc
    return f"{type(leaf).__name__}: {leaf}"


def _autodetect_model(llm_url: str, api_key: str) -> str | None:
    """Pick a tool-capable model from a local ``/v1/models`` list (Ollama-compatible)."""
    try:
        url = llm_url.rstrip("/") + "/models"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=4) as resp:  # noqa: S310 - local dev URL
            data = json.load(resp)
    except Exception:  # noqa: BLE001 - endpoint may be down; caller handles the None
        return None
    ids = [m.get("id", "") for m in data.get("data", [])]
    # Prefer text tool-callers; vision ("vl") variants are weaker at tool calling, so skip
    # them in the hint pass and only fall back to one if nothing else matches.
    for hint in _TOOL_MODEL_HINTS:
        for mid in ids:
            if hint in mid and "vl" not in mid:
                return mid
    for hint in _TOOL_MODEL_HINTS:
        for mid in ids:
            if hint in mid:
                return mid
    # No known tool-caller installed — don't fall back to ids[0]; models like
    # llama3:latest lack tool support and fail at request time with a 400.
    return None


async def _build(args: argparse.Namespace) -> tuple[OpenAICompatibleLLMProvider, list, list[dict]]:
    """Resolve the LLM provider, discover MCP tools, and pre-convert their OpenAI specs."""
    model = args.model or _autodetect_model(args.llm_url, args.api_key)
    if not model:
        sys.exit(
            f"error: no tool-capable model at {args.llm_url}. "
            "llama3 (not 3.1+) does not support tools in Ollama. "
            "Run `ollama pull qwen2.5:7b` (or llama3.1) then "
            "`mira-chat --model qwen2.5:7b`."
        )
    provider = OpenAICompatibleLLMProvider(
        base_url=args.llm_url, api_key=args.api_key, model=model
    )

    # Single declared server; carry a bearer token via env if --token/$*_TOKEN is set.
    token_env = None
    if args.token:
        os.environ["MCP_TOKEN"] = args.token
        token_env = "MCP_TOKEN"
    registry = [McpServerSpec(name="mcp", url=args.mcp, auth_token_env=token_env)]

    print(f"model={model}  mcp={args.mcp}{'  (auth)' if args.token else ''}\nconnecting ...")
    try:
        tools = await aload_mcp_tools(registry)
    except Exception as exc:  # noqa: BLE001 — surface a real connect/auth failure clearly
        sys.exit(f"error: MCP discovery failed: {_root_cause(exc)}")
    print(f"discovered {len(tools)} tools — ready\n")

    return provider, tools, to_openai_specs(tools)


async def _run_tool(tools_by_name: dict, name: str, tool_args: dict) -> str:
    """Execute one discovered MCP tool and return its result as a string."""
    tool = tools_by_name.get(name)
    if tool is None:
        return f"[no such tool: {name}]"
    try:
        result = await tool.ainvoke(tool_args)
    except Exception as exc:  # noqa: BLE001 — surface tool errors back to the model
        return f"[tool error: {type(exc).__name__}: {exc}]"
    return result if isinstance(result, str) else json.dumps(result, default=str)


async def _answer(
    provider: OpenAICompatibleLLMProvider,
    tools_by_name: dict,
    specs: list[dict],
    messages: list[dict],
) -> str:
    """Run the tool-calling loop for one user turn; return the model's final text."""
    for _ in range(MAX_TOOL_ROUNDS):
        # provider.chat is sync; run it off the event loop so ainvoke stays responsive.
        result = await asyncio.to_thread(
            provider.chat, messages, tools=specs, tool_choice="auto"
        )
        if not result.tool_calls:
            messages.append({"role": "assistant", "content": result.text})
            return result.text

        # Record the assistant's tool-call turn, then execute each call.
        messages.append(
            {
                "role": "assistant",
                "content": result.text or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in result.tool_calls
                ],
            }
        )
        for call in result.tool_calls:
            try:
                call_args = json.loads(call.arguments) if call.arguments else {}
            except json.JSONDecodeError:
                call_args = {}
            print(f"  → calling {call.name}({call.arguments})")
            output = await _run_tool(tools_by_name, call.name, call_args)
            print(f"  ← {output[:200]}{'…' if len(output) > 200 else ''}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})

    return "[stopped: exceeded max tool rounds]"


async def _main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    provider, tools, specs = await _build(args)
    tools_by_name = {t.name: t for t in tools}
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("ask about data from your connected MCP tool servers.  /tools, /quit\n")
    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user:
            continue
        if user in ("/quit", "/exit"):
            return
        if user == "/tools":
            for t in tools:
                print(f"  - {t.name}: {(t.description or '').splitlines()[0][:80]}")
            continue

        messages.append({"role": "user", "content": user})
        answer = await _answer(provider, tools_by_name, specs, messages)
        print(f"bot> {answer}\n")


def cli() -> None:
    """Console-script entry point (``mira-chat``)."""
    asyncio.run(_main())


if __name__ == "__main__":
    cli()
