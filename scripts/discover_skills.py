#!/usr/bin/env python3
"""
Skill Discovery System — Finds and indexes skills with triggers.

Generates trigger_map for Claude Code (the main IA backend) and the
``--check-contract`` prompt<->skill contract validation.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any


def extract_frontmatter(path: Path) -> dict[str, Any]:
    """Extract YAML frontmatter from SKILL.md.

    Returns empty dict on any error (legacy behavior for backward compat).
    Use parse_frontmatter() for tri-state distinction.
    """
    data, _ = parse_frontmatter(path)
    return data


def _parse_fm_lines(fm_text: str) -> dict[str, Any]:
    """Parse key:value lines from frontmatter text block."""
    data: dict[str, Any] = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if ": " in line:
            key, val = line.split(": ", 1)
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                val = [t.strip() for t in val[1:-1].split(",")]
            data[key] = val
        elif ":" in line and not line.startswith("#"):
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                val = [t.strip() for t in val[1:-1].split(",")]
            data[key] = val
    return data


def _validate_yaml(fm_text: str) -> str | None:
    """Validate frontmatter text as YAML. Returns error string or None."""
    try:
        import yaml

        yaml.safe_load(fm_text)
    except ImportError:
        return None
    except Exception as e:
        return f"YAML_INVALIDO: {e}"
    return None


def _split_frontmatter(content: str) -> tuple[str | None, str, int]:
    """Cut a markdown text into (frontmatter_text, body, body_line_offset).

    Before: ``content`` is the full text of a markdown file.
    During: applies THE frontmatter cut of this module -- anchored at line 1
            (``startswith("---")``) and ``split("---", 2)`` -- so no caller ever
            looks for "the first ``---``" on its own (32/48 prompts use ``---`` as
            a horizontal rule; DEC-router-prompts-001 D4).
    After: ``frontmatter_text`` is None when there is no block; ``body`` is the
           text after the closing ``---`` line; ``body_line_offset`` is the
           number of lines the block consumed (0 without frontmatter).
    """
    if not content.startswith("---"):
        return None, content, 0
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, content, 0
    body = parts[2]
    for newline in ("\r\n", "\n"):
        if body.startswith(newline):
            body = body[len(newline) :]
            break
    consumed = content[: len(content) - len(body)]
    return parts[1], body, consumed.count("\n")


def read_prompt_parts(path: Path) -> tuple[dict[str, Any], str | None, str, int]:
    """Parse a markdown file into (frontmatter_data, error, body, body_line_offset).

    Before: ``path`` points to a markdown file (it may not exist).
    During: reads it once (utf-8-sig) and applies ``_split_frontmatter``; the
            frontmatter is validated exactly like ``parse_frontmatter``.
    After: ``error`` follows ``parse_frontmatter`` (None, "NO_FRONTMATTER",
           "IO_ERROR: ..." or "YAML_INVALIDO: ..."); ``data`` is {} on any error;
           ``body``/``offset`` are always the post-frontmatter text and its line
           offset, so the PROMPT-SUMMARY window can be counted from there (T5).
    """
    try:
        with open(path, encoding="utf-8-sig") as f:
            content = f.read()
    except Exception as e:
        return {}, f"IO_ERROR: {e}", "", 0

    fm_raw, body, offset = _split_frontmatter(content)
    if fm_raw is None:
        return {}, "NO_FRONTMATTER", body, offset

    fm_text = fm_raw.strip()
    if not fm_text:
        return {}, "NO_FRONTMATTER", body, offset

    yaml_error = _validate_yaml(fm_text)
    if yaml_error:
        return {}, yaml_error, body, offset

    return _parse_fm_lines(fm_text), None, body, offset


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str | None]:
    """Parse YAML frontmatter from a markdown file.

    Returns (data, error) where:
      - error is None: valid frontmatter parsed
      - error == "NO_FRONTMATTER": file has no frontmatter block
      - error is a string: YAML parsing error description
      - data is empty dict on any error

    Delegates on ``read_prompt_parts`` (single cut, DEC-router-prompts-001); the
    signature and the returned values are unchanged.
    """
    data, error, _body, _offset = read_prompt_parts(path)
    return data, error


def _scan_skills_dir(
    directory: Path | None, bundle_root: Path | None = None
) -> dict[str, dict[str, Any]]:
    discovered = {}
    if not directory or not directory.exists() or not directory.is_dir():
        return discovered
    phase_root = bundle_root or _get_bundle_root()
    for skill_dir in sorted(directory.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        fm = extract_frontmatter(skill_file)
        if not fm:
            continue
        skill_name = fm.get("name", skill_dir.name)
        triggers = fm.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]

        discovered[skill_dir.name] = {
            "name": skill_name,
            "path": str(skill_dir),
            "skill_file": skill_file,
            "triggers": triggers,
            "version": fm.get("version", "1.0.0"),
            "description": fm.get("description", ""),
            # WOT-2026-008c: logical-authority metadata derived from frontmatter.
            "status": _derive_status(fm),
            "owner": _derive_owner(fm),
            # WOT-2026-008k: pipeline role exposed separately from owner. owner is
            # "who authored" (author, fallback role); role is "which pipeline role
            # owns the artifact" (frontmatter role, default "shared"). They may
            # coincide when no author is declared.
            "role": _derive_role(fm),
            # DEC-router-skills-001 D-S1: own cycle_phase, else inherited from
            # source_prompt. Empty tuple if neither resolves.
            "cycle_phase": _derive_cycle_phase(fm, phase_root),
            "aliases": list(triggers),
            # WOT-2026-010s: hybrid user/model-invoked taxonomy. Additive metadata;
            # does NOT affect trigger_map (triggers: stays the dispatch contract).
            "disable_model_invocation": _derive_disable_model_invocation(fm),
        }
    return discovered


# WOT-2026-008c: logical status values for the derived catalog.
# Authority remains frontmatter + live layout (DEC-008B-001, no registry.json).
VALID_STATUS = ("active", "deprecated", "draft")
DEFAULT_STATUS = "active"


def _derive_status(fm: dict[str, Any]) -> str:
    """Derive lifecycle status from frontmatter, default 'active'.

    Backward-compatible: files without a ``status:`` field are 'active'.
    Unknown values fall back to 'active' so a typo never silently hides a skill.
    """
    raw = fm.get("status", DEFAULT_STATUS)
    value = raw.strip().lower() if isinstance(raw, str) else DEFAULT_STATUS
    return value if value in VALID_STATUS else DEFAULT_STATUS


def _derive_disable_model_invocation(fm: dict[str, Any]) -> bool:
    """Derive the user-invoked flag from frontmatter (WOT-2026-010s).

    Backward-compatible hybrid taxonomy (inspired by mattpocock/skills
    docs/invocation.md, MIT, Adapted): ``disable-model-invocation: true`` marks a
    skill as user-invoked (the model must not auto-invoke it; a human or an
    explicit trigger still can). Absence of the field defaults to ``False``
    (model-invoked), so existing skills keep their current behaviour and
    ``trigger_map`` is unaffected. A non-boolean/invalid value also defaults to
    ``False`` so a typo never silently hides a skill from the model.
    """
    raw = fm.get("disable-model-invocation", False)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() == "true"
    return False


def _derive_owner(fm: dict[str, Any]) -> str:
    """Derive owner from frontmatter author, falling back to role then 'system'."""
    for key in ("author", "role"):
        val = fm.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "system"


def _derive_role(fm: dict[str, Any]) -> str:
    """Derive the pipeline role from frontmatter `role`, default 'shared'.

    WOT-2026-008k: role is exposed separately from owner so the catalog/INDEX can
    show which pipeline role owns a skill (e.g. auditor) independently of who
    authored it. Does not change _derive_owner semantics.
    """
    val = fm.get("role")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return "shared"


def _own_cycle_phase(fm: dict[str, Any]) -> tuple[str, ...]:
    """Normalize a skill/prompt frontmatter's own `cycle_phase` into a tuple.

    `cycle_phase: []` parses as [""] upstream; empty strings are dropped so an
    empty list reads as "absent", matching the prompt-side `_phase_errors`.
    """
    raw = fm.get("cycle_phase")
    values = raw if isinstance(raw, list) else [raw]
    return tuple(v for v in values if isinstance(v, str) and v)


def _derive_cycle_phase(fm: dict[str, Any], bundle_root: Path) -> tuple[str, ...]:
    """DEC-router-skills-001 D-S1: resolve a skill's `cycle_phase`.

    Before: ``fm`` is a skill's parsed frontmatter; ``bundle_root`` is the
            motor root (for resolving `source_prompt`).
    During: a skill's OWN `cycle_phase` always wins if declared (explicit
            override, e.g. when a pointer-skill needs a narrower phase than
            its prompt). Absent that, a pointer-skill (`source_prompt` set)
            inherits the `cycle_phase` of that prompt's frontmatter -- "skill
            apunta, prompt gobierna". An autocontenida with neither resolves
            to an empty tuple (no herencia posible; not an error here, the
            router/guard layer decides whether that is acceptable for its
            route_kind).
    After: a tuple of CYCLE_PHASES values (unvalidated against the enum here;
           callers that need the enum check reuse `_phase_errors`). Never
           raises: a missing/unreadable source_prompt resolves to "nothing to
           inherit", not an exception.
    """
    own = _own_cycle_phase(fm)
    if own:
        return own
    source_prompt = fm.get("source_prompt")
    if not isinstance(source_prompt, str) or not source_prompt:
        return ()
    prompt_path = _resolve_skill_path(source_prompt, bundle_root)
    if prompt_path is None or not prompt_path.exists():
        return ()
    prompt_fm, error = parse_frontmatter(prompt_path)
    if error:
        return ()
    return _own_cycle_phase(prompt_fm)


def _auto_host_skills_dir(bundle_root: Path) -> Path | None:
    """Resolve the host .agent/skills dir for host-first precedence, if any."""
    for candidate in (
        bundle_root.parent / ".agent" / "skills",
        Path.cwd() / ".agent" / "skills",
    ):
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def discover_skills(
    skills_dir: Path | None = None,
    host_skills_dir: Path | None = None,
) -> dict[str, Any]:
    """Discover all skills and their triggers.

    If host_skills_dir is provided (or auto-discovered under CWD/.agent/skills or bundle_root.parent/.agent/skills),
    host-defined skills override homonymous bundle-defined skills (host-first precedence).
    """
    bundle_root = Path(__file__).resolve().parent.parent
    if skills_dir is None:
        skills_dir = bundle_root / "skills"

    if host_skills_dir is None:
        host_skills_dir = _auto_host_skills_dir(bundle_root)

    bundle_skills = _scan_skills_dir(skills_dir, bundle_root)
    host_skills = _scan_skills_dir(host_skills_dir, bundle_root)

    host_triggers = set()
    for skill in host_skills.values():
        host_triggers.update(skill["triggers"])

    filtered_bundle_skills = {}
    for name, skill in bundle_skills.items():
        remaining_triggers = [t for t in skill["triggers"] if t not in host_triggers]
        if remaining_triggers:
            skill["triggers"] = remaining_triggers
            filtered_bundle_skills[name] = skill

    merged_skills = {**filtered_bundle_skills, **host_skills}

    skills: list[dict[str, Any]] = []
    trigger_map: dict[str, str] = {}

    for name in sorted(merged_skills.keys()):
        skill_entry = merged_skills[name]
        skill_file = skill_entry.pop("skill_file")
        skills.append(skill_entry)

        # WOT-2026-008c: only ACTIVE skills bind triggers. deprecated/draft
        # skills stay discoverable in the catalog but do not dispatch - the
        # derived status has real effect, not just presence on disk.
        if skill_entry.get("status", DEFAULT_STATUS) != "active":
            continue
        for trigger in skill_entry["triggers"]:
            trigger_map[trigger] = str(skill_file)

    return {
        "skills": skills,
        "trigger_map": trigger_map,
        "total_skills": len(skills),
        "total_triggers": len(trigger_map),
    }


def _get_bundle_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_skill_path(source_prompt: str, bundle_root: Path) -> Path | None:
    """Resolve source_prompt relative to bundle_root (repo_motor).

    Returns None if the path is absolute or not portable (resolves outside bundle_root).
    """
    candidate = (bundle_root / source_prompt).resolve()
    try:
        candidate.relative_to(bundle_root.resolve())
    except ValueError:
        return None
    return candidate


def _error(message: str) -> list[str]:
    return [message]


# Roles whose skills opt into the bidirectional prompt<->skill contract once they
# declare source_prompt/contract_id. WOT-2026-008k added "auditor" so the three
# contract-validated audit skills (audit-git-publication, audit-pipeline,
# system-health-audit) keep their source_prompt/contract_id enforcement after
# moving from role: manager to role: auditor. Shared->auditor skills without a
# contract still pass (the source_prompt/contract_id guard below lets them).
# DEC-router-skills-001 D-S2 added "orchestrator" so the 3 orchestrate-* skills
# (orchestrate-autonomous-ticket-batch, orchestrate-destination-batch,
# orchestrate-pipeline) stop escaping this gate under role: shared despite
# declaring source_prompt/contract_id.
CONTRACT_OPT_IN_ROLES = ("manager", "builder", "auditor", "orchestrator")


def _validate_frontmatter_contract_opt_in(
    skill_file: Path, bundle_root: Path
) -> tuple[dict[str, Any] | None, str | None]:
    """Return parsed frontmatter for opted-in role skills or a terminal error."""
    fm, fm_error = parse_frontmatter(skill_file)
    if fm_error == "NO_FRONTMATTER":
        return None, None
    if fm_error:
        rel = skill_file.relative_to(bundle_root).as_posix()
        return None, f"{rel}: YAML invalido ({fm_error})"

    role = fm.get("role", "")
    if role not in CONTRACT_OPT_IN_ROLES:
        return None, None

    source_prompt = fm.get("source_prompt", "")
    contract_id = fm.get("contract_id", "")
    if not (source_prompt or contract_id):
        return None, None

    return fm, None


def _validate_prompt_binding(
    rel_skill_path: str, source_prompt: str, contract_id: str, bundle_root: Path
) -> list[str]:
    """Validate prompt existence, portability, reverse anchor, and contract_id."""
    prompt_path = _resolve_skill_path(source_prompt, bundle_root)
    if prompt_path is None:
        return _error(
            f"{rel_skill_path}: source_prompt '{source_prompt}' no es portable contra repo_motor"
        )
    if not prompt_path.exists():
        return _error(f"{rel_skill_path}: source_prompt '{source_prompt}' no existe")

    prompt_content = prompt_path.read_text(encoding="utf-8")
    expected_anchor = f"Skill canonica: {rel_skill_path}"
    if expected_anchor not in prompt_content:
        return _error(
            f"{rel_skill_path}: prompt '{source_prompt}' no contiene '{expected_anchor}'"
        )

    prompt_contract_pattern = re.compile(
        rf"^contract_id:\s*{re.escape(contract_id)}\s*$", re.MULTILINE
    )
    if not prompt_contract_pattern.search(prompt_content):
        return _error(
            f"{rel_skill_path}: prompt '{source_prompt}' no contiene contract_id '{contract_id}'"
        )

    return []


def _validate_skill_contract(skill_file: Path, bundle_root: Path) -> list[str]:
    """Validate contract for a single skill file.

    Role skills opt into this contract once they declare either
    `source_prompt:` or `contract_id`. From that point onward the contract is
    strict and partial metadata is rejected.
    """
    fm, terminal_error = _validate_frontmatter_contract_opt_in(skill_file, bundle_root)
    if terminal_error:
        return _error(terminal_error)
    if fm is None:
        return []

    rel_skill_path = skill_file.relative_to(bundle_root).as_posix()
    source_prompt = fm.get("source_prompt", "")
    contract_id = fm.get("contract_id", "")

    if not source_prompt:
        return _error(f"{rel_skill_path}: falta source_prompt")

    if not contract_id:
        return _error(f"{rel_skill_path}: falta contract_id")

    return _validate_prompt_binding(
        rel_skill_path, source_prompt, contract_id, bundle_root
    )


# --------------------------------------------------------------------------
# WOT-2026-008d: naming convention gate (DEC-008D-001).
# prompts -> snake_case ; skills -> kebab-case. The gate validates the live
# prompt+skill surface and fails closed on a new non-conforming name.
# Authority for naming lives here, not in check_skill_collisions.py.
# --------------------------------------------------------------------------

# Snake_case prompt filename stem: lowercase alnum groups joined by single "_".
_PROMPT_NAME_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")
# Kebab-case skill dir name: lowercase alnum groups joined by single "-".
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Pipeline actor tokens (long form) for the DEC-008D-001 actor-first rule.
# Short forms `man-`/`bui-` are already actor-first by construction; the rule
# targets the long-form actors that can appear in either order.
_ACTOR_TOKENS: frozenset[str] = frozenset({"manager", "builder"})

# Pipeline ACTIONS the actor performs. The actor-first rule only fires when an
# actor is paired with one of THESE verbs in actor-last order
# (review_manager -> manager_review). This deliberately excludes head-noun uses
# like `refactor-manager` (manager is the subject, not paired with a pipeline
# action) to avoid AP-16 over-matching: a domain word (`refactor`) is not a
# pipeline action, so refactor-manager is left alone.
_PIPELINE_ACTIONS: frozenset[str] = frozenset(
    {"review", "implement", "create", "plan", "audit", "resolve", "approve"}
)

# Known legacy names tolerated by HARDCODE until their atomic rename ticket.
# WOT-2026-008e emptied this: review_manager -> manager_review is now tolerated
# declaratively via `legacy_aliases:` frontmatter in prompts/manager_review.md
# (see _declared_prompt_aliases), not by hardcode. Keep this empty; a name only
# belongs here if there is no canonical artifact yet to declare its alias.
KNOWN_LEGACY_NAMES: frozenset[str] = frozenset()


def _declared_prompt_aliases(prompts_dir: Path) -> set[str]:
    """Collect legacy stub names declared via prompt frontmatter (WOT-2026-008e).

    Before: prompts_dir may or may not exist.
    During: parse each prompts/*.md frontmatter with the existing
            parse_frontmatter(); collect every entry of `legacy_aliases:` into a
            flat set. This is the declarative replacement for KNOWN_LEGACY_NAMES:
            a canonical prompt (e.g. manager_review.md) declares the legacy stem
            (review_manager) it supersedes, and --check-naming tolerates a stub
            file whose stem is in this set.
    After: returns a set of legacy alias stems (empty if none / no dir). No
           side effects beyond reading files.
    """
    aliases: set[str] = set()
    if not prompts_dir.is_dir():
        return aliases
    for path in sorted(prompts_dir.glob("*.md")):
        fm, _ = parse_frontmatter(path)
        declared = fm.get("legacy_aliases", [])
        if isinstance(declared, str):
            declared = [declared]
        for alias in declared:
            if isinstance(alias, str) and alias.strip():
                aliases.add(alias.strip())
    return aliases


def _actor_order_violation(stem: str, sep: str) -> str | None:
    """Return an actor-first violation message for `stem`, or None if clean.

    DEC-008D-001 central rule: when a name pairs a pipeline actor with a
    pipeline ACTION, the actor goes first. `review_manager` (action_actor)
    violates; `manager_review` (actor_action) is clean. The rule fires ONLY when
    BOTH an actor token and a pipeline action token are present and the actor is
    not first — so `refactor-manager` (no pipeline action) and `launch_builder`
    (launch is not a pipeline action the actor performs) are left alone.

    Pure string analysis on the already-split tokens; no I/O.
    """
    tokens = stem.split(sep)
    if len(tokens) < 2:
        return None
    if not (_ACTOR_TOKENS & set(tokens) and _PIPELINE_ACTIONS & set(tokens)):
        return None
    # Both an actor and a pipeline action are present: the actor must be first.
    if tokens[0] in _ACTOR_TOKENS:
        return None
    actor = next(t for t in tokens if t in _ACTOR_TOKENS)
    return (
        f"violates actor-first (DEC-008D-001): actor '{actor}' must precede the "
        f"pipeline action (expected '{actor}{sep}...', got '{stem}')"
    )


def _name_violation(
    stem: str, lexical_re: re.Pattern[str], kind: str, sep: str
) -> str | None:
    """Return the first DEC-008D-001 violation for `stem`, or None if clean.

    Runs two rules in order: (1) lexical form (snake/kebab) and (2) actor-first
    ordering. A name is only clean if it passes BOTH. KNOWN_LEGACY_NAMES is
    applied by the caller AFTER detection, so legacy names are recorded as
    tolerated debt rather than silently treated as fully conformant.
    """
    expected = "[a-z0-9]+(_[a-z0-9]+)*" if sep == "_" else "[a-z0-9]+(-[a-z0-9]+)*"
    style = "snake_case" if sep == "_" else "kebab-case"
    if not lexical_re.match(stem):
        return f"{kind} '{stem}' violates {style} (DEC-008D-001): expected {expected}"
    return _actor_order_violation(stem, sep)


def _check_prompt_names(prompts_dir: Path) -> list[str]:
    """Flag prompts/*.md stems that violate DEC-008D-001 (snake_case + actor-first).

    A violating stem is tolerated only if it is a declared legacy alias: either
    in KNOWN_LEGACY_NAMES (hardcode, now empty) or in the `legacy_aliases:`
    frontmatter of some canonical prompt (WOT-2026-008e declarative path).
    """
    if not prompts_dir.is_dir():
        return []
    tolerated = KNOWN_LEGACY_NAMES | _declared_prompt_aliases(prompts_dir)
    out: list[str] = []
    for path in sorted(prompts_dir.glob("*.md")):
        stem = path.stem
        violation = _name_violation(stem, _PROMPT_NAME_RE, "prompt", "_")
        if violation and stem not in tolerated:
            out.append(violation)
    return out


def _check_skill_names(skills_dir: Path) -> list[str]:
    """Flag skills/<dir> names that violate DEC-008D-001 (kebab-case + actor-first).

    Also flags skills whose frontmatter name field does not equal the directory
    name (WOT-2026-014g). This check is additive: it does not affect the
    existing kebab-case/actor-first rules.
    """
    if not skills_dir.is_dir():
        return []
    out: list[str] = []
    for path in sorted(skills_dir.iterdir()):
        if not path.is_dir() or path.name.startswith("_"):
            continue
        name = path.name
        violation = _name_violation(name, _SKILL_NAME_RE, "skill", "-")
        if violation and name not in KNOWN_LEGACY_NAMES:
            out.append(violation)
        # WOT-2026-014g: frontmatter name must equal directory name.
        skill_file = path / "SKILL.md"
        if skill_file.exists():
            fm, _ = parse_frontmatter(skill_file)
            fm_name = fm.get("name", "")
            if fm_name and fm_name != path.name:
                out.append(
                    f"skill '{path.name}': frontmatter name='{fm_name}' != directory name='{path.name}'",
                )
    return out


def check_naming(bundle_root: Path | None = None) -> list[str]:
    """Return naming-convention violations on the live prompt+skill surface.

    Before: bundle_root resolves to the motor root (auto if None). prompts/ and
            skills/ may or may not exist.
    During: validates every prompts/*.md and prompts/_shared/*.md stem against
            snake_case and every skills/<dir> name against kebab-case
            (DEC-008D-001). prompts/_shared/ is checked explicitly
            (DEC-router-prompts-001 T8: the router lists those modules, so their
            names are surface too). skills/ directories starting with "_" and
            non-.md files are skipped. Names in KNOWN_LEGACY_NAMES are tolerated.
    After: returns a list of human-readable violation strings (empty == clean).
           No side effects, no I/O beyond directory listing.
    """
    if bundle_root is None:
        bundle_root = _get_bundle_root()
    prompts_dir = bundle_root / "prompts"
    return (
        _check_prompt_names(prompts_dir)
        + _check_prompt_names(prompts_dir / "_shared")
        + _check_skill_names(bundle_root / "skills")
    )


def _check_naming() -> int:
    """CLI entry for --check-naming. Returns 0 if clean, 1 on any violation."""
    violations = check_naming()
    if violations:
        for v in violations:
            print(f"[NAMING] {v}", file=sys.stderr)
        print(
            f"[NAMING] {len(violations)} naming violation(s); see DEC-008D-001.",
            file=sys.stderr,
        )
        return 1
    print("[OK] All prompt/skill names conform to DEC-008D-001.")
    return 0


def _check_contract() -> int:
    """Validate bidirectional prompt<->skill contract for all skills with role: manager|builder.

    Returns 0 if all contracts are valid, 1 otherwise.
    """
    bundle_root = _get_bundle_root()
    skills_dir = bundle_root / "skills"

    if not skills_dir.exists():
        print("ERROR: skills/ directory not found", file=sys.stderr)
        return 1

    all_errors: list[str] = []

    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        errors = _validate_skill_contract(skill_file, bundle_root)
        all_errors.extend(errors)

    if all_errors:
        for e in all_errors:
            print(e, file=sys.stderr)
        return 1

    return 0


# --------------------------------------------------------------------------
# WOT-2026-008c: derived catalog + generated INDEX projection.
# Authority stays in frontmatter + live layout (DEC-008B-001). The catalog is
# derived on every call; INDEX.md is a generated projection, never a source.
# --------------------------------------------------------------------------

# The five discovery/dispatch consumers declared by 008a/008c. Listed so the
# catalog documents the active consumer surface (script-consumer kind).
SCRIPT_CONSUMERS = (
    "scripts/discover_skills.py",
    "scripts/check_skill_collisions.py",
    "scripts/validate_agent_config.py",
    "scripts/run_gates_dispatch.py",
    "bus/skill_resolver.py",
)

INDEX_REL_PATH = "docs/registry/INDEX.md"
INDEX_AUTOGEN_MARKER = "<!-- AUTOGENERATED by discover_skills.py --generate-index"


def _rel(path: Path, root: Path) -> str:
    """Return path relative to root with forward slashes."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _catalog_entry(
    kind: str,
    path: Path,
    root: Path,
    *,
    status: str = DEFAULT_STATUS,
    owner: str = "system",
    role: str = "shared",
    aliases: list[str] | None = None,
    disable_model_invocation: bool = False,
) -> dict[str, Any]:
    """Build one canonical catalog entry. canonical_source == path (no renames).

    WOT-2026-008c: ``invocation`` reflects the hybrid taxonomy from WOT-2026-010s.
    ``disable_model_invocation: true`` -> ``user-invoked``; otherwise
    ``model-invoked``. Only skills carry the flag; other kinds default to
    model-invoked (the model may reach them).
    """
    rel = _rel(path, root)
    return {
        "kind": kind,
        "path": rel,
        "status": status,
        "owner": owner,
        "role": role,
        "canonical_source": rel,
        "aliases": sorted(aliases) if aliases else [],
        "invocation": "user-invoked" if disable_model_invocation else "model-invoked",
    }


def build_catalog(bundle_root: Path | None = None) -> dict[str, Any]:
    """Derive the enriched catalog from live sources (no manifest on disk).

    Before: bundle_root is the motor root (defaults to this file's parent.parent).
    During: scans skills/ (with frontmatter-derived status/owner/aliases),
            prompts/, references, _shared and lists the script consumers.
    After: returns {"entries": [...], "counts": {...}} sorted by (kind, path).
    """
    root = bundle_root or _get_bundle_root()

    # Skills: reuse the frontmatter-derived metadata from discover_skills().
    discovered = _scan_skills_dir(root / "skills", root)
    entries: list[dict[str, Any]] = [
        _catalog_entry(
            "skill",
            Path(skill["skill_file"]),
            root,
            status=skill.get("status", DEFAULT_STATUS),
            owner=skill.get("owner", "system"),
            role=skill.get("role", "shared"),
            aliases=skill.get("aliases", []),
            disable_model_invocation=skill.get("disable_model_invocation", False),
        )
        for skill in discovered.values()
    ]

    # Prompts, references and shared docs.
    # WOT-2026-011d: prompt lifecycle is derived from a real source in the file
    # (frontmatter `status:`) via the same _derive_status() used for skills, not
    # assumed "active" by layout. Vocabulary stays active|deprecated|draft: a
    # legacy stub declaring `status: deprecated` no longer publishes as active.
    # DEC-router-prompts-001: the prompt's frontmatter `role` (scalar) reaches the
    # catalog through the same _derive_role() used for skills (default shared).
    entries += [
        _catalog_entry(
            "prompt",
            p,
            root,
            status=_derive_status(fm),
            role=_derive_role(fm),
        )
        for p in sorted((root / "prompts").glob("*.md"))
        for fm in (parse_frontmatter(p)[0],)
    ]
    entries += [
        _catalog_entry("reference", p, root)
        for p in sorted((root / "skills").glob("*/references/*.md"))
    ]
    entries += [
        _catalog_entry("shared", p, root)
        for p in sorted((root / "skills" / "_shared").glob("*.md"))
    ]

    # Script consumers (active discovery/dispatch surface).
    entries += [
        _catalog_entry("script-consumer", root / rel, root, owner="system")
        for rel in SCRIPT_CONSUMERS
        if (root / rel).exists()
    ]

    entries.sort(key=lambda e: (e["kind"], e["path"]))
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    counts["total"] = len(entries)
    return {"entries": entries, "counts": counts}


def render_index(catalog: dict[str, Any]) -> str:
    """Render the INDEX.md projection from a derived catalog (deterministic)."""
    lines: list[str] = [
        f"{INDEX_AUTOGEN_MARKER}; do not edit by hand (WOT-2026-008c). -->",
        "# Catálogo de prompts y skills (proyección generada)",
        "",
        "> Proyección generada por `discover_skills.py --generate-index`.",
        "> Autoridad lógica: frontmatter + layout vivo + `discover_skills.py`",
        "> (DEC-008B-001). Este archivo NO es fuente de verdad; regenéralo con",
        "> `python scripts/discover_skills.py --generate-index`.",
        "",
        "## Conteo por kind",
        "",
        "| kind | total |",
        "|------|-------|",
    ]
    counts = catalog["counts"]
    lines += [
        f"| {kind} | {counts[kind]} |"
        for kind in sorted(k for k in counts if k != "total")
    ]
    lines.append(f"| **total** | **{counts['total']}** |")
    lines += [
        "",
        "## Entradas",
        "",
        "| kind | path | status | owner | role | invocation | aliases |",
        "|------|------|--------|-------|------|------------|---------|",
    ]
    for e in catalog["entries"]:
        aliases = ", ".join(e["aliases"]) if e["aliases"] else "—"
        invocation = e.get("invocation", "model-invoked")
        role = e.get("role", "shared")
        lines.append(
            f"| {e['kind']} | `{e['path']}` | {e['status']} | {e['owner']} "
            f"| {role} | {invocation} | {aliases} |"
        )
    lines.append("")
    return "\n".join(lines)


def generate_index(bundle_root: Path | None = None) -> Path:
    """Generate docs/registry/INDEX.md from the live catalog. Returns its path."""
    root = bundle_root or _get_bundle_root()
    catalog = build_catalog(root)
    index_path = root / INDEX_REL_PATH
    index_path.parent.mkdir(parents=True, exist_ok=True)
    # LF explicito: .gitattributes fija `*.md eol=lf` y el hook mixed-line-ending
    # (--fix=lf) abortaba el commit cada vez que se regeneraba en Windows (CRLF).
    index_path.write_text(render_index(catalog), encoding="utf-8", newline="\n")
    return index_path


def check_index_stale(bundle_root: Path | None = None) -> tuple[bool, str]:
    """Check whether INDEX.md matches the live catalog projection.

    Returns (is_stale, diagnostic). is_stale is True when INDEX.md is missing or
    diverges from the freshly-derived projection.
    """
    root = bundle_root or _get_bundle_root()
    index_path = root / INDEX_REL_PATH
    expected = render_index(build_catalog(root))
    if not index_path.exists():
        return True, f"{INDEX_REL_PATH} does not exist; run --generate-index."
    actual = index_path.read_text(encoding="utf-8")
    if actual != expected:
        return True, (
            f"{INDEX_REL_PATH} is stale vs the live discovery catalog. "
            "Regenerate with: python scripts/discover_skills.py --generate-index"
        )
    return False, ""


# --------------------------------------------------------------------------
# DEC-router-prompts-001: phase router of the prompts (generated projection).
# Source of truth: each prompt's frontmatter (role / cycle_phase / route_kind)
# plus its WOT-2026-022o PROMPT-SUMMARY. ROUTER.md is derived on every call and
# checked by --check-index (pre-commit hook check-index-stale, always_run).
# --------------------------------------------------------------------------

ROUTER_REL_PATH = "docs/registry/ROUTER.md"
ROUTER_AUTOGEN_MARKER = (
    "<!-- AUTOGENERATED by discover_skills.py --generate-index (router)"
)
# Read before opening any prompt, so it must stay short: a WARN, never a block
# (doc_optimization.md PASO 5: WARN first).
ROUTER_MAX_LINES_WARN = 150

# D1: temporal phases of the cycle (NOT the dispatcher's --phase vocabulary).
CYCLE_PHASES: tuple[str, ...] = (
    "F0-arranque-sesion",
    "F1-backlog",
    "F2-contrato",
    "F3-auditoria-contrato",
    "F4-lanzamiento",
    "F5-implementacion",
    "F6-revision",
    "F7-cierre-sesion",
    "F8-meta-auditoria",
)
# D2: closed enum. Named route_kind because the catalog already has a `kind`.
ROUTE_KINDS: tuple[str, ...] = ("entry", "modo", "modulo", "mantenimiento", "externo")
# D3: canonical roles of AGENTS.md (never a backend); `role` is a scalar.
CANONICAL_ROLES: tuple[str, ...] = ("orchestrator", "manager", "builder", "auditor")
# D2: external artifacts consumed whole by another system; exempt from metadata.
EXTERNAL_ALLOWLIST: frozenset[str] = frozenset({"hermes_soul.md"})
# D4: (role rule, cycle_phase rule) per route_kind.
_ROUTE_RULES: dict[str, tuple[str, str]] = {
    "entry": ("required", "required"),
    "modo": ("required", "required"),
    "modulo": ("optional", "forbidden"),
    "mantenimiento": ("required", "forbidden"),
    "externo": ("forbidden", "forbidden"),
}
# D5: loop defaults per cycle phase -> (dispatcher --phase, is governance,
# --task-type, note). Validated against ensemble_dispatch by the tests (T7).
PHASE_LOOP_PARAMS: dict[str, tuple[str, bool, str, str]] = {
    "F1-backlog": ("TRIAGE_AUDIT", False, "triage", ""),
    "F3-auditoria-contrato": ("CONTRACT_AUDIT", True, "contract-audit", ""),
    "F6-revision": (
        "MANAGER_REVIEW",
        True,
        "code-review",
        "`prose` si el entregable es documentation/research/analysis (decision provisional)",
    ),
    "F7-cierre-sesion": ("CLOSE", True, "contract-audit", ""),
}
PROMPT_SUMMARY_MARKER = "<!-- PROMPT-SUMMARY"
# T5: the block must close within these lines AFTER the frontmatter.
PROMPT_SUMMARY_SCAN_LINES = 12
_SUMMARY_KEYS = ("what", "when", "not")
_MAX_LISTED_CITERS = 5


def prompt_summary(body: str) -> dict[str, str]:
    """Return the what/when/not of the PROMPT-SUMMARY block of a prompt body.

    Before: ``body`` is the text AFTER the frontmatter (``read_prompt_parts``).
    During: scans only the first PROMPT_SUMMARY_SCAN_LINES lines for the marker
            and its closing ``-->`` (both must fall inside the window).
    After: {key: value} for the keys found; {} if absent or not closed in time.
    """
    lines = body.splitlines()[:PROMPT_SUMMARY_SCAN_LINES]
    start = next((i for i, ln in enumerate(lines) if PROMPT_SUMMARY_MARKER in ln), None)
    if start is None:
        return {}
    end = next((i for i in range(start, len(lines)) if lines[i].strip() == "-->"), None)
    if end is None:
        return {}
    summary: dict[str, str] = {}
    for line in lines[start + 1 : end]:
        key, sep, value = line.partition(":")
        if sep and key.strip() in _SUMMARY_KEYS:
            summary[key.strip()] = value.strip()
    return summary


def validate_route_metadata(name: str, fm: dict[str, Any]) -> list[str]:
    """Validate the routing frontmatter of one prompt against DEC D1-D4.

    Before: ``name`` is the prompt path relative to prompts/; ``fm`` its parsed
            frontmatter (``read_prompt_parts``).
    During: checks route_kind (closed enum; externo only via allowlist), the
            per-kind obligations of role/cycle_phase, role as ONE canonical role
            and cycle_phase values within D1.
    After: list of human-readable errors (empty == valid). No I/O.
    """
    kind = fm.get("route_kind")
    if not isinstance(kind, str) or kind not in ROUTE_KINDS:
        return [f"{name}: route_kind {kind!r} fuera del enum {list(ROUTE_KINDS)}"]
    errors: list[str] = []
    if kind == "externo" and Path(name).name not in EXTERNAL_ALLOWLIST:
        errors.append(
            f"{name}: route_kind externo solo para la allowlist {sorted(EXTERNAL_ALLOWLIST)}"
        )
    role_rule, phase_rule = _ROUTE_RULES[kind]
    errors += _role_errors(name, kind, fm.get("role"), role_rule)
    errors += _phase_errors(name, kind, fm.get("cycle_phase"), phase_rule)
    return errors


def _role_errors(name: str, kind: str, role: Any, rule: str) -> list[str]:
    """D3/D4: `role` obligation per route_kind and ONE canonical role."""
    if role in (None, ""):
        return (
            [f"{name}: role obligatorio para route_kind {kind}"]
            if rule == "required"
            else []
        )
    if rule == "forbidden":
        return [f"{name}: role no aplica a route_kind {kind}"]
    if not isinstance(role, str) or role not in CANONICAL_ROLES:
        return [f"{name}: role {role!r} debe ser UN valor de {list(CANONICAL_ROLES)}"]
    return []


def _phase_errors(name: str, kind: str, phases: Any, rule: str) -> list[str]:
    """D1/D4: `cycle_phase` obligation per route_kind and values within D1.

    `cycle_phase: []` parses as [""] (`_parse_fm_lines`): empty strings are
    dropped first, so an empty list means "absent", not an odd value.
    """
    values = phases if isinstance(phases, list) else [phases]
    values = [v for v in values if v not in (None, "")]
    if not values:
        if rule == "required":
            return [f"{name}: cycle_phase obligatoria para route_kind {kind}"]
        return []
    if rule == "forbidden":
        return [f"{name}: cycle_phase prohibida para route_kind {kind} (DEC D4)"]
    unknown = [v for v in values if v not in CYCLE_PHASES]
    return (
        [f"{name}: cycle_phase con valores fuera de D1: {unknown}"] if unknown else []
    )


def _prompt_files(root: Path) -> list[Path]:
    """prompts/*.md followed by prompts/_shared/*.md (the router universe)."""
    prompts_dir = root / "prompts"
    return sorted(prompts_dir.glob("*.md")) + sorted(
        (prompts_dir / "_shared").glob("*.md")
    )


def _citation_pattern(module_path: Path) -> re.Pattern[str]:
    """Regex of a citation of ``module_path`` (DEC D4, executable definition).

    The file name needs a boundary on BOTH sides: ``foo.x.md``, ``x.md.bak`` and
    ``x.mdx`` name other files; ``x.md.`` at the end of a sentence still counts.
    """
    name = re.escape(module_path.stem) + r"\.md"
    if module_path.parent.name == "_shared":
        prefixed = rf"(?<!skills/)_shared/{name}"
    else:
        prefixed = rf"prompts/{name}"
    bare = rf"(?<![A-Za-z0-9_./\-]){name}"
    return re.compile(rf"(?:{prefixed}|{bare})(?![A-Za-z0-9_\-]|\.[A-Za-z0-9])")


def _strip_summary_block(text: str) -> str:
    """Remove the PROMPT-SUMMARY block of a text, only if it is well formed.

    The block counts only when its closing ``-->`` falls within
    PROMPT_SUMMARY_SCAN_LINES lines of the marker (same window as
    ``prompt_summary``); an unclosed block removes nothing, so it can never
    hide a real citation that comes after it.
    """
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if PROMPT_SUMMARY_MARKER in ln), None)
    if start is None:
        return text
    window = range(start, min(len(lines), start + PROMPT_SUMMARY_SCAN_LINES))
    end = next((i for i in window if lines[i].strip() == "-->"), None)
    if end is None:
        return text
    return "".join(lines[:start] + lines[end + 1 :])


def module_citations(module_path: Path, root: Path) -> list[str]:
    """Return who cites a module: names relative to prompts/, or ``AGENTS.md``.

    Before: ``module_path`` is a prompt file under ``root``/prompts.
    During: searches prompts/*.md, prompts/_shared/*.md and AGENTS.md (the
            module itself excluded) for a literal occurrence of its file with
            extension: the prefixed path, or ``<name>.md`` as a token. Prose
            mentions with the path COUNT on purpose (navigation heuristic, not
            "who really uses it"); a bare word without ``.md`` does not.
            A well-formed PROMPT-SUMMARY block is skipped: its ``not:`` line
            says "this is NOT <file>", routing metadata, not a citation.
            Windows separators are normalised to ``/`` first, so
            ``skills\\_shared\\x.md`` is excluded like ``skills/_shared/x.md``.
    After: sorted list of citing names (empty == orphan module, T9 fails).
    """
    pattern = _citation_pattern(module_path)
    target = module_path.resolve()
    citers: list[str] = []
    candidates = [*_prompt_files(root), root / "AGENTS.md"]
    for path in candidates:
        if not path.is_file() or path.resolve() == target:
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        text = _strip_summary_block(text).replace("\\", "/")
        if pattern.search(text):
            if path.name == "AGENTS.md" and path.parent == root:
                citers.append("AGENTS.md")
            else:
                citers.append(path.relative_to(root / "prompts").as_posix())
    return sorted(citers)


def skill_pointer_for_prompt(prompt_rel: str, root: Path) -> str | None:
    """DEC-router-skills-001 D-S6: the skill-dir name whose `source_prompt`
    points at ``prompt_rel`` (e.g. "manager_review.md" or "_shared/gate.md"),
    or None if no skill-puntero declares this prompt as its source.

    Reuses the same bidirectional binding `_check_contract` already relies
    on (`source_prompt: prompts/<prompt_rel>`), so the router column and the
    contract gate can never silently disagree about which skill points at a
    prompt. At most one skill is expected to point at a given prompt in
    practice; if more than one does, the first found (sorted by dir name)
    wins -- deterministic, not a validated invariant here.
    """
    skills_dir = root / "skills"
    if not skills_dir.exists():
        return None
    expected = f"prompts/{prompt_rel}"
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        fm, error = parse_frontmatter(skill_file)
        if error:
            continue
        if fm.get("source_prompt") == expected:
            return skill_dir.name
    return None


def standalone_skills_by_phase(root: Path) -> dict[str, list[str]]:
    """DEC-router-skills-001 D-S6: group autocontenida skills by cycle_phase.

    Before: ``root`` is the motor root.
    During: scans ``skills/*/SKILL.md``; a skill is "standalone" for this
            section when it declares NO `source_prompt` (a pointer-skill's
            phase comes from D-S1's herencia/override and is already shown
            via its prompt's row -- listing it again here would duplicate
            it). Skills with no own `cycle_phase` are not groupable; they
            are absent from the pending-prompts-style gap this section
            fills, not an error.
    After: {cycle_phase: [skill_dir_name, ...]}, each list sorted; only
           phases with at least one skill are present as keys.
    """
    skills_dir = root / "skills"
    by_phase: dict[str, list[str]] = {}
    if not skills_dir.exists():
        return by_phase
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        fm, error = parse_frontmatter(skill_file)
        if error or fm.get("source_prompt"):
            continue
        for phase in _own_cycle_phase(fm):
            by_phase.setdefault(phase, []).append(skill_dir.name)
    for names in by_phase.values():
        names.sort()
    return by_phase


def _route_entries(root: Path) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Split the router universe into (adopted entries, pending names, exempt names)."""
    entries: list[dict[str, Any]] = []
    pending: list[str] = []
    exempt: list[str] = []
    for path in _prompt_files(root):
        rel = path.relative_to(root / "prompts").as_posix()
        if rel in EXTERNAL_ALLOWLIST:
            exempt.append(rel)
            continue
        fm, _error, body, offset = read_prompt_parts(path)
        kind = fm.get("route_kind")
        if not kind:
            pending.append(rel)
            continue
        phases = fm.get("cycle_phase") or []
        if isinstance(phases, str):
            phases = [phases]
        role = fm.get("role")
        entries.append(
            {
                "rel": rel,
                "path": path,
                "kind": kind,
                "role": role if isinstance(role, str) else "",
                "phases": [p for p in phases if p],
                "summary": prompt_summary(body),
                # One read per file: frontmatter lines + body lines.
                "lines": offset + len(body.splitlines()),
                # D-S6: which skill-puntero (if any) points at this prompt.
                "skill": skill_pointer_for_prompt(rel, root),
            }
        )
    return entries, pending, exempt


