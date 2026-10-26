"""Repo-root entry point: `python main.py --invoice_path=...`."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

try:
    from acme.cli import main
except ModuleNotFoundError as exc:
    if (exc.name or "").startswith("acme"):
        raise
    # Not running in the backend venv: re-run there if setup has been done, else say how to do it
    venv = ROOT / "backend" / ".venv"
    for venv_python in (venv / "bin" / "python", venv / "Scripts" / "python.exe"):
        if venv_python.exists() and Path(sys.prefix).resolve() != venv.resolve():
            os.execv(str(venv_python), [str(venv_python), *sys.argv])
    sys.exit(
        f"Missing Python package '{exc.name}': the backend is not installed.\n"
        "Run setup once from the repo root, then retry:\n"
        "  make backend-setup\n"
        "or, without make:\n"
        "  python -m venv backend/.venv\n"
        "  backend/.venv/bin/python -m pip install -e \"backend[dev]\"   # Windows: backend\\.venv\\Scripts\\python.exe\n"
        "See backend/README.md for details."
    )

if __name__ == "__main__":
    raise SystemExit(main())
