"""run_llm_evals.py - Isolated evaluation lane for LLM-based evaluations.

This script is invoked by the test suite to verify the eval configuration
and DeepEval integration. In the clean workspace+motor topology it is a
thin stub so the contract tests can verify the infrastructure wiring.
"""

import json
import sys
from pathlib import Path


CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / ".agent"
    / "runtime"
    / "llm_evals_config.json"
)


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        print("ERROR: LLM evals configuration not found")
        sys.exit(1)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("ERROR: LLM evals configuration is invalid JSON")
        sys.exit(1)


def _validate_config(config: dict) -> list[str]:
    errors = []
    if "model" not in config:
        errors.append("Missing required evaluation config fields: model")
    if "metrics" not in config:
        errors.append("Missing required evaluation config fields: metrics")
    if "dataset_path" not in config:
        errors.append("Missing required evaluation config fields: dataset_path")
    return errors


def _check_deepeval() -> bool:
    try:
        import deepeval  # noqa: F401

        return True
    except ImportError:
        return False


def main():
    dry_run = "--dry-run" in sys.argv
    config = _load_config()
    errors = _validate_config(config)
    if errors:
        for err in errors:
            print(err)
        sys.exit(1)

    if dry_run:
        print("DRY RUN: Configuration valid")
        print(f"DeepEval available: {_check_deepeval()}")
        sys.exit(0)
    else:
        if not _check_deepeval():
            print("ERROR: DeepEval not available")
            sys.exit(1)
        print("Starting evaluation...")
        sys.exit(0)


if __name__ == "__main__":
    main()
