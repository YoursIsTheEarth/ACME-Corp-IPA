"""Test-only CLI entry point: `python backend/tests/fake_cli.py <main.py arguments>` with the fake model.

For subprocess tests that need a fresh process. Lives under tests/ only; no setting or flag selects it.
Set a dummy key (e.g. `XAI_API_KEY=test-key`) so the key check passes.
"""

import sys

import pytest

import fake_llm
from acme.cli import main

if __name__ == "__main__":
    fake_llm.install(pytest.MonkeyPatch())
    sys.exit(main())
