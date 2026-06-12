"""Review rubrics per deliverable_type for the Manager review prompt.

Extracted from bus/review_bridge.py (monolith decomposition). This module
owns the rubric TEXT — what the Manager must verify for each
deliverable_type (code / mixed / documentation / research / analysis),
including the anti-pattern checklist (AP-01..AP-07).

Pure functions: input is the dtype, ticket id and the pre-rendered
canonical anti-pattern inventory block; output is the rubric string.
To add or modify an anti-pattern in the rubric, edit this file only.
"""

from __future__ import annotations


SCAFFOLDING_PRECHECK = (
    "AP-07 Scaffolding misclassified as code precheck: if the majority of Files Likely Touched are "
    "structural non-Python artifacts (references/, .gitkeep, empty dirs, placeholders, "
    "config stubs) with no logic — even if one small support file is included — "
    "the correct deliverable_type is 'documentation', not 'code'. "
    "Flag 'code' classification for majority-scaffolding tickets as a planning error "
    "(SUGGESTIONS, not BLOCKER)."
)


def rubric_for_type(
    dtype: str, ticket_id: str, anti_pattern_inventory: str = ""
) -> str:
    """Return the review rubric for a deliverable_type.

    ``anti_pattern_inventory`` is the pre-rendered canonical inventory block
    (may be empty); it is embedded after the scaffolding precheck.
    """
    canonical_anti_patterns_block = (
        f"{anti_pattern_inventory}\n\n" if anti_pattern_inventory else ""
    )
    if dtype == "code":
        return (
            f"Review code ticket {ticket_id}. "
            f"Verify the implementation correctness, testing coverage, and style guides. "
            f"Check acceptance criteria and Files Likely Touched.\n\n"
            f"{SCAFFOLDING_PRECHECK}\n\n"
            f"{canonical_anti_patterns_block}"
            f"Test anti-patterns — flag as BLOCKERS if found:\n"
            f"- AP-01 Mock drift: each patch/mock must target the actual API the code calls "
            f"(e.g. patching pathlib.Path.open is inert if the code uses the built-in open()).\n"
            f"- AP-02 Floor assertion: each numeric threshold must exceed the base value that exists "
            f"without the tested feature (e.g. assert score >= 150 is trivially true if "
            f"the base recency score alone is ~20_000_000).\n\n"
            f"Implementation anti-patterns — flag as BLOCKERS if found:\n"
            f"- AP-03 Zero-logic wrapper: a function whose entire body is a single 1:1 delegate "
            f"call with no own logic must be inlined or eliminated.\n"
            f"- AP-04 Exclusive resource acquisition without reentrancy guard: if the diff introduces "
            f"exclusive resource acquisition (O_CREAT|O_EXCL, flock, Lock.acquire(), lock-file "
            f"creation) inside a method that can be reached from more than one call site or "
            f"called twice on the same instance (e.g. standalone + inside a wrapper), verify "
            f"that an explicit instance-level reentrancy guard exists. Without it: BLOCKER.\n"
            f"- AP-05 Boolean truthiness regression in changed return contracts: if the diff changes "
            f"a method's return type from implicit None to explicit bool, verify that every "
            f"caller uses `is False` / `is True` rather than generic truthiness (`if not x`, "
            f"`if x`, `while x`). Mixing None, False, and True under a falsy guard silently "
            f"breaks when the method is monkeypatched or called from a legacy path. "
            f"Any caller still using generic truthiness after the return-type change: BLOCKER."
        )
    elif dtype == "mixed":
        return (
            f"Review mixed ticket {ticket_id}. "
            f"Verify code correctness, tests, and style guides, and additionally verify "
            f"that all declared non-code deliverables exist, are well-structured, and are fully complete. "
            f"Check acceptance criteria and Files Likely Touched.\n\n"
            f"{SCAFFOLDING_PRECHECK}\n\n"
            f"{canonical_anti_patterns_block}"
            f"Test anti-patterns — flag as BLOCKERS if found:\n"
            f"- AP-01 Mock drift: each patch/mock must target the actual API the code calls.\n"
            f"- AP-02 Floor assertion: each numeric threshold must exceed the base value that "
            f"exists without the tested feature.\n\n"
            f"Implementation anti-patterns — flag as BLOCKERS if found:\n"
            f"- AP-03 Zero-logic wrapper: a function whose entire body is a single 1:1 delegate "
            f"call with no own logic must be inlined or eliminated.\n"
            f"- AP-04 Exclusive resource acquisition without reentrancy guard: if the diff introduces "
            f"exclusive resource acquisition (O_CREAT|O_EXCL, flock, Lock.acquire(), lock-file "
            f"creation) inside a method that can be reached from more than one call site or "
            f"called twice on the same instance, verify that an explicit reentrancy guard exists. "
            f"Without it: BLOCKER.\n"
            f"- AP-05 Boolean truthiness regression in changed return contracts: if the diff changes "
            f"a method's return type from implicit None to explicit bool, verify all callers use "
            f"`is False` / `is True` rather than generic truthiness (`if not x`, `if x`). "
            f"Any caller still using generic truthiness after the change: BLOCKER."
        )
    else:  # documentation, research, analysis
        return (
            f"Review non-code {dtype} ticket {ticket_id}. "
            f"Since this is a non-code deliverable, focus strictly on the clarity, depth, correctness, "
            f"structure, and completeness of the requested document deliverables. "
            f"Check acceptance criteria and Files Likely Touched."
        )