def router_metadata_errors(bundle_root: Path | None = None) -> list[str]:
    """Validate every routed file of the universe (DEC D4 + T6 + T9).

    Before: ``bundle_root`` is the motor root (auto if None).
    During: for each prompt that declares ``route_kind``: runs
            ``validate_route_metadata`` and, for a ``modulo``, requires at least
            one citation (``module_citations``); an allowlisted external file
            must carry no routing frontmatter.
    After: list of errors (empty == the router can be generated); used by
           --generate-index (refuses to write) and --check-index (fails), so
           invalid metadata never reaches ROUTER.md silently.
    """
    root = bundle_root or _get_bundle_root()
    errors: list[str] = []
    for path in _prompt_files(root):
        rel = path.relative_to(root / "prompts").as_posix()
        fm = read_prompt_parts(path)[0]
        if rel in EXTERNAL_ALLOWLIST:
            if fm.get("route_kind"):
                errors.append(
                    f"{rel}: externo exento, no lleva frontmatter de enrutado (T6)"
                )
            continue
        if not fm.get("route_kind"):
            continue
        errors += validate_route_metadata(rel, fm)
        if fm.get("route_kind") == "modulo" and not module_citations(path, root):
            errors.append(
                f"{rel}: modulo sin ninguna cita en prompts/ ni AGENTS.md (T9)"
            )
    return errors


