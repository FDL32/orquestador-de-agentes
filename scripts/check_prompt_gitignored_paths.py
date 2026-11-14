"""Audit executable paths cited by canonical prompts against git-ignored files.

Before: The motor contains canonical Markdown prompts and may contain ignored
destination paths in their examples or operational instructions.
During: Extract inline-code and fenced-code citations, classify program-shaped
paths using their execution context, and resolve candidates in one
``git check-ignore --no-index -v -z --stdin`` batch.
After: Always publish the denominator, citation classes, and method. Existing
executable debt born on or before the fixed introduction cutoff is WARN-only;
new or unmeasurable executable debt fails closed.

Only ``prompts/`` is measured. ``skills/`` and AGENTS.md are proposed future
surfaces, not part of this denominator. EXEC examples include ``python
ignored/tool.py --flag``, ``ignored/tool.py --flag``, ``ejecuta ignored/tool.py``
and ``via ignored/tool.py``. Historical/illustrative markers (``legacy``,
``ejemplo``, ``was``, ``no longer``) are ILLUS. Prohibitions, data/output/read
paths, ``--report`` paths, and neutral mentions are MENTION, even when their
suffix is ``.py``. This deliberately does not infer shell syntax beyond the
listed forms. The real-tree inventory depends on local state: a generated venv
``.gitignore`` containing ``*`` ignores ``.venv/Scripts/python.exe``. That is
the only known EXEC there and is a benign grandfathered WARN false positive.
Proposal (not implemented here): exclude venv interpreters from the denominator.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


_INTRO_CUTOFF_DATE = _datetime.date(2026, 11, 14)
_PROGRAM_SUFFIXES = (".py", ".sh", ".ps1", ".bat", ".cmd", ".exe")
_ROLE_PREFIXES = (
    "<workspace>/",
    "<repo_destino>/",
    "<destino>/",
    "<DESTINO_ROOT>/",
    "repo_destino/",
    "workspace/",
)
_EXEC_VERBS = re.compile(
    r"\b(?:ejecuta|invoca|lanza|corre|usa|llama|run|execute|invoke|call)\b",
    re.IGNORECASE,
)
_VIA = re.compile(r"\b(?:via|mediante|a\s+traves\s+de|through)\b", re.IGNORECASE)
_ILLUS = re.compile(
    r"\b(?:ejemplo|por\s+ejemplo|e\.g\.|ilustrativo|historico|legacy|obsoleto|"
    r"retirado|deprecado|ya\s+no|no\s+longer|used\s+to|was)\b",
    re.IGNORECASE,
)
_DATA_CONTEXT = re.compile(
    r"\b(?:escribe|guarda|genera|lee|informe|salida|output|read|write|save|"
    r"generate)\b|--report\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Citation:
    prompt: str
    line: int
    text: str
    route: str
    span: str = ""
    ignored: bool = False
    pattern: str = ""
    source: str = ""


def _run(
    root: Path, args: list[str], *, input_data: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run a git command in root and preserve its literal return code."""

    try:
        return subprocess.run(  # noqa: S603 - argv is built from fixed git subcommands
            ["git", *args],  # noqa: S607 - git is the required repository executable
            cwd=root,
            input=input_data,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"git unavailable: {exc}") from exc


def _git_prompts(root: Path) -> list[str]:
    """Return the tracked Markdown prompt denominator, or fail closed."""

    result = _run(root, ["ls-files", "--", "prompts"])
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed rc={result.returncode}")
    prompts = [
        line.decode("utf-8", "replace")
        for line in result.stdout.splitlines()
        if line.endswith(b".md")
    ]
    if not prompts:
        raise RuntimeError("denominator is empty: 0 prompts read")
    return prompts


def _route_tokens(text: str) -> list[str]:
    """Extract route-shaped tokens while retaining punctuation-free spans."""

    tokens = re.findall(r'(?<![\w./-])(?:<[^>\s]+>/)?[^\s`"\']+', text)
    return [
        token.rstrip(",.;:)]}")
        for token in tokens
        if token.lower().endswith(_PROGRAM_SUFFIXES)
    ]


