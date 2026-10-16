"""Barrier (WOT-2026-090v, hardened by WOT-2026-093g): no test may rewrite
files via git.

A test that mutates a tracked file and restores it with ``git checkout --`` /
``git restore`` destroys any uncommitted work in that file and, when aimed at
the real working tree, corrupts the repository under test. The sanctioned
technique is COPY-RESTORE (copy the file, mutate the copy, restore from the
copy), never git (see observation
``obs-mutation-verify-copy-restore-not-git-checkout``).

This module parses every *versioned* test file under ``tests/**/*.py`` with
:mod:`ast` and flags a destructive git argv wherever it is statically
constructed. Two scoping/pruning defences keep the scan on its real universe
(gitignored volatile subtrees and caches are pruned before walking; doctrine
WOT-2026-025w/013d) and skip files whose string literals cannot spell the
destructive subcommand (a sound over-approximate prefilter, see limitations):

- a list/tuple whose first element resolves to the constant ``"git"`` and whose
  subcommand resolves to ``"restore"`` (file-level by nature), or to
  ``"checkout"`` together with the ``"--"`` path separator;
- the same argv held in a variable for a later ``subprocess.*`` call;
- the same argv built by concatenation (``["git"] + args``) or by star
  unpacking (``["git", *args]``);
- the same argv produced by a helper DEFINED IN THE SAME FILE and returned
  (for example ``def _git(*a): return ["git", *a]``).

Branch operations are intentionally NOT flagged: ``git checkout --detach main``
and ``git checkout -b lateral`` do not rewrite working-tree files and are used
legitimately against repositories created inside ``tmp_path``.

Limitations (declared, not hidden):

- A git argv imported from ANOTHER module (``from helpers import _git``) is NOT
  covered: inlining a foreign module would require importing and executing it,
  which is out of scope for a static scan.
- A helper that EXECUTES the git argv instead of returning it (for example
  ``def _run(*a): subprocess.run(["git", *a])``) is NOT covered; only returning
  helpers are inlined.
- A command assembled from values that are not statically resolvable within
  the file (an argument from ``sys.argv``, ``os.system`` with a shell string,
  ``shlex.split``) is NOT covered.
- A construction is reported even if it is never executed: this is a guardrail
  against the concrete regression this ticket fixes, not a proof of absence.
- The prefilter is SOUND (it may parse extra files, never skip a real offender):
  it decodes the values of Python string literals with :func:`ast.literal_eval`
  — the same decoding :mod:`ast` applies to a ``Constant`` — and re-joins runs
  of adjacent literals (implicit concatenation), so every subcommand the scanner
  can resolve to ``restore``/``checkout`` has its text present in some decoded
  run. Splits (``"res" "tore"``), escapes (``"\\x72estore"``), comments and line
  continuations between adjacent literals are all covered.

Why not regex (WOT-2026-093g): the previous textual scan only saw the literal
form of the argv. It missed a variable git token, a variable argv, star
unpacking, concatenation and same-file helpers, and it false-positived on
docstrings that merely mention the argv.
"""

from __future__ import annotations

import ast
import io
import subprocess
import tokenize
from pathlib import Path

import pytest
from scripts.project_scanner import _safe_walk


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = PROJECT_ROOT / "tests"
_SELF = Path(__file__).resolve()

_GIT = "git"
_PATH_SEPARATOR = "--"
_RESTORE = "restore"
_CHECKOUT = "checkout"

# A destructive git argv can only be resolved from string constants; if no
# decoded string literal of the file spells one of these subcommands, the file
# cannot contain an offender. Over-approximate by construction (never skips a
# real one): the check only decides whether the expensive AST scan is worth it.
_DESTRUCTIVE_MARKERS = (_RESTORE, _CHECKOUT)
# Tokens that may appear BETWEEN adjacent string literals without breaking their
# implicit concatenation (whitespace-newlines and comments); treated as transparent.
_STRING_RUN_TRANSPARENT = frozenset(
    {
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.COMMENT,
        tokenize.INDENT,
        tokenize.DEDENT,
    }
)


class _Unknown:
    """Sentinel for an argv element that cannot be resolved statically."""

    def __repr__(self) -> str:
        return "<unknown>"


_UNKNOWN = _Unknown()


