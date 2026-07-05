"""Layered memory: session, long-term, and summarization (ADR-017)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# IStateStore is owned by e01-f02-t01 (mira.providers.protocols). Until #10 lands
# we fall back to a structurally-identical local Protocol; the import takes
# precedence the moment the canonical definition exists, and
# test_local_state_store_matches_canonical_protocol guards against drift.
try:
    from mira.providers.protocols import IStateStore
except ImportError:
    @runtime_checkable
    class IStateStore(Protocol):
        """Session/durable KV seam (ADR-002). Canonical definition in mira.providers.protocols."""

        def get(self, key: str) -> str | None: ...

        def set(self, key: str, value: str) -> None: ...


class SessionMemory:
    """Session tier: durable conversation state via IStateStore (checkpointer seam)."""

    def __init__(self, store: IStateStore, *, prefix: str = "session:") -> None:
        self._store = store
        self._prefix = prefix

    def _key(self, thread_id: str) -> str:
        return f"{self._prefix}{thread_id}"

    def get(self, thread_id: str) -> str | None:
        return self._store.get(self._key(thread_id))

    def save(self, thread_id: str, state: str) -> None:
        self._store.set(self._key(thread_id), state)


@runtime_checkable
class LongTermMemory(Protocol):
    def write(self, key: str, content: str, *, metadata: dict[str, Any] | None = None) -> None: ...

    def retrieve(self, query: str, *, limit: int = 5) -> list[str]: ...


class InMemoryLongTermMemory:
    """In-memory long-term store with key/substring similarity retrieval."""

    def __init__(self) -> None:
        self._entries: dict[str, str] = {}

    def write(self, key: str, content: str, *, metadata: dict[str, Any] | None = None) -> None:
        del metadata  # reserved for future embedding/tenant metadata
        self._entries[key] = content

    def retrieve(self, query: str, *, limit: int = 5) -> list[str]:
        needle = query.lower()
        matches = [
            content
            for key, content in self._entries.items()
            if needle in key.lower() or needle in content.lower()
        ]
        return matches[:limit]


def _word_count(text: str) -> int:
    return len(text.split())


def summarize(history: list[str], max_tokens: int) -> list[str]:
    """Compress history when total word count exceeds the budget.

    ``max_tokens`` is a deliberate Phase-1 **word-count** proxy for a token
    budget (see ``_word_count``); it is not a real tokenizer count. A summary
    marker is always retained when earlier turns are collapsed, so the caller
    can always tell compression occurred (ADR-017).
    """
    if max_tokens <= 0 or not history:
        return []

    total = sum(_word_count(item) for item in history)
    if total <= max_tokens:
        return list(history)

    latest = history[-1]
    latest_words = _word_count(latest)
    if latest_words > max_tokens:
        return [" ".join(latest.split()[:max_tokens])]

    omitted = len(history) - 1
    summary_line = f"[Summarized {omitted} earlier message(s)]"
    remaining = max_tokens - latest_words

    if _word_count(summary_line) <= remaining:
        return [summary_line, latest]

    # Tight budget: never silently drop the marker. Fall back to a minimal
    # ellipsis so the caller still sees that earlier turns were collapsed.
    return ["[…]", latest]
