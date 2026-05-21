#!/usr/bin/env python3
"""
Legacy-compatible wrapper for agent system version detection.

This script is kept as a compatibility alias and delegates to the canonical
manifest-first detector in scripts/detect_version.py.
"""

from detect_version import AgentSystemDetector as _AgentSystemDetector, main


AgentSystemDetector = _AgentSystemDetector


if __name__ == "__main__":
    raise SystemExit(main())
