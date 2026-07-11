"""``python -m mira`` entrypoint (e03-f07).

Builds the agent service composition via :func:`mira.app.build_app` and serves
the warm service WSGI app. The default server is waitress (a real threaded WSGI
server) — the stdlib wsgiref dev server is single-threaded and mishandles
streamed (SSE) responses behind a Docker Desktop port-forward, silently
returning empty /turn results. wsgiref remains a fallback only when waitress is
unavailable. ``--check`` boots the composition and exits 0 without binding a
socket (a network-free boot smoke); the default action serves until interrupted.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from mira.app import DEFAULT_PROFILE, build_app
from mira.config.profiles import PROFILE_ENV


def _default_registry() -> Any | None:
    """Best-effort demo agent-card registry for supervisor-first /turn routing.

    Uses the demo fixture corpus **only when the repo fixtures exist relative to
    the current working directory** (a source checkout); an installed package
    or a different cwd gets no registry, and /turn serves the plain runtime
    turn instead — the ADR-006 Phase V1 default-off behavior.
    """
    handbook = Path("tests/fixtures/handbook.md")
    ledger = Path("tests/fixtures/ledger.csv")
    if not (handbook.is_file() and ledger.is_file()):
        return None
    from mira.orchestration.specialists.demo import build_demo_registry

    return build_demo_registry(str(handbook), str(ledger))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mira",
        description="Runnable Mira agent service (warm service + runtime).",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help=f"deployment profile name (default: ${PROFILE_ENV} or '{DEFAULT_PROFILE}')",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=8080, help="bind port")
    parser.add_argument(
        "--check",
        action="store_true",
        help="boot the composition and exit (network-free smoke); does not serve",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # Local-by-default: without an explicit PLATFORM the local in-memory bundle is
    # used so the boot smoke never imports a cloud/orchestration vendor SDK.
    os.environ.setdefault("PLATFORM", "local")
    os.environ.setdefault(PROFILE_ENV, DEFAULT_PROFILE)

    app = build_app(args.profile, registry=_default_registry())

    if args.check:
        print(f"mira: composed app on profile {app.profile.name!r}", file=sys.stderr)
        return 0

    app.service.register_sigterm_handler()
    _serve(app.wsgi_app, host=args.host, port=args.port, profile=app.profile.name,
           on_shutdown=app.service.begin_shutdown)
    return 0


def _serve(wsgi_app: Any, *, host: str, port: int, profile: str,
           on_shutdown) -> None:
    """Serve the WSGI app — waitress (threaded, production) preferred, wsgiref
    (single-threaded, dev-only) as a fallback when waitress is not installed."""
    try:
        from waitress import serve as _waitress_serve
    except ImportError:
        _waitress_serve = None

    if _waitress_serve is not None:
        print(f"mira: serving on {host}:{port} (profile {profile!r}, waitress)", file=sys.stderr)
        try:
            # threads: a handful is plenty for a single-user advisor; SSE turns
            # can be long-running, so allow a few concurrent so health probes and
            # the SPA's parallel fetches never head-of-line block a streamed turn.
            _waitress_serve(wsgi_app, host=host, port=port, threads=8)
        except KeyboardInterrupt:
            on_shutdown()
        return

    from wsgiref.simple_server import make_server
    with make_server(host, port, wsgi_app) as httpd:
        print(f"mira: serving on {host}:{port} (profile {profile!r}, wsgiref dev)", file=sys.stderr)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            on_shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
