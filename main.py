"""Repo-root entry point: `python main.py --invoice_path=...`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend" / "src"))

from acme.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