def _normalize(route: str) -> str | None:
    """Normalize role prefixes and reject paths unsafe for check-ignore stdin."""

    route = route.strip().strip("`\"'()[]{}")
    for prefix in _ROLE_PREFIXES:
        if route.startswith(prefix):
            route = route[len(prefix) :]
            break
    if (
        not route
        or route.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", route)
    ):
        return None
    parts = route.replace("\\", "/").split("/")
    if ".." in parts:
        return None
    return "/".join(part for part in parts if part and part != ".")


def _extract(root: Path, prompts: list[str]) -> list[Citation]:
    """Extract inline and fenced citations with source line numbers."""

    citations: list[Citation] = []
    for prompt in prompts:
        try:
            lines = (root / prompt).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"cannot read prompt {prompt}: {exc}") from exc
        fenced = False
        for number, line in enumerate(lines, 1):
            if line.strip().startswith("```"):
                fenced = not fenced
                continue
            spans = re.findall(r"`([^`]+)`", line)
            if fenced:
                spans.append(line)
            for span in spans:
                for route in _route_tokens(span):
                    normalized = _normalize(route)
                    if normalized:
                        citations.append(
                            Citation(prompt, number, line, normalized, span)
                        )
    return citations


def _ignored(root: Path, citations: list[Citation]) -> dict[str, tuple[str, str]]:
    """Resolve all safe unique candidates through one check-ignore batch."""

    routes = sorted({citation.route for citation in citations})
    if not routes:
        return {}
    payload = b"".join(route.encode() + b"\0" for route in routes)
    result = _run(
        root,
        ["check-ignore", "--no-index", "-v", "-z", "--stdin"],
        input_data=payload,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"git check-ignore failed rc={result.returncode}")
    fields = result.stdout.split(b"\0")
    matches: dict[str, tuple[str, str]] = {}
    for index in range(0, len(fields) - 3, 4):
        source, _line, pattern, route = (
            field.decode("utf-8", "replace") for field in fields[index : index + 4]
        )
        if not route or pattern.startswith("!"):
            continue
        matches[route] = (pattern, source)
    return matches


def _classify(citation: Citation) -> str:
    """Classify an ignored citation as EXEC, ILLUS, or MENTION."""

    context = citation.text.replace("\\", "/")
    span = citation.span.replace("\\", "/")
    for prefix in _ROLE_PREFIXES:
        context = context.replace(prefix, "")
        span = span.replace(prefix, "")
    lower = context.lower()
    if _ILLUS.search(context):
        return "ILLUS"
    if lower.startswith(
        ("no ", "don't ", "do not ", "prohibido ")
    ) or _DATA_CONTEXT.search(context):
        return "MENTION"
    route = re.escape(citation.route)
    execution_context = f"{context}\n{span}"
    has_launcher = re.search(
        r"\b(?:python|python3|uv\s+run\s+python|bash|sh|pwsh|cmd)\b",
        execution_context,
        re.I,
    ) and re.search(route, execution_context, re.I)
    starts_route = re.search(
        rf"(?:^|[\s`\"'(]){route}(?:\s+--|[\s`\"'.,:;)]*$)",
        span,
        re.I,
    )
    verb_object = _EXEC_VERBS.search(context) and re.search(route, context, re.I)
    via_object = _VIA.search(context) and re.search(route, context, re.I)
    return (
        "EXEC"
        if has_launcher or starts_route or verb_object or via_object
        else "MENTION"
    )


