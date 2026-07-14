"""Development-only utility to reset the usage database. Not invoked automatically."""

from __future__ import annotations

import sys
from pathlib import Path

from usage.database import get_db_path, init_db


def main() -> int:
    db_path = get_db_path()
    if db_path == "/app/data/usage/tokenwise.db" and "--force" not in sys.argv:
        print("Refusing to reset production path without --force flag.")
        print("Usage: python -m usage.reset_db --force")
        return 1

    path = Path(db_path)
    if path.exists():
        path.unlink()
    init_db(db_path)
    print(f"Reset usage database at {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