class _GitArgvScanner(ast.NodeVisitor):
    """Resolve statically constructed git argv and record destructive ones."""

    def __init__(self, source: str) -> None:
        self._source = source
        self._scopes: list[dict[str, ast.expr]] = []
        self._functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self._checked: set[int] = set()
        self.offenders: list[tuple[int, str]] = []

    def scan(self, tree: ast.AST) -> list[tuple[int, str]]:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._functions.setdefault(node.name, node)
        self._scopes.append({})
        try:
            for stmt in tree.body:
                self.visit(stmt)
        finally:
            self._scopes.pop()
        return self.offenders

    # -- scope tracking -------------------------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._scopes.append({})
        try:
            for stmt in node.body:
                self.visit(stmt)
        finally:
            self._scopes.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scopes.append({})
        try:
            for stmt in node.body:
                self.visit(stmt)
        finally:
            self._scopes.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            self._scopes[-1][node.targets[0].id] = node.value

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            if isinstance(node.target, ast.Name):
                self._scopes[-1][node.target.id] = node.value

    # -- candidate expressions -----------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        self._check(node)
        self.generic_visit(node)

    def visit_List(self, node: ast.List) -> None:
        self._check(node)
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        self._check(node)
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Add):
            self._check(node)
        self.generic_visit(node)

    # -- resolution -----------------------------------------------------
    def _check(self, node: ast.expr) -> None:
        if id(node) in self._checked:
            return
        self._checked.add(id(node))
        items = self._resolve_sequence(node, 0)
        if items is None or not self._is_destructive(items):
            return
        snippet = ast.get_source_segment(self._source, node) or ""
        self.offenders.append((node.lineno, snippet))

    def _lookup(self, name: str) -> ast.expr | None:
        for scope in reversed(self._scopes):
            if name in scope:
                return scope[name]
        return None

    def _resolve_sequence(
        self, node: ast.expr | None, depth: int
    ) -> list[object] | None:
        if node is None or depth > 8:
            return None
        if isinstance(node, (ast.List, ast.Tuple)):
            return self._flatten(node.elts, depth)
        if isinstance(node, ast.Starred):
            return self._resolve_sequence(node.value, depth + 1)
        if isinstance(node, ast.Name):
            return self._resolve_sequence(self._lookup(node.id), depth + 1)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._resolve_sequence(node.left, depth + 1)
            right = self._resolve_sequence(node.right, depth + 1)
            if left is None or right is None:
                return None
            return left + right
        if isinstance(node, ast.Call):
            return self._resolve_call(node, depth)
        return None

    def _flatten(self, elements: list[ast.expr], depth: int) -> list[object]:
        items: list[object] = []
        for element in elements:
            items.extend(self._flatten_element(element, depth))
        return items

    def _flatten_element(self, element: ast.expr, depth: int) -> list[object]:
        if isinstance(element, ast.Constant):
            return [element.value] if isinstance(element.value, str) else [_UNKNOWN]
        if isinstance(element, ast.Starred):
            inner = self._resolve_sequence(element.value, depth + 1)
            return inner if inner is not None else [_UNKNOWN]
        if isinstance(element, ast.Name):
            resolved = self._lookup(element.id)
            if isinstance(resolved, ast.Constant) and isinstance(resolved.value, str):
                return [resolved.value]
            inner = self._resolve_sequence(resolved, depth + 1)
            return inner if inner is not None else [_UNKNOWN]
        return [_UNKNOWN]

    def _resolve_call(self, node: ast.Call, depth: int) -> list[object] | None:
        if not isinstance(node.func, ast.Name):
            return None
        function = self._functions.get(node.func.id)
        if function is None:
            return None
        self._scopes.append(self._bind_arguments(function, node))
        try:
            for stmt in function.body:
                if isinstance(stmt, ast.Return) and stmt.value is not None:
                    resolved = self._resolve_sequence(stmt.value, depth + 1)
                    if resolved is not None:
                        return resolved
        finally:
            self._scopes.pop()
        return None

    @staticmethod
    def _bind_arguments(
        function: ast.FunctionDef | ast.AsyncFunctionDef,
        call: ast.Call,
    ) -> dict[str, ast.expr]:
        args = function.args
        positional = list(args.posonlyargs) + list(args.args)
        bindings: dict[str, ast.expr] = {}
        for index, parameter in enumerate(positional):
            if index < len(call.args):
                bindings[parameter.arg] = call.args[index]
        if args.vararg is not None:
            extra = list(call.args[len(positional) :])
            bindings[args.vararg.arg] = ast.Tuple(elts=extra, ctx=ast.Load())
        for keyword in call.keywords:
            if keyword.arg is not None:
                bindings[keyword.arg] = keyword.value
        return bindings

    @staticmethod
    def _is_destructive(items: list[object]) -> bool:
        if len(items) < 2 or items[0] != _GIT:
            return False
        subcommand = items[1]
        if subcommand == _RESTORE:
            return True
        if subcommand == _CHECKOUT:
            return _PATH_SEPARATOR in items
        return False


