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


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str | None]:
    """Parse YAML frontmatter from a markdown file.

    Returns (data, error) where:
      - error is None: valid frontmatter parsed
      - error == "NO_FRONTMATTER": file has no frontmatter block
      - error is a string: YAML parsing error description
      - data is empty dict on any error
    """
    try:
        with open(path, encoding="utf-8-sig") as f:
            content = f.read()
    except Exception as e:
        return {}, f"IO_ERROR: {e}"

    if not content.startswith("---"):
        return {}, "NO_FRONTMATTER"

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, "NO_FRONTMATTER"

    fm_text = parts[1].strip()
    if not fm_text:
        return {}, "NO_FRONTMATTER"

    yaml_error = _validate_yaml(fm_text)
    if yaml_error:
        return {}, yaml_error

    return _parse_fm_lines(fm_text), None


def _scan_skills_dir(directory: Path | None) -> dict[str, dict[str, Any]]:
    discovered = {}
    if not directory or not directory.exists() or not directory.is_dir():
        return discovered
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

    bundle_skills = _scan_skills_dir(skills_dir)
    host_skills = _scan_skills_dir(host_skills_dir)

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
CONTRACT_OPT_IN_ROLES = ("manager", "builder", "auditor")


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
    During: validates every prompts/*.md stem against snake_case and every
            skills/<dir> name against kebab-case (DEC-008D-001). Directories
            starting with "_" (e.g. _shared) and non-.md files are skipped.
            Names in KNOWN_LEGACY_NAMES are tolerated (declared legacy debt).
    After: returns a list of human-readable violation strings (empty == clean).
           No side effects, no I/O beyond directory listing.
    """
    if bundle_root is None:
        bundle_root = _get_bundle_root()
    return _check_prompt_names(bundle_root / "prompts") + _check_skill_names(
        bundle_root / "skills"
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
    discovered = _scan_skills_dir(root / "skills")
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
    entries += [
        _catalog_entry(
            "prompt", p, root, status=_derive_status(parse_frontmatter(p)[0])
        )
        for p in sorted((root / "prompts").glob("*.md"))
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
    index_path.write_text(render_index(catalog), encoding="utf-8")
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


def _dispatch_catalog_flags() -> None:
    """Handle the WOT-2026-008c catalog/index CLI flags; SystemExit if matched."""
    if "--catalog" in sys.argv:
        print(json.dumps(build_catalog(), indent=2, ensure_ascii=False))
        raise SystemExit(0)

    if "--generate-index" in sys.argv:
        path = generate_index()
        print(f"[OK] Generated {path.relative_to(_get_bundle_root())}")
        raise SystemExit(0)

    if "--check-index" in sys.argv:
        is_stale, diag = check_index_stale()
        if is_stale:
            print(f"[STALE] {diag}", file=sys.stderr)
            raise SystemExit(1)
        print("[OK] INDEX.md is in sync with the live discovery catalog.")
        raise SystemExit(0)


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