def _cell(value: Any) -> str:
    """One markdown table cell: single line, pipes escaped, '-' when empty."""
    text = " ".join(str(value).split()).replace("|", "\\|")
    return text or "-"


def build_router(bundle_root: Path | None = None) -> str:
    """Render ROUTER.md from the adopted prompts (deterministic projection).

    Before: ``bundle_root`` is the motor root (auto if None).
    During: reads the routing frontmatter + PROMPT-SUMMARY of every prompt in
            prompts/ and prompts/_shared/ and the citations of each modulo.
    After: the full markdown text; prompts without ``route_kind`` are counted as
           pending and NOT routed; the external allowlist is declared, not routed.
    """
    root = bundle_root or _get_bundle_root()
    entries, pending, exempt = _route_entries(root)
    lines = _router_header(len(entries), len(entries) + len(pending), exempt)
    lines += _router_cycle_section(_of_kind(entries, "entry"))
    lines += _router_standalone_skills_section(standalone_skills_by_phase(root))
    lines += _router_table(
        "## Modos (encadenan fases por ticket)",
        "| Prompt | Fases | Rol | Skill | Cuando | NO es | Lineas |",
        [
            f"| `prompts/{e['rel']}` | {_cell(', '.join(e['phases']))} | {_cell(e['role'])}"
            f" | {_skill_cell(e)} | {_summary_cell(e, 'when')} | {_summary_cell(e, 'not')}"
            f" | {e['lines']} |"
            for e in _of_kind(entries, "modo")
        ],
    )
    lines += _router_table(
        "## Fuera del ciclo (mantenimiento)",
        "| Prompt | Rol | Skill | Cuando | NO es | Lineas |",
        [
            f"| `prompts/{e['rel']}` | {_cell(e['role'])} | {_skill_cell(e)}"
            f" | {_summary_cell(e, 'when')} | {_summary_cell(e, 'not')} | {e['lines']} |"
            for e in _of_kind(entries, "mantenimiento")
        ],
    )
    lines += _router_table(
        "## Modulos (no los abras tu: te los cita otro prompt)",
        "| Modulo | Lo citan | Que es | Lineas |",
        [
            f"| `prompts/{e['rel']}` | {_cell(_citers_cell(module_citations(e['path'], root)))}"
            f" | {_summary_cell(e, 'what')} | {e['lines']} |"
            for e in _of_kind(entries, "modulo")
        ],
    )
    lines += _router_roles_section(entries)
    return "\n".join(lines)