def _join_adjacent_string_literals(literals: list[str]) -> str:
    """Values of a run of adjacent string literals, concatenated (implicit join)."""
    parts: list[str] = []
    for literal in literals:
        try:
            value = ast.literal_eval(literal)
        except (ValueError, SyntaxError):
            value = ""
        parts.append(value if isinstance(value, str) else "")
    return "".join(parts)


def _decoded_string_runs(text: str) -> list[str]:
    """Every run of adjacent string literals in *text*, decoded to its value.

    Uses Python's own tokenizer so an escape (``"\\x72estore"``) or a split
    (``"res" "tore"``) are decoded EXACTLY as :mod:`ast` would when folding the
    literals into a ``Constant``. Returns a fallback ``[text]`` for a source the
    tokenizer cannot handle, which keeps the prefilter over-approximate.
    """
    runs: list[str] = []
    pending: list[str] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.STRING:
                pending.append(token.string)
            elif token.type in _STRING_RUN_TRANSPARENT:
                continue
            elif pending:
                runs.append(_join_adjacent_string_literals(pending))
                pending = []
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return [text]
    if pending:
        runs.append(_join_adjacent_string_literals(pending))
    return runs


def _could_contain_destructive_git(text: str) -> bool:
    """Cheap SOUND prefilter: False only when no literal can spell the subcommand.

    Before: *text* is the decoded source of one Python file.
    During: fast-paths on a raw substring hit (cheap), otherwise decodes the runs
        of adjacent string literals (see :func:`_decoded_string_runs`) and looks
        for the destructive markers.
    After: returns True if any decoded run contains ``restore``/``checkout``.
        It NEVER returns False for a file the AST scanner could flag (the scanner
        resolves the subcommand only from a string constant, whose value is one
        of those runs), so skipping the parse on False is safe.
    """
    if _RESTORE in text or _CHECKOUT in text:
        return True
    return any(
        marker in run
        for run in _decoded_string_runs(text)
        for marker in _DESTRUCTIVE_MARKERS
    )


def _scan_source(path: Path, text: str) -> list[tuple[Path, int, str]]:
    """AST scan of *text* with no prefilter (the reference used for equivalence)."""
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []
    scanner = _GitArgvScanner(text)
    return [(path, lineno, snippet) for lineno, snippet in scanner.scan(tree)]