def _blame_date(root: Path, citation: Citation) -> _datetime.date:
    """Read the author date for one prompt line, failing closed on any gap."""

    head = _run(root, ["show", f"HEAD:{citation.prompt}"])
    if head.returncode != 0:
        raise RuntimeError(
            f"prompt line is not present in HEAD: {citation.prompt}:{citation.line}"
        )
    head_lines = head.stdout.decode("utf-8", "replace").splitlines()
    if (
        citation.line > len(head_lines)
        or head_lines[citation.line - 1] != citation.text
    ):
        raise RuntimeError(
            f"prompt line is not present in HEAD: {citation.prompt}:{citation.line}"
        )
    result = _run(
        root,
        [
            "blame",
            "--line-porcelain",
            "HEAD",
            "-L",
            f"{citation.line},{citation.line}",
            "--",
            citation.prompt,
        ],
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"blame failed for {citation.prompt}:{citation.line} rc={result.returncode}"
        )
    header = result.stdout.splitlines()[0] if result.stdout.splitlines() else b""
    sha = header.split(maxsplit=1)[0] if header else b""
    if not re.fullmatch(rb"[0-9a-f]{40}", sha) or sha == b"0" * 40:
        raise RuntimeError(
            f"blame has no committed revision for {citation.prompt}:{citation.line}"
        )
    match = re.search(rb"^author-time (\d+)$", result.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError(
            f"blame has no author-time for {citation.prompt}:{citation.line}"
        )
    return _datetime.datetime.fromtimestamp(
        int(match.group(1)), _datetime.timezone.utc
    ).date()


def main(argv: list[str] | None = None) -> int:  # noqa: C901 - CLI orchestration and reporting
    """Audit prompts and return zero only for clean or grandfathered findings."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--motor-root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--inventory", type=Path)
    args = parser.parse_args(argv)
    root = args.motor_root.resolve()
    try:
        prompts = _git_prompts(root)
        citations = _extract(root, prompts)
        ignored = _ignored(root, citations)
    except RuntimeError as exc:
        print(f"[prompt-gitignored] ERROR: {exc}")
        return 1
    unique_citations = list(
        {(c.prompt, c.line, c.route): c for c in citations}.values()
    )
    annotated = [
        Citation(
            c.prompt,
            c.line,
            c.text,
            c.route,
            c.span,
            c.route in ignored,
            *(ignored.get(c.route, ("", ""))),
        )
        for c in unique_citations
    ]
    classes = {name: 0 for name in ("EXEC", "ILLUS", "MENTION")}
    errors: list[str] = []
    inventory_lines: list[str] = []
    for citation in annotated:
        kind = _classify(citation) if citation.ignored else "-"
        if citation.ignored:
            classes[kind] += 1
        inventory_lines.append(
            f"{'IGNORED' if citation.ignored else '-'} {kind} "
            f"{citation.prompt}:{citation.line}:{citation.route}"
        )
        if kind == "EXEC":
            try:
                birth = _blame_date(root, citation)
            except RuntimeError as exc:
                errors.append(
                    f"{citation.prompt}:{citation.line}:{citation.route} ({exc})"
                )
                continue
            if birth <= _INTRO_CUTOFF_DATE:
                print(
                    f"WARN {citation.prompt}:{citation.line}:{citation.route} (born {birth.isoformat()})"
                )
            else:
                errors.append(
                    f"{citation.prompt}:{citation.line}:{citation.route} (born {birth.isoformat()})"
                )
    print(
        f"[prompt-gitignored] denominator: {len(prompts)} prompts; citations: {len(unique_citations)}; "
        f"ignored_routes(unique)={len(ignored)}; "
        f"ignored_citations={sum(c.ignored for c in annotated)}; "
        f"classes over ignored citations EXEC={classes['EXEC']} "
        f"ILLUS={classes['ILLUS']} MENTION={classes['MENTION']}"
    )
    print(
        "[prompt-gitignored] method: git ls-files prompts (*.md), inline/fenced code citations, one git check-ignore --no-index -v -z --stdin batch"
    )
    if args.inventory:
        try:
            args.inventory.write_text(
                "\n".join(inventory_lines) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            print(f"[prompt-gitignored] ERROR: inventory write failed: {exc}")
            return 1
    if errors:
        print("[prompt-gitignored] ERROR: executable ignored prompt path(s):")
        for error in errors:
            print(f"  {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
