from __future__ import annotations

import argparse
import sys

import uvicorn

from .api.server import create_app
from .config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas", description="evidence-atlas API gateway")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the HTTP server")
    serve.add_argument("--config", default=None)
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    args = parser.parse_args(argv)

    if args.command == "serve":
        cfg = load_config(args.config)
        app = create_app(cfg)
        host = args.host or cfg.server.host
        port = args.port or cfg.server.port
        uvicorn.run(app, host=host, port=port)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
