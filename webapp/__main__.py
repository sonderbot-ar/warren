"""Start the app on this machine: `python -m webapp [--port 8000] [--db PATH]`.

It listens on 127.0.0.1 only (nothing is reachable from another machine), checks the database's
schema first and refuses to start if it is out of date (the app never applies migrations).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from shared_kernel.config import DB_PATH
from webapp.database import SchemaMismatch, require_current_schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m webapp", description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=DB_PATH, help="the Warren database")
    args = parser.parse_args(argv)

    try:
        require_current_schema(args.db)
    except SchemaMismatch as exc:
        print(exc, file=sys.stderr)
        return 1

    import uvicorn

    from webapp.app import create_app

    print(f"Warren: http://127.0.0.1:{args.port}/")
    uvicorn.run(create_app(db_path=args.db), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
