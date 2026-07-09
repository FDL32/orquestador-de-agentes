from __future__ import annotations

import json
import re
import statistics
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / ".agent"

TEXT_EXTENSIONS = frozenset(
    {
        ".md",
        ".py",
        ".json",
        ".jsonl",
        ".toml",
        ".yaml",
        ".yml",
        ".sh",
        ".ps1",
        ".txt",
        ".xml",
    }
)

SUSPICIOUS_CODEPOINTS = {
    0x00C3,
    0x00C2,
    0x00E2,
    0x00F0,
    0x0102,
    0xFFFD,
}

# CTL-2026-012j (Check 1): de-acentuacion lossy detection. De-accented Spanish
# (sin tildes) is valid ASCII and passes the byte-level guard (false green of
# CTL-2026-012h); this layer flags de-accented blocks inside a document that
# otherwise uses accents. Only Spanish acute accent + diaeresis + n-tilde; NOT
# other languages' diacritics (e.g. grave a/egrave). Follows the frozenset
# convention of SUSPICIOUS_CODEPOINTS / TEXT_EXTENSIONS.
ACCENTED_CHARS = frozenset("áéíóúüñÁÉÍÓÚÜÑ")

# De-acentuacion only applies to prose; code/config (.py/.json/.toml/.jsonl/
# .yaml/.yml/.sh/.ps1) legitimately lacks accents and is excluded. The caller
# (file_issues) filters by suffix before invoking find_deaccentuation_lossy.
DEACCENT_PROSE_EXTENSIONS = frozenset({".md", ".html", ".txt", ".xml"})

# Fixed-line windows (no HTML/markdown parsing): simpler, more robust, avoids
# false positives from parse errors.
DEACCENT_BLOCK_LINES = 50

# Minimum characters per block to avoid noise in short blocks.
DEACCENT_MIN_BLOCK_CHARS = 200

# A document is only checked when its own accent baseline is significant.
# Measured on real destino/motor prose (execution_log CTL-2026-012j): the
# highest false-positive file median was 0.01333 (a changelog with code blocks);
# 0.015 excludes all measured false positives with margin while keeping genuine
# accented prose (>= ~0.019) under the check.
DEACCENT_BASELINE_MIN = 0.015

# A block is suspect when its accent ratio falls below 10% of the document
# baseline. Measured: the lightest real accented block sits at ~40% of its
# baseline, so 10% gives ~4x margin against false positives while flagging
# de-accented blocks (ratio ~0). Matches the contract's initial 10% value.
DEACCENT_RATIO_THRESHOLD = 0.10

STATIC_FILES_TO_CHECK = [
    AGENT_DIR / "agent_controller.py",
    AGENT_DIR / "completion_checker.py",
    ROOT / "scripts" / "update_project_map.py",
    AGENT_DIR / "README.md",
    AGENT_DIR / "hooks" / "stop_hook.py",
    AGENT_DIR / "completion_common.py",
    AGENT_DIR / "collaboration" / "work_plan.md",
    AGENT_DIR / "collaboration" / "execution_log.md",
    AGENT_DIR / "collaboration" / "notifications.md",
    AGENT_DIR / "collaboration" / "TURN.md",
    AGENT_DIR / "workflows" / "manager_workflow.md",
    AGENT_DIR / "workflows" / "builder_workflow.md",
    AGENT_DIR / "templates" / "LEGACY_NOTE.md",
    AGENT_DIR / "templates" / "work_plan_template.md",
    AGENT_DIR / "templates" / "findings_template.md",
    AGENT_DIR / "templates" / "PRIVATE_REGISTRY.md",
    AGENT_DIR / "templates" / "work_plan_example_v2.md",
    AGENT_DIR / "legacy" / "LEGACY_NOTE.md",
    AGENT_DIR / "legacy" / "manager_workflow.md",
    AGENT_DIR / "legacy" / "builder_workflow.md",
    AGENT_DIR / "legacy" / "MANAGER_SKILLS.md",
    AGENT_DIR / "legacy" / "BUILDER_SKILLS.md",
    AGENT_DIR / "legacy" / "MANAGER_CONTEXT.md",
    AGENT_DIR / "legacy" / "BUILDER_CONTEXT.md",
]