def find_git_restore_offenders(files: list[Path]) -> list[tuple[Path, int, str]]:
    """Return ``(path, lineno, snippet)`` for each destructive git argv.

    Before: *files* is an explicit list of Python files (the caller can pass any
        set, e.g. a ``git show`` export of an older revision, for mutation
        verification).
    During: reads each file, applies the sound prefilter
        (:func:`_could_contain_destructive_git`) and parses only the survivors,
        resolving statically constructed git argv (see the module docstring).
    After: returns one tuple per offender (empty when none). Files that cannot
        be read or parsed are skipped; it never raises on them.
    """
    offenders: list[tuple[Path, int, str]] = []
    for raw_path in files:
        path = Path(raw_path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _could_contain_destructive_git(text):
            continue
        offenders.extend(_scan_source(path, text))
    return offenders


def _discover_test_files() -> list[Path]:
    """Every versioned ``tests/**/*.py`` file except this barrier itself.

    Walks with :func:`scripts.project_scanner._safe_walk` (doctrine
    WOT-2026-025w/013d), which PRUNES the gitignored volatile subtrees
    (``tests/sandbox/test_runtime``, caches, ``__pycache__``) before descending
    and tolerates concurrent deletes. The barrier's universe is versioned source,
    not the runtime files the suite generates under it.
    """
    return sorted(
        path
        for path in _safe_walk(PROJECT_ROOT)
        if path.suffix == ".py"
        and path.is_relative_to(TESTS_DIR)
        and path.resolve() != _SELF
    )


def test_no_test_rewrites_files_with_git() -> None:
    """No test file may invoke destructive ``git checkout``/``git restore``."""
    offenders = find_git_restore_offenders(_discover_test_files())
    assert offenders == [], (
        "Destructive git checkout/restore found in tests: use COPY-RESTORE "
        "instead (never aim git checkout/restore at a tracked file). "
        + "; ".join(
            f"{p.relative_to(PROJECT_ROOT)}:{n} -> {txt.strip()}"
            for p, n, txt in offenders
        )
    )


def _write_fixture(tmp_path: Path, name: str, code: str) -> Path:
    fixture = tmp_path / name
    fixture.write_text(code, encoding="utf-8")
    return fixture


def test_barrier_flags_path_checkout(tmp_path: Path) -> None:
    """Positive control: the literal path form still has teeth."""
    fixture = _write_fixture(
        tmp_path,
        "test_offender.py",
        'subprocess.run(["git", "checkout", "--", str(RUNNER_PATH)])\n',
    )
    assert find_git_restore_offenders([fixture]), (
        "barrier must flag git checkout -- <path>"
    )


def test_barrier_flags_any_restore(tmp_path: Path) -> None:
    """Positive control: ``git restore`` is file-level by nature -> flagged."""
    fixture = _write_fixture(
        tmp_path,
        "test_offender_restore.py",
        'subprocess.run(["git", "restore", "--", str(RUNNER_PATH)])\n',
    )
    assert find_git_restore_offenders([fixture]), "barrier must flag git restore"


def test_barrier_allows_branch_checkout(tmp_path: Path) -> None:
    """Negative control: branch operations in a tmp repo are legitimate."""
    fixture = _write_fixture(
        tmp_path,
        "test_branch_ops.py",
        'subprocess.run(["git", "checkout", "--detach", "main"])\n'
        'subprocess.run(["git", "checkout", "-b", "lateral"])\n'
        'subprocess.run(["git", "checkout", "main"])\n',
    )
    offenders = find_git_restore_offenders([fixture])
    assert offenders == [], (
        f"branch operations must not be flagged as destructive restores: {offenders}"
    )


def test_barrier_flags_git_token_and_argv_via_variable(tmp_path: Path) -> None:
    """Form 1 (WOT-2026-093g): git token and argv both held in variables."""
    fixture = _write_fixture(
        tmp_path,
        "test_offender_variable.py",
        'GIT = "git"\n'
        'cmd = [GIT, "restore", "--", str(RUNNER_PATH)]\n'
        "subprocess.run(cmd)\n",
    )
    assert find_git_restore_offenders([fixture]), (
        "barrier must flag git/argv held in variables"
    )


def test_barrier_flags_star_unpacking(tmp_path: Path) -> None:
    """Form 2 (WOT-2026-093g): ``["git", *args]`` with resolvable args."""
    fixture = _write_fixture(
        tmp_path,
        "test_offender_star.py",
        'args = ["restore", "--", str(RUNNER_PATH)]\nsubprocess.run(["git", *args])\n',
    )
    assert find_git_restore_offenders([fixture]), (
        "barrier must flag star-unpacked git argv"
    )


def test_barrier_flags_concatenation(tmp_path: Path) -> None:
    """Form 3 (WOT-2026-093g): ``["git"] + args`` built by concatenation."""
    fixture = _write_fixture(
        tmp_path,
        "test_offender_concat.py",
        'args = ["restore", "--", str(RUNNER_PATH)]\n'
        'cmd = ["git"] + args\n'
        "subprocess.run(cmd)\n",
    )
    assert find_git_restore_offenders([fixture]), (
        "barrier must flag concatenated git argv"
    )


def test_barrier_flags_same_file_helper(tmp_path: Path) -> None:
    """Form 4 (WOT-2026-093g): same-file helper returns the git argv."""
    fixture = _write_fixture(
        tmp_path,
        "test_offender_helper.py",
        "def _git(*a):\n"
        '    return ["git", *a]\n'
        "\n"
        'subprocess.run(_git("restore", "--", str(RUNNER_PATH)))\n',
    )
    assert find_git_restore_offenders([fixture]), (
        "barrier must flag same-file git helper"
    )


def test_barrier_ignores_docstring_mention(tmp_path: Path) -> None:
    """No false positive from a docstring that merely mentions the argv."""
    fixture = _write_fixture(
        tmp_path,
        "test_docstring_only.py",
        '"""Example of the bad pattern: subprocess.run(["git", "restore", "f"])."""\n'
        "VALUE = 1\n",
    )
    offenders = find_git_restore_offenders([fixture])
    assert offenders == [], f"a docstring mention is not code: {offenders}"


# --- pilot A guards (WOT-2026-... suite optimization) -----------------------
#
# The scope/pruning fix and the prefilter must NOT weaken the barrier. These
# adversarial forms are the exact regressions the ensemble round found: a
# subcommand split across adjacent literals or written with escapes is folded
# to the SAME ``Constant`` by :mod:`ast`, so the AST scanner flags them today;
# the prefilter must keep flagging them.

_ADVERSARIAL_SUBCOMMAND_FORMS: list[tuple[str, str]] = [
    ("split_restore", 'X = ["git", "res" "tore", "f"]\n'),
    ("escape_hex_restore", 'X = ["git", "\\x72estore", "f"]\n'),
    ("escape_octal_restore", 'X = ["git", "\\162estore", "f"]\n'),
    ("escape_unicode4_restore", 'X = ["git", "\\u0072estore", "f"]\n'),
    ("escape_unicode8_restore", 'X = ["git", "\\U00000072estore", "f"]\n'),
    ("split_checkout", 'X = ["git", "check" "out", "--", "f"]\n'),
    ("escape_hex_checkout", 'X = ["git", "\\x63heckout", "--", "f"]\n'),
    ("continuation_split", 'X = ["git", "res\\\ntore", "f"]\n'),
    (
        "comment_split",
        'X = [\n    "git",\n    "res"  # note\n    "tore",\n    "f",\n]\n',
    ),
]


@pytest.mark.parametrize(
    ("name", "source"),
    _ADVERSARIAL_SUBCOMMAND_FORMS,
    ids=[name for name, _ in _ADVERSARIAL_SUBCOMMAND_FORMS],
)
def test_prefilter_keeps_obfuscated_subcommands(
    tmp_path: Path, name: str, source: str
) -> None:
    """An obfuscated destructive argv must survive the prefilter and stay flagged."""
    fixture = _write_fixture(tmp_path, f"test_{name}.py", source)
    assert _could_contain_destructive_git(source), f"prefilter dropped {name}"
    assert find_git_restore_offenders([fixture]), f"barrier must still flag {name}"


def test_discover_keeps_every_versioned_test_file() -> None:
    """The scope/pruning fix must not drop any git-versioned ``tests/**/*.py``."""
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "ls-files", "-z", "--", "tests"],
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = {
        (PROJECT_ROOT / rel).resolve()
        for rel in result.stdout.split("\0")
        if rel.endswith(".py")
    }
    tracked.discard(_SELF)
    discovered = {path.resolve() for path in _discover_test_files()}
    missing = sorted(tracked - discovered)
    assert missing == [], f"versioned test files dropped from the barrier: {missing}"


def test_prefilter_equivalence_over_real_corpus(tmp_path: Path) -> None:
    """The prefilter must not drop an offender the reference scan would find.

    Equivalence form that stays cheap: for every real test file the prefilter
    SKIPS, the reference AST scan must find nothing (the files it KEEPS are
    scanned by the production path anyway). A synthetic OBFUSCATED offender is
    exercised end-to-end so the assertion has teeth: the prefilter must keep it
    and the full pipeline must still catch it.
    """
    offender = _write_fixture(
        tmp_path,
        "test_synthetic_obfuscated_offender.py",
        'X = ["git", "res" "tore", "f"]\n',
    )
    corpus = _discover_test_files()
    leaks: list[Path] = []
    for path in corpus:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _could_contain_destructive_git(text):
            continue
        if _scan_source(path, text):
            leaks.append(path)
    assert leaks == [], f"prefilter skipped files the reference scan flags: {leaks}"
    assert find_git_restore_offenders([offender]), (
        "the synthetic obfuscated offender must survive the full pipeline"
    )
