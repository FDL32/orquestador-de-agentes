#!/usr/bin/env python3
"""Shared function for validating the mcp: threadId prefix.

Before: the module file path is available via __file__.
During: validates that a threadId string starts with the mcp: prefix constant.
After: returns True if the prefix matches, False otherwise.

Constants:
    MCP_PREFIX: the required prefix for supervisor threadIds.
"""

from __future__ import annotations


# The required prefix for supervisor threadIds.
# This is the ONLY file in scripts/ that carries the literal "mcp:" as an
# enforced prefix; the writer, the guard, and the helper import and call
# this function instead of duplicating the startswith call.
MCP_PREFIX: str = "mcp:"


def has_mcp_prefix(thread_id: str) -> bool:
    """Check if `thread_id` starts with the mcp: prefix.

    Before: `thread_id` is a string (may be empty).
    During: compares against MCP_PREFIX using startswith.
    After: returns True if the prefix matches, False otherwise (including
        when the string is empty or the prefix is absent).
    """
    return thread_id.startswith(MCP_PREFIX)
