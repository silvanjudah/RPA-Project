"""Start the local web interface for the job vacancy bot.

    python3 web_bot.py
    python3 web_bot.py --port 8080 --config config/config.json

The server binds to 127.0.0.1 by default and has no authentication: keep it on
your machine or a trusted network.
"""

from __future__ import annotations

import argparse

from rpa_jobs import __version__
from rpa_jobs.webapp import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web_bot.py",
        description="Local web RPA interface for the job vacancy bot.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="port (default: 5000)")
    parser.add_argument("--config", default=None, help="path to a JSON config file")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    app = create_app(args.config)
    print(f"RPA Job Vacancy Bot web console v{__version__}")
    print(f"Open http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