def _of_kind(entries: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Adopted entries of one route_kind, sorted by path (deterministic output)."""
    return sorted((e for e in entries if e["kind"] == kind), key=lambda e: e["rel"])


def _summary_cell(entry: dict[str, Any], key: str) -> str:
    """One PROMPT-SUMMARY field of an entry as a table cell."""
    return _cell(entry["summary"].get(key, ""))


def _citers_cell(citers: list[str]) -> str:
    """List the citers, or collapse them to 'transversal (N)' above the limit."""
    if len(citers) > _MAX_LISTED_CITERS:
        return f"transversal ({len(citers)})"
    return ", ".join(citers)


def _router_header(adopted: int, total: int, exempt: list[str]) -> list[str]:
    """Marker, title, how to read it and the adoption status of the router."""
    exempt_note = f" (exento: {', '.join(exempt)})" if exempt else ""
    return [
        f"{ROUTER_AUTOGEN_MARKER}; do not edit by hand (DEC-router-prompts-001). -->",
        "# Router de prompts por fase (proyeccion generada)",
        "",
        "> Lee esto ANTES de abrir un prompt: dice cual abrir en tu fase y cual NO (columna `NO es`).",
        "> Fuente: frontmatter `role` / `cycle_phase` / `route_kind` + `PROMPT-SUMMARY` de cada prompt.",
        "> Regenera con `python scripts/discover_skills.py --generate-index`; `--check-index` detecta deriva.",
        f"> Adoptados: {adopted} de {total}{exempt_note}. Los no adoptados aun NO aparecen"
        " aqui: si tu fase no esta, busca en `docs/registry/INDEX.md`.",
        "",
    ]


def _skill_cell(entry: dict[str, Any]) -> str:
    """D-S6: the pointer-skill's name as a table cell, or '-' if none."""
    skill = entry.get("skill")
    return f"`{skill}`" if skill else "-"


def _router_cycle_section(entry_prompts: list[dict[str, Any]]) -> list[str]:
    """'Ciclo por fase': one row per entry and phase, F5 fixed, loop defaults (D5)."""
    lines = [
        "## Ciclo por fase (abre UNO)",
        "",
        "| Fase | Rol | Abre | Skill | Cuando | NO es | Lineas | Bucle (`--phase` / `--task-type`) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for phase in CYCLE_PHASES:
        if phase == "F5-implementacion":
            lines.append(
                f"| {phase} | builder | (ninguno) | - | Tu contrato es el prompt que recibiste"
                " + `work_plan.md` | No abras `prompts/` para buscar | - | - |"
            )
            continue
        loop = PHASE_LOOP_PARAMS.get(phase)
        loop_cell = f"{loop[0]} / {loop[2]}{' (*)' if loop[3] else ''}" if loop else "-"
        lines.extend(
            f"| {phase} | {_cell(e['role'])} | `prompts/{e['rel']}` | {_skill_cell(e)}"
            f" | {_summary_cell(e, 'when')} | {_summary_cell(e, 'not')} | {e['lines']}"
            f" | {loop_cell} |"
            for e in entry_prompts
            if phase in e["phases"]
        )
    lines.append("")
    lines += [f"(*) {phase}: {p[3]}." for phase, p in PHASE_LOOP_PARAMS.items() if p[3]]
    lines += [
        "Revisar una propuesta sin commit: `DESIGN_REVIEW` / `prompt-audit` o `exploracion`"
        " (loop_id `EXPLORATORY-<tema>`, sin nonce).",
        "",
    ]
    return lines


def _router_standalone_skills_section(by_phase: dict[str, list[str]]) -> list[str]:
    """DEC-router-skills-001 D-S6: skills autocontenidas por fase.

    Autocontenidas (sin source_prompt) never appear in the prompt-driven
    tables above (those only scan prompts/); this section is their only
    entry point in ROUTER.md. Omitted entirely when there are none yet
    (the piloto only has 1: systematic-debugging).
    """
    if not by_phase:
        return []
    lines = ["## Skills autocontenidas por fase", ""]
    for phase in CYCLE_PHASES:
        names = by_phase.get(phase)
        if not names:
            continue
        lines.append(f"- **{phase}**: {', '.join(f'`{n}`' for n in names)}")
    lines.append("")
    return lines


def _router_table(title: str, header: str, rows: list[str]) -> list[str]:
    """A titled markdown table; omitted entirely when it has no rows."""
    if not rows:
        return []
    separator = "|" + "---|" * header.count(" | ") + "---|"
    return [title, "", header, separator, *rows, ""]


def _router_roles_section(entries: list[dict[str, Any]]) -> list[str]:
    """'Por rol': deterministic anchors (### Rol: <role>) for native-agent pointers."""
    lines = ["## Por rol", ""]
    for role in CANONICAL_ROLES:
        mine = sorted((e for e in entries if e["role"] == role), key=lambda e: e["rel"])
        if not mine:
            continue
        lines += [f"### Rol: {role}", ""]
        lines += [
            f"- `prompts/{e['rel']}` ({', '.join(e['phases']) if e['phases'] else e['kind']})"
            for e in mine
        ]
        lines.append("")
    return lines


def generate_router(bundle_root: Path | None = None) -> Path:
    """Write docs/registry/ROUTER.md from the live prompts. Returns its path."""
    root = bundle_root or _get_bundle_root()
    router_path = root / ROUTER_REL_PATH
    router_path.parent.mkdir(parents=True, exist_ok=True)
    # LF explicito, como generate_index (`*.md eol=lf` + hook --fix=lf).
    router_path.write_text(build_router(root), encoding="utf-8", newline="\n")
    return router_path


def check_router_stale(bundle_root: Path | None = None) -> tuple[bool, str]:
    """Check whether ROUTER.md matches the projection of the live prompts.

    Returns (is_stale, diagnostic): stale when missing or divergent.
    """
    root = bundle_root or _get_bundle_root()
    router_path = root / ROUTER_REL_PATH
    expected = build_router(root)
    if not router_path.exists():
        return True, f"{ROUTER_REL_PATH} does not exist; run --generate-index."
    if router_path.read_text(encoding="utf-8") != expected:
        return True, (
            f"{ROUTER_REL_PATH} is stale vs the live prompts (DEC-router-prompts-001). "
            "Regenerate with: python scripts/discover_skills.py --generate-index"
        )
    return False, ""


# --------------------------------------------------------------------------
# DEC-router-skills-001 D-S4: .claude/skills/<n>/SKILL.md stubs so Claude
# Code's native skill_listing can find a skill without duplicating its full
# source. Scoped to a `names` subset (the 4-skill pilot) so the generator can
# also be exercised against all 43 real skills WITHOUT committing that
# (tramo 3 PASO 1 pieza 3: "verificalo en el worktree, no lo commitees sobre
# las 43"). Canal: this stub is read ONLY by Claude Code's native listing;
# every other agent/channel keeps using ROUTER.md (D-S6).
# --------------------------------------------------------------------------

_SKILL_STUB_SUBDIR = Path(".claude") / "skills"


def _stub_names(bundle_root: Path, names: list[str] | None) -> list[str]:
    """Resolve which skill dir names to generate/check stubs for."""
    if names is not None:
        return list(names)
    skills_dir = bundle_root / "skills"
    if not skills_dir.exists():
        return []
    return sorted(
        p.name
        for p in skills_dir.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    )


def _build_skill_stub(skill_dir_name: str, fm: dict[str, Any]) -> str:
    """Render one stub's content: name + description + a one-line pointer."""
    skill_name = fm.get("name", skill_dir_name)
    description = fm.get("description", "")
    rel_skill_path = f"skills/{skill_dir_name}/SKILL.md"
    return (
        f"---\nname: {skill_name}\ndescription: {description}\n---\n\n"
        f"Lee `{rel_skill_path}`.\n"
    )


def generate_skill_stubs(
    bundle_root: Path | None = None,
    names: list[str] | None = None,
    stub_root: Path | None = None,
) -> list[Path]:
    """Write .claude/skills/<n>/SKILL.md stubs for the given skill names.

    Before: ``names`` is a subset of real skill-dir names (None = all real
            skills found under ``bundle_root/skills``, used to verify the
            generator at scale without committing the 43 stubs -- see
            module header). ``stub_root`` lets a test isolate WHERE stubs
            land (default: ``bundle_root/.claude/skills``) without touching
            the real ``skills/`` source.
    During: reads each real ``skills/<n>/SKILL.md`` frontmatter and writes a
            minimal stub (name + description + a `Lee skills/<n>/SKILL.md`
            pointer) with LF line endings, creating parent dirs as needed.
            A skill whose SKILL.md is missing or unparsable is skipped (not
            an error here; `--check-contract`/`validate_all.py` already
            guard the real SKILL.md).
    After: returns the list of stub paths written, in the same order as the
           resolved names.
    """
    root = bundle_root or _get_bundle_root()
    out_root = stub_root if stub_root is not None else root / _SKILL_STUB_SUBDIR
    written: list[Path] = []
    for skill_dir_name in _stub_names(root, names):
        skill_file = root / "skills" / skill_dir_name / "SKILL.md"
        if not skill_file.exists():
            continue
        fm, error = parse_frontmatter(skill_file)
        if error:
            continue
        stub_dir = out_root / skill_dir_name
        stub_dir.mkdir(parents=True, exist_ok=True)
        stub_path = stub_dir / "SKILL.md"
        stub_path.write_text(
            _build_skill_stub(skill_dir_name, fm), encoding="utf-8", newline="\n"
        )
        written.append(stub_path)
    return written


def check_skill_stubs_stale(
    bundle_root: Path | None = None,
    names: list[str] | None = None,
    stub_root: Path | None = None,
) -> tuple[bool, str]:
    """Check whether the stubs for ``names`` match their live SKILL.md source.

    Returns (is_stale, diagnostic): stale when any stub is missing or its
    rendered content diverges from what `generate_skill_stubs` would write
    today (name/description drift, e.g. the real SKILL.md changed its
    description and the stub was not regenerated).
    """
    root = bundle_root or _get_bundle_root()
    out_root = stub_root if stub_root is not None else root / _SKILL_STUB_SUBDIR
    stale: list[str] = []
    for skill_dir_name in _stub_names(root, names):
        skill_file = root / "skills" / skill_dir_name / "SKILL.md"
        if not skill_file.exists():
            continue
        fm, error = parse_frontmatter(skill_file)
        if error:
            continue
        expected = _build_skill_stub(skill_dir_name, fm)
        stub_path = out_root / skill_dir_name / "SKILL.md"
        if not stub_path.exists():
            stale.append(f"{skill_dir_name}: stub missing at {stub_path}")
            continue
        if stub_path.read_text(encoding="utf-8") != expected:
            stale.append(f"{skill_dir_name}: stub is stale vs live SKILL.md")
    if stale:
        return True, (
            "; ".join(stale)
            + ". Regenerate with: python scripts/discover_skills.py --generate-skill-stubs"
        )
    return False, ""


def _deployed_stub_names(bundle_root: Path) -> list[str]:
    """Names of skills that already have a stub on disk under .claude/skills/.

    Used as the CLI default scope for --check-skill-stubs/--generate-skill-
    stubs, so the gate only watches what has actually been deployed so far
    (the pilot's 4 skills today) instead of demanding all 43 have a stub
    before the batch rollout (a separate tramo, per DEC-router-skills-001).
    """
    stub_dir = bundle_root / _SKILL_STUB_SUBDIR
    if not stub_dir.exists():
        return []
    return sorted(
        p.name for p in stub_dir.iterdir() if p.is_dir() and (p / "SKILL.md").exists()
    )


def _generate_skill_stubs_cli() -> None:
    """CLI body of --generate-skill-stubs; always SystemExit (never returns).

    Default scope: only what is ALREADY deployed under .claude/skills/ (the
    pilot's subset today). --all-skills opts into generating the full 43 --
    reserved for the batch rollout tramo; never the default, so re-running
    this flag can never silently create new stubs beyond what was explicitly
    deployed (a real bug caught during the pilot, see test_discover_skills.
    TestGenerateSkillStubsCliScope).
    """
    root = _get_bundle_root()
    if "--all-skills" in sys.argv:
        names = None
    else:
        names = _deployed_stub_names(root)
        if not names:
            print(
                "[SKILL-STUBS] no stubs deployed yet under .claude/skills/; "
                "pass --all-skills to generate the full 43 (batch rollout only).",
                file=sys.stderr,
            )
            raise SystemExit(1)
    paths = generate_skill_stubs(root, names=names)
    for path in paths:
        print(f"[OK] Generated {path.relative_to(root)}")
    raise SystemExit(0)


def _check_index_cli() -> None:
    """CLI body of --check-index; always SystemExit (never returns).

    Covers INDEX.md, ROUTER.md (DEC-router-prompts-001) and, when any skill
    stub is deployed (D-S4), the stub/SKILL.md freshness gate -- scoped to
    what is deployed, never demanding all 43 before the batch rollout.
    """
    root = _get_bundle_root()
    failures = [
        f"[STALE] {diag}"
        for stale, diag in (check_index_stale(), check_router_stale())
        if stale
    ]
    failures += [f"[ROUTER] {error}" for error in router_metadata_errors()]
    deployed = _deployed_stub_names(root)
    if deployed:
        stub_stale, stub_diag = check_skill_stubs_stale(root, names=deployed)
        if stub_stale:
            failures.append(f"[SKILL-STUBS] {stub_diag}")
    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        raise SystemExit(1)
    print("[OK] INDEX.md is in sync with the live discovery catalog.")
    print("[OK] ROUTER.md is in sync with the live prompts.")
    if deployed:
        print(f"[OK] {len(deployed)} skill stub(s) in sync with their SKILL.md.")
    raise SystemExit(0)


def _dispatch_catalog_flags() -> None:
    """Handle the WOT-2026-008c catalog/index CLI flags; SystemExit if matched.

    --generate-index and --check-index cover BOTH projections: INDEX.md
    (catalog) and ROUTER.md (DEC-router-prompts-001), so the existing
    always-run pre-commit hook check-index-stale guards the router too.
    """
    if "--catalog" in sys.argv:
        print(json.dumps(build_catalog(), indent=2, ensure_ascii=False))
        raise SystemExit(0)

    if "--generate-index" in sys.argv:
        root = _get_bundle_root()
        metadata_errors = router_metadata_errors(root)
        if metadata_errors:
            for error in metadata_errors:
                print(f"[ROUTER] {error}", file=sys.stderr)
            print(
                "[ROUTER] invalid routing metadata; nothing generated.", file=sys.stderr
            )
            raise SystemExit(1)
        path = generate_index()
        router = generate_router()
        print(f"[OK] Generated {path.relative_to(root)}")
        print(f"[OK] Generated {router.relative_to(root)}")
        router_lines = len(router.read_text(encoding="utf-8").splitlines())
        if router_lines > ROUTER_MAX_LINES_WARN:
            print(
                f"[WARN] {ROUTER_REL_PATH} has {router_lines} lines "
                f"(> {ROUTER_MAX_LINES_WARN}); it is read before every prompt.",
                file=sys.stderr,
            )
        raise SystemExit(0)

    if "--generate-skill-stubs" in sys.argv:
        _generate_skill_stubs_cli()

    if "--check-index" in sys.argv:
        _check_index_cli()


def main() -> None:
    """CLI entry point."""

    if "--check-contract" in sys.argv:
        raise SystemExit(_check_contract())

    if "--check-naming" in sys.argv:
        raise SystemExit(_check_naming())

    _dispatch_catalog_flags()

    result = discover_skills()

    if "--json" in sys.argv:
        print(json.dumps(result, indent=2))
    else:
        print("\nSKILL DISCOVERY RESULTS\n")
        print(f"Total Skills: {result['total_skills']}")
        print(f"Total Triggers: {result['total_triggers']}\n")

        if result["skills"]:
            print("| Skill | Triggers | Version |")
            print("|-------|----------|---------|")
            for skill in result["skills"]:
                triggers_str = (
                    ", ".join(skill["triggers"]) if skill["triggers"] else "\u2014"
                )
                print(f"| {skill['name']} | {triggers_str} | {skill['version']} |")
        else:
            print("No skills found in skills/ directory")


if __name__ == "__main__":
    main()
