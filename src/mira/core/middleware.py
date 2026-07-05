"""Composable per-request middleware pipeline (ADR-009).

Fixed stage order on the response path:
auth → correlation → entitlement → guardrail_in → [handler] → guardrail_out → telemetry
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

NextFn = Callable[[], Awaitable[Any]]


class AuthError(Exception):
    """Raised when auth middleware rejects a request."""


@dataclass
class RequestContext:
    """Per-request state shared across middleware stages."""

    attributes: dict[str, Any] = field(default_factory=dict)


class Middleware(Protocol):
    async def __call__(self, ctx: RequestContext, call_next: NextFn) -> Any: ...


class NoOpMiddleware:
    """Default no-op stage — passes through to the next stage."""

    async def __call__(self, ctx: RequestContext, call_next: NextFn) -> Any:
        return await call_next()


class AuthMiddleware:
    """Auth runs first; rejects before any downstream stage executes."""

    def __init__(self, *, allow: Callable[[RequestContext], bool] | None = None) -> None:
        self._allow = allow or (lambda _ctx: True)

    async def __call__(self, ctx: RequestContext, call_next: NextFn) -> Any:
        if not self._allow(ctx):
            raise AuthError("authentication failed")
        return await call_next()


class GuardrailOutMiddleware:
    """Wraps every exit — success, error, and streamed chunks — with no bypass."""

    async def __call__(self, ctx: RequestContext, call_next: NextFn) -> Any:
        try:
            result = await call_next()
        except Exception as exc:
            await self._on_exit(ctx, exc)
            raise
        return await self._wrap_result(ctx, result)

    async def _wrap_result(self, ctx: RequestContext, result: Any) -> Any:
        if hasattr(result, "__aiter__"):
            return self._wrap_stream(ctx, result)
        await self._on_exit(ctx, result)
        return result

    async def _wrap_stream(self, ctx: RequestContext, stream: AsyncIterator[Any]) -> AsyncIterator[Any]:
        # ADR-009: guardrail-out must run on the streaming error path too. If the
        # underlying iterator raises mid-stream, record the exception via _on_exit
        # before re-raising so no exit bypasses the guardrail hook.
        try:
            async for chunk in stream:
                await self._on_exit(ctx, chunk)
                yield chunk
        except Exception as exc:
            await self._on_exit(ctx, exc)
            raise

    async def _on_exit(self, ctx: RequestContext, payload: Any) -> None:
        hooks = ctx.attributes.setdefault("guardrail_out_exits", [])
        hooks.append(payload)


# Forward ADR-009 response-path order (auth first). Single source of truth;
# Pipeline.STAGE_ORDER aliases it.
STAGE_ORDER: tuple[str, ...] = (
    "auth",
    "correlation",
    "entitlement",
    "guardrail_in",
    "guardrail_out",
    "telemetry",
)

# Innermost-first onion-bind order. This is NOT a plain reverse of STAGE_ORDER:
# guardrail_out is bound innermost (wraps closest to the handler) so it observes
# every chunk/error before telemetry, while telemetry stays an outer wrap. The
# test_compose_order_covers_all_stages invariant guards against accidental drift
# (same stage set, exactly once each) without forcing an incorrect derivation (L1).
_COMPOSE_ORDER: tuple[str, ...] = (
    "guardrail_out",
    "telemetry",
    "guardrail_in",
    "entitlement",
    "correlation",
    "auth",
)

_STAGE_DEFAULTS: dict[str, Middleware] = {
    "auth": AuthMiddleware(),
    "correlation": NoOpMiddleware(),
    "entitlement": NoOpMiddleware(),
    "guardrail_in": NoOpMiddleware(),
    "guardrail_out": GuardrailOutMiddleware(),
    "telemetry": NoOpMiddleware(),
}


def _bind(middleware: Middleware, inner: Callable[[RequestContext], Awaitable[Any]]) -> Callable[
    [RequestContext], Awaitable[Any]
]:
    async def bound(ctx: RequestContext) -> Any:
        async def next_fn() -> Any:
            return await inner(ctx)

        return await middleware(ctx, next_fn)

    return bound


class Pipeline:
    """Runs middleware stages in the fixed ADR-009 order around a handler."""

    STAGE_ORDER: tuple[str, ...] = STAGE_ORDER

    def __init__(self, middlewares: dict[str, Middleware] | None = None) -> None:
        merged = dict(_STAGE_DEFAULTS)
        if middlewares:
            merged.update(middlewares)
        self._middlewares = merged

    async def run(
        self,
        ctx: RequestContext,
        handler: Callable[[RequestContext], Awaitable[Any]],
    ) -> Any:
        async def call_handler(ctx: RequestContext) -> Any:
            return await handler(ctx)

        chain: Callable[[RequestContext], Awaitable[Any]] = call_handler
        for name in _COMPOSE_ORDER:
            chain = _bind(self._middlewares[name], chain)
        return await chain(ctx)