GLOB_PATTERNS = [
    "skills/**/*.md",
    "prompts/**/*.md",
    "scripts/**/*.py",
    # WOT-2026-011f: bring real PowerShell sources under the repo-wide guard so
    # BOM/mojibake in .ps1 is caught (the launcher carried both pre-011f).
    "scripts/**/*.ps1",
    ".claude/**/*.md",
    "runtime/**/*.py",
    "bus/**/*.py",
    ".agent/**/*.py",
    "*.md",
]

EXCLUDE_PATTERNS = {
    "scripts/sandbox/**",
    ".agent/backups/**",
    ".agent/runtime/uv-cache/**",
}

ALLOWLIST = {}


def relative_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def find_mojibake(text: str) -> list[str]:
    snippets: list[str] = []
    for idx, ch in enumerate(text):
        if ord(ch) not in SUSPICIOUS_CODEPOINTS:
            continue
        snippet = text[idx : idx + 4]
        if snippet not in snippets:
            snippets.append(snippet)
    return snippets


def find_q_in_word(text: str) -> list[str]:
    matches: list[str] = []
    for idx, ch in enumerate(text[1:-1], start=1):
        if ch != "?":
            continue
        prev_char = text[idx - 1]
        next_char = text[idx + 1]
        if prev_char.isalpha() and next_char.isalpha():
            snippet = text[idx - 1 : idx + 2]
            if snippet not in matches:
                matches.append(snippet)
    return matches


# ASCII control chars (<32) that are legitimate in text files: tab, line feed,
# carriage return. Everything else below 0x20 (e.g. 0x00 NUL, 0x07 BEL, 0x0B VT,
# 0x0C FF) is corruption — the class that slipped past the guard in WOT-2026-008f
# and 008j because the guard only inspected codepoints >127 (mojibake/BOM).
_ALLOWED_CONTROL_CHARS = frozenset({"\t", "\n", "\r"})


def find_control_chars(text: str) -> list[str]:
    """Return snippets around disallowed ASCII control chars (<32, not tab/LF/CR).

    Each snippet shows the control char as ``<0xNN>`` with up to 3 chars of
    following context, deduplicated, so the report is human-readable. CRLF is
    fine because both \\r and \\n are allowed.
    """
    snippets: list[str] = []
    for idx, ch in enumerate(text):
        if ord(ch) >= 32 or ch in _ALLOWED_CONTROL_CHARS:
            continue
        marker = f"<0x{ord(ch):02X}>"
        tail = text[idx + 1 : idx + 4].replace("\n", "\\n").replace("\r", "\\r")
        snippet = marker + tail
        if snippet not in snippets:
            snippets.append(snippet)
    return snippets


# WOT-2026-013q: the broken-backtick fragment is the same heredoc/PowerShell
# escape-literalization that produced `r (from \r) in CTL-2026-007a; the very
# same mechanism emits `n (from \n) and `t (from \t) at the end of a path
# bullet. Match the [rnt] family, EOL-anchored and path-shaped, so legitimate
# inline-code bullets (e.g. ``- use `ruff` ``) never false-positive.
_BROKEN_PATH_BULLET_RE = re.compile(r"^[./A-Za-z0-9_-]+(?:/[./A-Za-z0-9_-]+)*/`[rnt]$")


