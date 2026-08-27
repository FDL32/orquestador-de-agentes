from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


# WOT-2026-013n / vocabulario de cierre: la terminalidad de un ticket la define
# UNA sola autoridad -- bus/state_machine.py. Este validador NO mantiene su propia
# lista de estados terminales (asi no puede divergir del runtime: un terminal nuevo
# en el enum lo conoce este guard automaticamente). Precedente del import:
# scripts/reconcile_ticket.py:29-33.
_MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))
from bus.state_machine import terminal_state_strings  # noqa: E402


REVALIDATE = "python scripts/validate_contract_formation.py {file}"


@dataclass
class VError:
    file: str
    field_: str
    reason: str

    def render(self) -> str:
        cmd = REVALIDATE.format(file=self.file)
        return f"ERROR | file={self.file} | field={self.field_} | reason={self.reason} | revalidate: {cmd}"


@dataclass
class VResult:
    errors: list[VError] = field(default_factory=list)

    def add(self, f: str, fld: str, r: str) -> None:
        self.errors.append(VError(file=f, field_=fld, reason=r))

    @property
    def ok(self) -> bool:
        return not self.errors


def _body(content: str, heading: str) -> str:
    m = re.search(
        rf"##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##|\Z)",
        content,
        re.IGNORECASE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""


TICKET_REQUIRED = [
    "status",
    "Objective-Link",
    "Plan-Link",
    "Premise",
    "Premise Re-check",
    "Context Baseline",
    "Forbidden Surfaces",
    "DoD",
    "STOP conditions",
    "CONTRACT_GAP",
    "Builder clarification",
]

# Estados de un contrato VIVO (en formacion): exigen TODO el checklist TICKET_REQUIRED.
STATUS_LIVE = {"draft", "review", "frozen", "invalidated"}


# Estados TERMINALES: derivados de la UNICA autoridad (bus/state_machine.py). Un
# contrato terminal NO es un contrato en formacion -> se exime del checklist de
# campos-vivos (no tiene sentido exigir "Premise Re-check" a un ticket cerrado);
# solo exige `status` valido + una traza minima de cierre (`closed:` o `Evidence:`).
# terminal_state_strings() da COMPLETED/SUPERSEDED/BLOCKED_FINAL (+legacy CLOSED);
# se normaliza a minusculas y se aceptan las variantes con guion que el vocabulario
# de contrato uso historicamente (blocked-final == BLOCKED_FINAL).
def _terminal_status_tokens() -> set[str]:
    toks: set[str] = set()
    for s in terminal_state_strings(include_legacy=True):
        low = s.lower()
        toks.add(low)
        toks.add(low.replace("_", "-"))  # blocked_final <-> blocked-final
    return toks


STATUS_TERMINAL = _terminal_status_tokens()
STATUS_VALID = STATUS_LIVE | STATUS_TERMINAL


# ---------------------------------------------------------------------------
# WOT-2026-055e: LA MEMORIA COMO ENTRADA, NO COMO ADORNO.
# Un contrato se CONGELA (`status: frozen`) sin haber consultado el archive de
# lecciones, asi que el mismo defecto se re-descubre y se vuelve a pagar. El
# corpus portable EXISTE (215 entradas, MEDIDO 2026-08-27, en
# .agent/runtime/memory/archive/observations.YYYY-MM.jsonl) y nada obligaba a
# mirarlo antes de congelar. ROJO MEDIDO: un contrato frozen SIN matriz de
# consulta valida rc=0.
#
# Se exige, SOLO para frozen, una matriz `DoD-item | consulta | hits |
# conclusion` y el hash corto (>=7) del archive consultado. La verificacion es
# de FORMA: que el hash declarado sea coherente, no que sus bytes se relean aqui
# (M1 del diseno) -- este validador no abre el archive.
#
# CORRECCION MEDIDA a la ruta del diseno: el archive NO vive en `archive/` sino
# en `.agent/runtime/memory/archive/`. La ruta del enunciado no existe en disco.
# ---------------------------------------------------------------------------

# Fila de la matriz: cuatro columnas separadas por `|`, todas con contenido real
# (una fila de guiones es el separador markdown, no una consulta).
_MEMORY_MATRIX_ROW_RE = re.compile(
    r"^\s*\|(?P<dod>[^|\n]+)\|(?P<consulta>[^|\n]+)\|(?P<hits>[^|\n]+)\|"
    r"(?P<concl>[^|\n]+)\|\s*$",
    re.MULTILINE,
)

# Separador de tabla markdown (|---|---|): no es fila de datos.
_MATRIX_SEPARATOR_RE = re.compile(r"^[\s:-]+$")

# Hash corto del archive consultado. La convencion del repo es >=7 hex; uno mas
# corto NO identifica un commit y se rechaza NOMBRANDO su longitud. Se capturan
# tambien los de 4-6 chars para poder DIAGNOSTICAR el truncado en vez de decir
# "falta el hash" cuando lo que pasa es que esta mutilado.
#
# FALSO POSITIVO MEDIDO 2026-08-27: el nombre del propio archive contiene un ano
# que es hex VALIDO -- `observations.2026-08` ofrece `2026` (4 chars) ANTES que
# el sha real, y quedarse con la PRIMERA coincidencia rechazaba un contrato
# correcto por "hash truncado ('2026')". Se recogen TODOS los candidatos de la
# linea y basta con que UNO sea un hash legitimo; solo si ninguno lo es se
# reporta el mas largo como truncado. La fecha `YYYY-MM` se descarta ademas por
# forma, para no contar un ano como intento de sha.
_ARCHIVE_LINE_RE = re.compile(r"^.*archive.*$", re.IGNORECASE | re.MULTILINE)
_HEX_TOKEN_RE = re.compile(r"(?<![0-9a-zA-Z])([0-9a-f]{4,40})(?![0-9a-zA-Z])")
# `2026-08` / `2026-08-27`: fragmento de fecha, nunca un sha declarado.
_DATE_FRAGMENT_RE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?")


def _archive_hash_candidates(block: str) -> list[str]:
    """Hex tokens on any line mentioning the archive, minus date fragments."""
    out: list[str] = []
    for line in _ARCHIVE_LINE_RE.findall(block):
        masked = _DATE_FRAGMENT_RE.sub(lambda m: " " * len(m.group(0)), line)
        out.extend(_HEX_TOKEN_RE.findall(masked))
    return out


_MEMORY_MATRIX_HEADER_TOKENS = ("dod-item", "consulta", "hits", "conclusion")


def _matrix_rows(block: str) -> list[tuple[str, str, str, str]]:
    """Data rows of the memory-consultation matrix (header/separator excluded)."""
    rows: list[tuple[str, str, str, str]] = []
    for m in _MEMORY_MATRIX_ROW_RE.finditer(block):
        cells = [
            m.group("dod").strip(),
            m.group("consulta").strip(),
            m.group("hits").strip(),
            m.group("concl").strip(),
        ]
        if not all(cells):
            continue
        if any(_MATRIX_SEPARATOR_RE.fullmatch(c) for c in cells):
            continue
        joined = " ".join(c.lower() for c in cells)
        if all(tok in joined for tok in _MEMORY_MATRIX_HEADER_TOKENS):
            continue
        rows.append((cells[0], cells[1], cells[2], cells[3]))
    return rows


def _chk_frozen_memory_consultation(
    block: str, tid: str, fp: str, res: VResult
) -> None:
    """WOT-2026-055e: a frozen contract must SHOW it consulted the archive."""
    rows = _matrix_rows(block)
    if not rows:
        res.add(
            fp,
            "memory_matrix",
            f"Ticket frozen {tid}: falta la matriz de consulta al archive "
            "(`DoD-item | consulta | hits | conclusion`) -- congelar sin "
            "consultar la memoria re-descubre lo ya escrito",
        )
        return

    candidates = _archive_hash_candidates(block)
    if not candidates:
        res.add(
            fp,
            "memory_archive_hash",
            f"Ticket frozen {tid}: la matriz no declara el hash corto del "
            "archive consultado (observations.YYYY-MM.jsonl)",
        )
        return
    if any(len(c) >= 7 for c in candidates):
        return
    worst = max(candidates, key=len)
    res.add(
        fp,
        "memory_archive_hash",
        f"Ticket frozen {tid}: hash del archive truncado "
        f"('{worst}', {len(worst)} chars): se exigen >=7",
    )


def _chk_ticket(block: str, tid: str, fp: str, res: VResult) -> None:
    bl = block.lower()
    sm = re.search(r"\*\*status:?\*\*:?\s*([A-Za-z_-]+)", block, re.IGNORECASE)
    st = sm.group(1).strip("*,'\"").lower() if sm else None

    # Un contrato TERMINAL con traza valida se exime del checklist de campos-vivos
    # (un ticket cerrado no necesita "Premise Re-check"); solo exige la traza de
    # cierre. Cualquier otra cosa -- vivo, sin status, o status invalido -- NO es
    # un cierre legitimo y se le exige el checklist COMPLETO de contrato-en-formacion
    # (asi un contrato al que le falte status no escapa a la validacion de campos).
    if st in STATUS_TERMINAL:
        if "closed:" not in bl and "evidence:" not in bl:
            res.add(
                fp,
                "closure_trace",
                f"Ticket terminal {tid} ('{st}') sin traza de cierre "
                "(se exige `closed:` o `Evidence:`)",
            )
        return

    if st is None:
        res.add(fp, "status", f"Campo status no encontrado en ticket {tid}")
    elif st not in STATUS_VALID:
        res.add(
            fp,
            "status",
            f"Valor invalido en {tid}: '{st}'. Validos: {sorted(STATUS_VALID)}",
        )

    # Contrato VIVO (o con status ausente/invalido): exige el checklist completo.
    for fld in TICKET_REQUIRED:
        if fld.lower() not in bl:
            res.add(fp, fld, f"Campo obligatorio ausente en ticket {tid}")

    # WOT-2026-055e: congelar exige, ADEMAS, haber consultado la memoria.
    if st == "frozen":
        _chk_frozen_memory_consultation(block, tid, fp, res)


def validate_ticket_contracts(fp: str, res: VResult) -> None:
    content = Path(fp).read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=##\s+(?:<?[A-Z]))", content)
    found = False
    for block in blocks:
        # La clase incluye MINUSCULAS a proposito (F-3, 2026-08-05): la convencion
        # de ids de este repo lleva sufijo en minuscula (`WOT-2026-047w`,
        # `CTL-2026-013a`). Con `[A-Z0-9_\-]+\b` el `\b` retrocedia hasta el ultimo
        # guion y el id se reportaba MUTILADO (`CTL-2026-`), asi que N tickets de
        # la misma familia colapsaban en la MISMA etiqueta de error y el reporte
        # no permitia saber cual fallaba. Medido en el destino: 17/17 errores sin
        # identificar su ticket.
        # El ID se captura como TOKEN COMPLETO (hasta espacio o fin de linea), no
        # cortando en el primer `\b` (F-3, 2026-08-05 + bucle L800 nonce 8662423b).
        #
        # Dos defectos que esta forma cierra, ambos MEDIDOS:
        #  1. MUTILACION. `[A-Z0-9_\-]+\b` excluia minusculas, y la convencion de
        #     ids de este repo lleva sufijo en minuscula (`WOT-2026-047w`). El `\b`
        #     retrocedia hasta el ultimo guion -> el error decia `WOT-2026-` pelado
        #     y N tickets hermanos colapsaban en la MISMA etiqueta (17/17 errores
        #     sin identificar su ticket, reportado desde el destino).
        #  2. PROSA DE UNA PALABRA EN MAYUSCULAS. `## TODO`, `## API`, `## JSON`
        #     matcheaban como si fueran tickets -- defecto PREEXISTENTE, no
        #     introducido aqui: el regex viejo tambien los aceptaba. Se exige ahora
        #     al menos un DIGITO en el id, que es lo que distingue un identificador
        #     (`CTL-2026-013a`, `T-HEALTH-001`) de una palabra (`TODO`).
        #
        # El placeholder `<NOMBRE>` conserva su rama propia: no lleva digito.
        m = re.match(
            r"##\s+(<[A-Z][A-Za-z0-9_\-]*>|[A-Z][A-Za-z0-9_\-]*[0-9][A-Za-z0-9_\-]*)(?=\s|$)",
            block.strip(),
        )
        if m:
            found = True
            _chk_ticket(block, m.group(1), fp, res)
    if not found:
        res.add(
            fp, "ticket_contract", "No se encontraron bloques de ticket (## TICKET_ID)"
        )


CHARTER_SECTIONS = [
    "Product Intent",
    "Architecture Constraints",
    "Non-Goals",
    "Quality Bar",
    "Security Constraints",
    "Negative Audit Checklist",
]


def validate_repo_charter(fp: str, res: VResult) -> None:
    content = Path(fp).read_text(encoding="utf-8")
    for sec in CHARTER_SECTIONS:
        if not re.search(rf"##\s+{re.escape(sec)}", content, re.IGNORECASE):
            res.add(fp, f"section:{sec}", f"Seccion obligatoria ausente: {sec}")
    obj_list = list(
        re.finditer(r"#{2,3}\s+(OBJ-\d+)(.*?)(?=\n#{2,3}\s|\Z)", content, re.DOTALL)
    )
    if not obj_list:
        res.add(fp, "OBJ-*", "No se encontraron objetivos OBJ-*")
    for om in obj_list:
        oid, obody = om.group(1), om.group(2)
        if "failure_modes" not in obody.lower():
            res.add(
                fp,
                f"{oid}:failure_modes",
                f"El objetivo {oid} no declara failure_modes",
            )
    nac = _body(content, "Negative Audit Checklist")
    items = re.findall(r"- \[[ x]\]", nac)
    if len(items) < 2:
        res.add(fp, "Negative Audit Checklist", f"{len(items)} items (minimo 2)")
    ng = _body(content, "Non-Goals")
    if len(ng) < 20:
        res.add(fp, "Non-Goals", "Seccion Non-Goals vacia o insuficiente (< 20 chars)")


# WOT-2026-025v: marcadores TERMINALES de un bloque PLAN en el plan_graph. Son
# etiquetas EDITORIALES del header (## PLAN-xxx -- [MARKER]), NO estados runtime
# del bus (STATUS_TERMINAL vive en otro dominio; mezclarlos contaminaria a los
# consumidores de estados canonicos -- adjudicado Codex-FS 2026-07-20). Un bloque
# terminal (cancelado/no-perseguido/bloqueado-final) no tiene superficie operativa,
# asi que 'n/a' en paralelizable y la ausencia de shared_dependencies son LEGITIMOS.
# La exencion mira el MARKER DEL HEADER, nunca el valor invalido: un bloque VIVO con
# 'n/a' sigue siendo ERROR.
PLAN_TERMINAL_MARKERS = ("CANCELADO", "NOT-PURSUED", "BLOCKED-FINAL")


def _plan_header_is_terminal(header_line: str) -> bool:
    """True si el header de un bloque PLAN lleva un marker terminal en corchetes.

    Casa ``## PLAN-xxx -- [CANCELADO / ABSORBED ...]`` / ``[NOT-PURSUED]`` /
    ``[BLOCKED-FINAL]`` por allowlist EXACTA sobre el PRIMER token del ``[...]``.
    El token es la primera palabra dentro de los corchetes (partido por espacio o
    ``/``), normalizada a mayusculas. Asi ``NO-CANCELADO``, ``CANCELADO-PARCIAL`` o
    ``XBLOCKED-FINALY`` NO casan (Codex-FS: un substring laxo contradiria "exacta").
    No casa un marker fuera de corchetes ni en el cuerpo.
    """
    m = re.search(r"\[([^\]]+)\]", header_line)
    if not m:
        return False
    inside = m.group(1).upper().strip()
    # primer token: hasta el primer separador (espacio o '/')
    first_token = re.split(r"[\s/]+", inside, maxsplit=1)[0]
    return first_token in PLAN_TERMINAL_MARKERS


VALID_PARALELIZABLE_RE = re.compile(r"^\s*(yes|no|after\s+PLAN-\d+)\s*$", re.IGNORECASE)

TABLE_PLAN_ROW_RE = re.compile(r"^\|\s*PLAN-\d+.*\|$", re.IGNORECASE | re.MULTILINE)


def _find_paralelizable_column_index(impact_body: str) -> int | None:
    """Parse the Impact Simulation table header and return the column index
    whose header label matches 'paralelizable' (case-insensitive).

    Returns None if no matching header column is found.
    """
    for line in impact_body.split("\n"):
        ls = line.strip()
        if ls.startswith("|") and not ls.startswith("|-"):
            cells = [c.strip().lower() for c in ls.split("|")[1:-1]]
            for i, cell in enumerate(cells):
                if "paralelizable" in cell:
                    return i
    return None


def _terminal_plan_ids(content: str) -> set[str]:
    """Set of EXACT PLAN ids whose block HEADER carries a terminal marker (025v).

    Scans every ``## PLAN-<id> -- [MARKER]`` header line and collects the FULL
    plan id (e.g. ``PLAN-013B-002``) UP-CASED when ``_plan_header_is_terminal``
    matches. Consumers match by EXACT (case-normalized) id -- never by family
    prefix (Codex-FS: ``PLAN-013`` must NOT be exempted by a terminal *child*
    ``PLAN-013B-002``; a live family block/row keeps its checks).
    """
    terminal: set[str] = set()
    for line in content.splitlines():
        hm = re.match(r"##\s+(PLAN-[A-Z0-9-]+)", line, re.IGNORECASE)
        if hm and _plan_header_is_terminal(line):
            terminal.add(hm.group(1).upper())
    return terminal


def _validate_paralelizable_values(
    fp: str, impact_body: str, res: VResult, terminal_pids: set[str]
) -> None:
    """Validate strict paralelizable values in Impact Simulation table rows.

    Locates the Paralelizable column by header name (not position) and
    validates each data row's value against the strict regex. WOT-2026-025v:
    a row whose FULL plan-id is terminal (EXACT, case-normalized match against
    ``terminal_pids``) is exempt -- a cancelled/not-pursued/blocked plan
    legitimately declares ``n/a``. A live row is NOT exempt.
    """
    col_index = _find_paralelizable_column_index(impact_body)
    if col_index is None:
        # Column not found by header; the column-name existence check in
        # validate_plan_graph will catch missing "paralelizable".
        return
    for line in impact_body.split("\n"):
        ls = line.strip()
        if TABLE_PLAN_ROW_RE.match(ls):
            cells = [c.strip() for c in ls.split("|")]
            # cells[0] is empty (before first |), cells[-1] is empty (after last |)
            real_cells = cells[1:-1]
            if col_index < len(real_cells):
                paralelizable_val = real_cells[col_index]
                pid = real_cells[0]
                if pid.upper() in terminal_pids:
                    continue  # WOT-2026-025v: terminal block, 'n/a' is legitimate
                if not VALID_PARALELIZABLE_RE.match(paralelizable_val):
                    res.add(
                        fp,
                        f"Impact Simulation:{pid}:paralelizable",
                        f"Valor de paralelizable invalido: '{paralelizable_val}'. "
                        "Valores permitidos: yes, no, after PLAN-00x",
                    )


def validate_plan_graph(fp: str, res: VResult) -> None:
    content = Path(fp).read_text(encoding="utf-8")
    # WOT-2026-025v: PLAN blocks whose header carries a terminal marker are exempt
    # from the paralelizable-value and shared_dependencies checks (no operational
    # surface -> 'n/a' and absent shared_deps are legitimate).
    terminal_pids = _terminal_plan_ids(content)
    if not re.findall(r"##\s+PLAN-\d+", content):
        res.add(fp, "PLAN-*", "No se encontraron planes PLAN-* en plan_graph")
    if "impact simulation" not in content.lower():
        res.add(
            fp,
            "Impact Simulation",
            "Seccion Impact Simulation ausente (obligatoria, pipeline seccion 7)",
        )
    else:
        impact_m = re.search(
            r"impact simulation.*?\n(.*?)(?=\n##|\Z)",
            content,
            re.IGNORECASE | re.DOTALL,
        )
        ibody = impact_m.group(1).lower() if impact_m else ""
        for col in ["plan", "superficies", "shared", "conflicto", "paralelizable"]:
            if col not in ibody:
                res.add(
                    fp,
                    f"Impact Simulation:{col}",
                    f"Columna '{col}' ausente en tabla Impact Simulation",
                )
        # --- Strict paralelizable value validation ---
        impact_full = impact_m.group(1) if impact_m else ""
        _validate_paralelizable_values(fp, impact_full, res, terminal_pids)
    if "forbidden surfaces" not in content.lower():
        res.add(
            fp, "Forbidden Surfaces", "Seccion Forbidden Surfaces ausente en plan_graph"
        )
    if "merge regression audit" not in content.lower():
        res.add(
            fp,
            "Merge Regression Audit",
            "Seccion Merge Regression Audit ausente (obligatoria en plan_graph)",
        )
    for pm in re.finditer(
        r"##\s+(PLAN-[A-Z0-9-]+)([^\n]*)(.*?)(?=\n##|\Z)",
        content,
        re.IGNORECASE | re.DOTALL,
    ):
        full_pid, header_rest, pbody = pm.group(1), pm.group(2), pm.group(3)
        # WOT-2026-025v: terminal block (marker in ITS OWN header) is exempt;
        # keyed on THIS block's full id, never a family prefix (Codex-FS).
        if full_pid.upper() in terminal_pids or _plan_header_is_terminal(header_rest):
            continue
        # Report using the family form (PLAN-\d+) to preserve the historic field key.
        fam = re.match(r"(PLAN-\d+)", full_pid, re.IGNORECASE)
        pid = fam.group(1) if fam else full_pid
        if "shared_dep" not in pbody.lower() and "shared dep" not in pbody.lower():
            res.add(
                fp,
                f"{pid}:shared_dependencies",
                f"El plan {pid} no declara shared_dependencies",
            )


GAP_REQUIRED = [
    "ticket_id",
    "gap_type",
    "description",
    "evidence",
    "requested_resolution",
]


def validate_contract_gap(fp: str, res: VResult) -> None:
    content = Path(fp).read_text(encoding="utf-8").lower()
    for fld in GAP_REQUIRED:
        if fld not in content:
            res.add(
                fp,
                fld,
                f"Campo obligatorio ausente en CONTRACT_GAP: {fld}. Ver docs/contract_formation/templates/contract_gap.md",
            )


def _detect(fp: str) -> str:
    name = Path(fp).name.lower()
    if "charter" in name:
        return "charter"
    if "plan_graph" in name or "plan-graph" in name:
        return "plan_graph"
    if "ticket_contract" in name:
        return "ticket_contracts"
    if "contract_gap" in name or name.startswith("cg-"):
        return "contract_gap"
    try:
        c = Path(fp).read_text(encoding="utf-8")
        if "Product Intent" in c or "OBJ-" in c:
            return "charter"
        if "PLAN-" in c and "Impact Simulation" in c:
            return "plan_graph"
        if "Forbidden Surfaces" in c and "CONTRACT_GAP" in c:
            return "ticket_contracts"
    except OSError:
        pass
    return "unknown"


DISPATCH = {
    "charter": validate_repo_charter,
    "plan_graph": validate_plan_graph,
    "ticket_contracts": validate_ticket_contracts,
    "contract_gap": validate_contract_gap,
}


def _resolve_typed(args: argparse.Namespace) -> list[tuple[str, str]]:
    typed: list[tuple[str, str]] = []
    if args.charter:
        typed.append((args.charter, "charter"))
    if args.plan:
        typed.append((args.plan, "plan_graph"))
    if args.tickets:
        typed.append((args.tickets, "ticket_contracts"))
    if args.gap:
        typed.append((args.gap, "contract_gap"))
    typed.extend((f, _detect(f)) for f in args.files)
    return typed


def _validate_all(typed: list[tuple[str, str]], res: VResult) -> None:
    for fp, doc_type in typed:
        if not Path(fp).exists():
            res.add(fp, "file", f"Archivo no encontrado: {fp}")
            continue
        fn = DISPATCH.get(doc_type)
        if fn is None:
            res.add(
                fp,
                "type",
                f"Tipo no reconocido: {doc_type}. Use --charter/--plan/--tickets/--gap",
            )
            continue
        fn(fp, res)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Validate Contract Formation artifacts (stdlib-only)."
    )
    p.add_argument("files", nargs="*")
    p.add_argument("--charter", metavar="FILE")
    p.add_argument("--plan", metavar="FILE")
    p.add_argument("--tickets", metavar="FILE")
    p.add_argument("--gap", metavar="FILE")
    args = p.parse_args(argv)
    res = VResult()
    typed = _resolve_typed(args)
    if not typed:
        p.print_help()
        return 0
    _validate_all(typed, res)
    if res.ok:
        print(f"OK: {len(typed)} file(s) validated, 0 errors.")
        return 0
    print(f"ERRORS: {len(res.errors)} error(s) found.\n")
    for e in res.errors:
        print(e.render())
    return 1


if __name__ == "__main__":
    sys.exit(main())
