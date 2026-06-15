from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


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
    "Forbidden Surfaces",
    "DoD",
    "STOP conditions",
    "CONTRACT_GAP",
    "Builder clarification",
]
STATUS_VALID = {"draft", "review", "frozen", "invalidated"}


def _chk_ticket(block: str, tid: str, fp: str, res: VResult) -> None:
    bl = block.lower()
    for fld in TICKET_REQUIRED:
        if fld.lower() not in bl:
            res.add(fp, fld, f"Campo obligatorio ausente en ticket {tid}")
    sm = re.search(r"\*\*status:?\*\*:?\s*(\S+)", block, re.IGNORECASE)
    if sm:
        st = sm.group(1).strip("*,'\"")
        if st not in STATUS_VALID:
            res.add(
                fp,
                "status",
                f"Valor invalido en {tid}: '{st}'. Validos: {sorted(STATUS_VALID)}",
            )
    else:
        res.add(fp, "status", f"Campo status no encontrado en ticket {tid}")


def validate_ticket_contracts(fp: str, res: VResult) -> None:
    content = Path(fp).read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=##\s+[A-Z])", content)
    found = False
    for block in blocks:
        m = re.match(r"##\s+([A-Z][A-Z0-9_\-]+)\b", block.strip())
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


def validate_plan_graph(fp: str, res: VResult) -> None:
    content = Path(fp).read_text(encoding="utf-8")
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
    if "forbidden surfaces" not in content.lower():
        res.add(
            fp, "Forbidden Surfaces", "Seccion Forbidden Surfaces ausente en plan_graph"
        )
    for pm in re.finditer(r"##\s+(PLAN-\d+)(.*?)(?=\n##|\Z)", content, re.DOTALL):
        pid, pbody = pm.group(1), pm.group(2)
        if "shared_dep" not in pbody.lower() and "shared dep" not in pbody.lower():
            res.add(
                fp,
                f"{pid}:shared_dependencies",
                f"El plan {pid} no declara shared_dependencies",
            )


GAP_REQUIRED = ["ticket_id", "gap_type", "description", "evidence", "action"]


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