def find_path_bullet_mangling(text: str) -> list[str]:
    """Return narrow signatures of markdown path-bullet corruption.

    This catches the signatures from the CTL-2026-007a incident:

    - a literal tab immediately after the bullet marker (`- <TAB>path`)
    - a broken backtick fragment at the end of a path bullet from heredoc
      escape literalization: ``- src/pipeline/`r`` and its same-mechanism
      siblings ``/`n`` and ``/`t``.

    The detector is intentionally narrow so legitimate tabs elsewhere in the
    file (for example, markdown tables) and inline-code bullets remain allowed.
    """
    snippets: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        if not stripped.startswith("- "):
            continue

        body = stripped[2:]
        if body.startswith("\t"):
            snippet = "<bullet-tab>" + body[:12].replace("\t", "<TAB>")
            if snippet not in snippets:
                snippets.append(snippet)

        if _BROKEN_PATH_BULLET_RE.fullmatch(body):
            snippet = body[-16:]
            if snippet not in snippets:
                snippets.append(snippet)
    return snippets


def find_c1_controls(text: str) -> list[str]:
    """Return snippets around C1 control codepoints (U+0080-U+009F) in decoded text.

    WOT-2026-014d: C1 control characters are a distinct class from ASCII controls
    (<32) and mojibake.  They are valid UTF-8 multibyte sequences so
    ``content.decode('utf-8', errors='strict')`` does NOT flag them, yet they
    indicate encoding corruption (typically CP1252-mismapped markers that were
    stored as raw C1 bytes and re-read as UTF-8).  A separate check is required.

    Each snippet shows the codepoint as ``<U+NNNN>`` with up to 3 chars of
    following context, deduplicated for human readability.
    """
    snippets: list[str] = []
    for idx, ch in enumerate(text):
        if not (0x0080 <= ord(ch) <= 0x009F):
            continue
        marker = f"<U+{ord(ch):04X}>"
        tail = text[idx + 1 : idx + 4].replace("\n", "\\n").replace("\r", "\\r")
        snippet = marker + tail
        if snippet not in snippets:
            snippets.append(snippet)
    return snippets


def check_utf8_strict(path: Path) -> list[str]:
    """Return a single-element list if the file has invalid UTF-8 byte sequences.

    WOT-2026-014d: complementary layer for the C1 check.  ``find_c1_controls``
    catches valid-UTF-8-but-wrong-class codepoints; this function catches a
    different class: raw byte sequences that are NOT valid UTF-8 at all (e.g.
    lone continuation bytes, overlong sequences).

    Returns an empty list on clean files so the caller can use a uniform
    ``if snippets`` test.
    """
    raw = path.read_bytes()
    try:
        raw.decode("utf-8", errors="strict")
        return []
    except UnicodeDecodeError as exc:
        return [f"<invalid-utf8:{exc.start:#04x}:{exc.reason}>"]


def find_text_corruption(text: str) -> list[str]:
    """Return non-mojibake structural corruption snippets for a text file."""
    findings: list[str] = []
    for snippet in [
        *find_control_chars(text),
        *find_path_bullet_mangling(text),
        *find_c1_controls(text),
    ]:
        if snippet not in findings:
            findings.append(snippet)
    return findings


def find_deaccentuation_lossy(text: str) -> list[str]:
    """Return snippets for blocks that lost Spanish accents vs the doc baseline.

    CTL-2026-012j (Check 1): detects de-accented blocks (Spanish without tildes,
    which is valid ASCII and passes the byte-level guard) inside a document that
    otherwise uses accents. Splits the text into fixed windows of
    ``DEACCENT_BLOCK_LINES`` lines, computes ``accent_ratio = accented / alpha``
    per block, takes the document baseline as the median of valid blocks
    (>= ``DEACCENT_MIN_BLOCK_CHARS``), and flags blocks whose ratio is below
    ``DEACCENT_RATIO_THRESHOLD`` of the baseline when the baseline is
    significant (>= ``DEACCENT_BASELINE_MIN``).

    Known limitation: a COMPLETELY de-accented document has baseline ~0
    (< DEACCENT_BASELINE_MIN) and is NOT flagged -- there is no intra-document
    baseline to compare against. Catching fully de-accented Spanish needs a
    global repo baseline or a Spanish dictionary (follow-up, not a bug).
    """
    lines = text.splitlines()
    if not lines:
        return []
    blocks: list[tuple[int, float]] = []
    for start in range(0, len(lines), DEACCENT_BLOCK_LINES):
        block_text = "\n".join(lines[start : start + DEACCENT_BLOCK_LINES])
        if len(block_text) < DEACCENT_MIN_BLOCK_CHARS:
            continue
        alpha = sum(1 for ch in block_text if ch.isalpha())
        if not alpha:
            continue
        ratio = sum(1 for ch in block_text if ch in ACCENTED_CHARS) / alpha
        blocks.append((start + 1, ratio))
    if len(blocks) < 2:
        return []
    baseline = statistics.median([ratio for _, ratio in blocks])
    if baseline < DEACCENT_BASELINE_MIN:
        return []
    threshold = DEACCENT_RATIO_THRESHOLD * baseline
    snippets: list[str] = []
    for start, ratio in blocks:
        if ratio >= threshold:
            continue
        snippet = (
            f"<deaccent-lossy@line {start}: ratio {ratio:.4f} "
            f"< {DEACCENT_RATIO_THRESHOLD:.2f} * baseline {baseline:.4f}>"
        )
        if snippet not in snippets:
            snippets.append(snippet)
    return snippets


