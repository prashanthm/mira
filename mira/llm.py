"""Local LLM access — Ollama only (no cloud).

Builds a LangChain chat model bound to a local Ollama server. If Ollama isn't
running, raises OllamaUnavailable so callers (e.g. a nightly job) can no-op cleanly
rather than crash or fall back to a cloud provider.
"""
from __future__ import annotations

import logging

log = logging.getLogger("mira.llm")

_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaUnavailable(RuntimeError):
    """Raised when the local Ollama server can't be reached."""


def ollama_up(base_url: str = _DEFAULT_BASE_URL, timeout: float = 3.0) -> bool:
    import requests
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def available_models(base_url: str = _DEFAULT_BASE_URL) -> list[str]:
    import requests
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=3.0)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def build_model(model: str = "qwen2.5:7b", base_url: str = _DEFAULT_BASE_URL,
                temperature: float = 0.2, num_ctx: int = 8192):
    """Return a ChatOllama model bound to the local server.

    Raises OllamaUnavailable if the server isn't reachable or the model isn't pulled.
    """
    if not ollama_up(base_url):
        raise OllamaUnavailable(
            f"Ollama not reachable at {base_url}. Start it (`ollama serve`) and pull a model."
        )
    pulled = available_models(base_url)
    if pulled and model not in pulled and model.split(":")[0] not in {m.split(":")[0] for m in pulled}:
        log.warning(f"model '{model}' not in pulled models {pulled}; the call may fail.")

    from langchain_ollama import ChatOllama
    return ChatOllama(model=model, base_url=base_url, temperature=temperature, num_ctx=num_ctx)
