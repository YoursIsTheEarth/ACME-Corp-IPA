"""`python -m acme.llm`: print the LLM key status (used by run.sh and `make dev`).

Exit code 0 when every needed key is set, 1 when one is missing, 2 for an invalid provider.
"""

import sys

from acme.llm import ProviderConfigError, active_models, key_status, missing_key_message


def main() -> int:
    try:
        status = key_status()
    except ProviderConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not status.configured:
        print(f"WARNING: {missing_key_message(status.missing_key, status.provider)}")
        return 1
    model = active_models()["approval"]["model"]
    print(f"LLM: {status.provider} ({model}); API key configured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