def is_excluded(relative: str) -> bool:
    return any(fnmatch(relative, pattern) for pattern in EXCLUDE_PATTERNS)


def is_allowlisted(relative: str) -> bool:
    return relative in ALLOWLIST


@lru_cache(maxsize=1)
def collect_files_to_check() -> tuple[Path, ...]:
    files = {path for path in STATIC_FILES_TO_CHECK}
    for pattern in GLOB_PATTERNS:
        files.update(path for path in ROOT.glob(pattern) if path.is_file())
    return tuple(sorted(path for path in files if not is_excluded(relative_path(path))))


@lru_cache(maxsize=1)
def collect_scope_set() -> frozenset[Path]:
    return frozenset(collect_files_to_check())


def is_in_scope(relative: str) -> bool:
    if is_excluded(relative):
        return False
    candidate = ROOT / relative
    return candidate in collect_scope_set()


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def has_utf8_bom(path: Path) -> bool:
    return path.read_bytes().startswith(b"\xef\xbb\xbf")


def file_issues(path: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (mojibake, question_mark, text_corruption) issue snippets for path.

    The third element intentionally keeps the existing 3-tuple contract used by
    the CLI guard and the post-write hook.  It now covers:
    - disallowed ASCII control chars (<32, not tab/LF/CR)
    - narrow path-bullet mangling signatures (CTL-2026-007a)
    - C1 control codepoints (U+0080-U+009F) in decoded text (WOT-2026-014d)
    - invalid UTF-8 byte sequences via strict-decode (WOT-2026-014d)
    - de-acentuacion lossy: de-accented Spanish prose in .md/.html/.txt/.xml
      (CTL-2026-012j); not applied to code/config extensions

    Note: ``check_utf8_strict`` operates on raw bytes before ``load_text``
    (which uses errors='replace' semantics via UTF-8 read).  For files that are
    already valid UTF-8 the strict check is a no-op.  For files with invalid
    bytes it returns a diagnostic snippet appended to the third element so the
    existing caller contract (3-tuple, third element is a list[str]) is preserved.
    """
    strict_issues = check_utf8_strict(path)
    if strict_issues:
        # File has invalid UTF-8 bytes: load_text would raise UnicodeDecodeError.
        # Return early with only the strict-decode diagnostic so callers receive
        # a well-formed 3-tuple without an exception propagating.
        return [], [], list(strict_issues)
    text = load_text(path)
    text_corruption = find_text_corruption(text)
    # CTL-2026-012j: de-acentuacion lossy (prose only). Called AFTER the
    # strict-decode early return so bytes-invalid files never reach the
    # text-level check, and AFTER find_text_corruption to keep that function's
    # "structural corruption" contract unchanged.
    if path.suffix.lower() in DEACCENT_PROSE_EXTENSIONS:
        text_corruption.extend(find_deaccentuation_lossy(text))
    return find_mojibake(text), find_q_in_word(text), text_corruption


def iter_staged_files(paths: list[str]) -> list[Path]:
    staged: list[Path] = []
    for rel in paths:
        candidate = ROOT / rel
        if candidate.exists() and candidate.is_file() and is_in_scope(rel):
            staged.append(candidate)
    return staged


# ---------------------------------------------------------------------------
# CTL-2026-012i (Check 2): conformidad estructural HTML contra templates del
# destino. Cross-repo: el motor lee los templates via --project-root en runtime
# (DEC-012i-01); no hardcodea rutas del destino. Complementa (no reemplaza) el
# check intra-documento de 012j con un baseline cross-documento que caza output
# totalmente de-acentuado (limitacion conocida de 012j: un doc COMPLETAMENTE
# de-acentuado tiene baseline ~0 y no se flaggea).
# ---------------------------------------------------------------------------

# Tolerancia de conteo de H2: el output valido puede fusionar secciones del
# template (DEC-012i-03). Medido sobre output real (execution_log
# CTL-2026-012i): output ES `incienso_liturgico/content_es/5_article_polished`
# tiene 8 H2 vs 9 del template Product -> divergencia legitima = 1. Con
# H2_TOLERANCE=1 el output valido pasa (8 >= 9-1) y el colapso estructural
# (1-2 H2 vs 8-9) se caza con margen amplo. Valor minimal justificado por la
# medicion (contrato: "tolerancia >= 1").
H2_TOLERANCE = 1

# Fraccion del baseline de acentos del template que el output debe alcanzar
# (DEC-012i-04). Medido: output ES acentuado accent_freq 0.020510 vs template
# Product 0.005487 (ratio 3.74). Con 0.5 el output valido pasa con ~7.5x margen
# (0.0205 >= 0.5 * 0.0055) y un output totalmente de-acentuado (freq ~0) cae
# bajo el piso. 012i caza "totalmente de-acentuado"; el parcial
# intra-documento lo cubre 012j (rigor proporcional CEM).
TEMPLATE_ACCENT_FRACTION = 0.5

_JSONLD_BLOCK_RE = re.compile(
    r"<script\s+type=[\"']application/ld\+json[\"']>\s*(.*?)\s*</script>",
    re.IGNORECASE | re.DOTALL,
)
_H2_RE = re.compile(r"<h2[\s>]", re.IGNORECASE)


class TemplateProfile(NamedTuple):
    """Perfil estructural de un template del destino (CTL-2026-012i).

    - ``primary_type``: primer @type no-FAQPage del JSON-LD (selector).
    - ``h2_count``: numero de <h2> del template (baseline de estructura).
    - ``accent_freq``: frecuencia de acentos del template (baseline cross-doc).
    - ``has_faqpage``: si el template declara FAQPage (presencia obligatoria).
    - ``template_path``: ruta del template (trazabilidad).
    """

    primary_type: str
    h2_count: int
    accent_freq: float
    has_faqpage: bool
    template_path: Path


def extract_jsonld_types(html: str) -> list[str]:
    """Extraer los @type top-level de cada bloque JSON-LD del HTML, en orden.

    Un @type que es una lista JSON se expande. Los bloques con JSON invalido o
    sin @type no contribuyen tipos (fail-closed: sin tipos validos, el caller
    reporta ``<missing-jsonld>`` o ``<missing-primary-type>``).
    """
    types: list[str] = []
    for match in _JSONLD_BLOCK_RE.finditer(html):
        try:
            obj = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        type_value = obj.get("@type")
        if isinstance(type_value, list):
            types.extend(str(item) for item in type_value)
        elif isinstance(type_value, str):
            types.append(type_value)
    return types


def count_h2(html: str) -> int:
    """Contar elementos <h2> (robusto a atributos; no <h3>/<h4>)."""
    return len(_H2_RE.findall(html))


def accent_frequency(text: str) -> float:
    """Frecuencia de acentos: accented / alpha. Reutiliza ACCENTED_CHARS (012j).

    Retorna 0.0 si no hay caracteres alfabeticos.
    """
    alpha = sum(1 for ch in text if ch.isalpha())
    if not alpha:
        return 0.0
    return sum(1 for ch in text if ch in ACCENTED_CHARS) / alpha


def build_template_registry(templates_dir: Path) -> dict[str, TemplateProfile]:
    """Construir ``{primary_type: TemplateProfile}`` desde templates del destino.

    Lee todos los ``article_*_template.html`` de ``templates_dir`` y extrae el
    @type primario (primer no-FAQPage), el conteo de H2, la frecuencia de
    acentos y la presencia de FAQPage. Fail-closed: lanza si el dir no existe,
    no hay templates, un template no tiene @type primario, o dos templates
    comparten @type primario (CONTRACT_GAP: no se puede seleccionar). El caller
    (CLI) traduce la excepcion en un diagnostico accionable, nunca silent skip.
    """
    if not templates_dir.is_dir():
        raise FileNotFoundError(
            f"templates dir not found (fail-closed): {templates_dir}"
        )
    registry: dict[str, TemplateProfile] = {}
    for path in sorted(templates_dir.glob("article_*_template.html")):
        html = path.read_text(encoding="utf-8")
        types = extract_jsonld_types(html)
        primary = next((t for t in types if t != "FAQPage"), None)
        if primary is None:
            raise ValueError(
                f"template without primary @type (no non-FAQPage @type): {path}"
            )
        if primary in registry:
            raise ValueError(
                f"duplicate primary @type {primary!r}: {path} and "
                f"{registry[primary].template_path} "
                "(CONTRACT_GAP: cannot select template)"
            )
        registry[primary] = TemplateProfile(
            primary_type=primary,
            h2_count=count_h2(html),
            accent_freq=accent_frequency(html),
            has_faqpage="FAQPage" in types,
            template_path=path,
        )
    if not registry:
        raise FileNotFoundError(
            f"no article_*_template.html found in {templates_dir} (fail-closed)"
        )
    return registry


def find_template_conformity_issues(
    html_text: str, registry: dict[str, TemplateProfile]
) -> list[str]:
    """Retornar issues de conformidad del HTML contra el registry de templates.

    Funcion pura (sin I/O). Selecciona el template por @type primario (primer
    no-FAQPage), exige FAQPage secundario, valida H2 minimo con tolerancia y
    baseline de acentos cross-documento. Issues descriptivos y deduplicados.
    Lista vacia = conforme.

    Orden de checks: ``<missing-jsonld>`` -> ``<missing-primary-type>`` ->
    ``<unknown-type:{type}>`` (+ ``<missing-faqpage>``) -> ``<missing-faqpage>``
    -> ``<h2-collapse>`` -> ``<accent-below-template>``.
    """
    types = extract_jsonld_types(html_text)
    if not types:
        return ["<missing-jsonld>"]
    primary = next((t for t in types if t != "FAQPage"), None)
    if primary is None:
        return ["<missing-primary-type>"]
    issues: list[str] = []
    if primary not in registry:
        issues.append(f"<unknown-type:{primary}>")
        if "FAQPage" not in types:
            issues.append("<missing-faqpage>")
        return list(dict.fromkeys(issues))
    if "FAQPage" not in types:
        issues.append("<missing-faqpage>")
    template = registry[primary]
    h2_count = count_h2(html_text)
    h2_floor = template.h2_count - H2_TOLERANCE
    if h2_count < h2_floor:
        issues.append(
            f"<h2-collapse: {h2_count} < {template.h2_count} - {H2_TOLERANCE}>"
        )
    accent_freq = accent_frequency(html_text)
    accent_floor = TEMPLATE_ACCENT_FRACTION * template.accent_freq
    if accent_freq < accent_floor:
        issues.append(
            f"<accent-below-template: {accent_freq:.6f} < "
            f"{TEMPLATE_ACCENT_FRACTION} * {template.accent_freq:.6f}>"
        )
    return list(dict.fromkeys(issues))
