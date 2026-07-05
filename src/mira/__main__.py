"""``python -m mira`` entrypoint (e03-f07).

Builds the agent service composition via :func:`mira.app.build_app` and serves
the warm service WSGI app over the stdlib :mod:`wsgiref` server for the local
profile. ``--check`` boots the composition and exits 0 without binding a socket
(a network-free boot smoke); the default action serves until interrupted.
"""

from __future__ import annotations

import argparse
import os
import sys
from wsgiref.simple_server import make_server

from mira.app import DEFAULT_PROFILE, build_app
from mira.config.profiles import PROFILE_ENV


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

    app = build_app(args.profile)

    if args.check:
        print(f"mira: composed app on profile {app.profile.name!r}", file=sys.stderr)
        return 0

    app.service.register_sigterm_handler()
    with make_server(args.host, args.port, app.wsgi_app) as httpd:
        print(f"mira: serving on {args.host}:{args.port} (profile {app.profile.name!r})", file=sys.stderr)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            app.service.begin_shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
