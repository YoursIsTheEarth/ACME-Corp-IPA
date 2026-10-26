"""`python -m acme.db seed` creates the schema and seeds reference data."""

import argparse

from acme.db import connect
from acme.db.seed import seed
from acme.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m acme.db")
    parser.add_argument("command", choices=["seed"])
    parser.parse_args(argv)
    conn = connect()
    try:
        seed(conn)
    finally:
        conn.close()
    print(f"Seeded {get_settings().db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
