"""Tests de scripts/check_distributable_planning_clean.py (WOT-2026-024h / C4').

El guard mide el ARBOL DE TRABAJO, no el indice de git: el instalador copia con
``shutil.copy2`` desde el filesystem, asi que un fichero UNTRACKED bajo el
manifiesto VIAJA IGUAL (medido en la ruta productiva). Una version previa filtraba
por ``git ls-files`` y producia un FALSO VERDE sobre ese caso; los tests de abajo
lo fijan con su par de mutacion.

Aun asi los fixtures hacen su propio ``git init``: los tests DISTINGUEN tracked de
untracked para demostrar que el veredicto NO depende de esa distincion, y un
fixture sin ``.git`` propio dejaria que el walk-up de git alcanzase el repo REAL y
contestase por el arbol de la maquina (vector WOT-2026-020r).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_distributable_planning_clean import (
    find_contaminated,
    main,
    read_distributable_planning_entries,
)


MOTOR_ROOT = Path(__file__).resolve().parent.parent.parent

_REAL_CONTRACT = """# Ticket Contracts

## WOT-2026-021k

- **status:** frozen
- **deliverable_type:** code
"""

_NEUTRAL_PLANNING = """# Plan Graph

## PLAN-001 -- objetivo del destino

- **status:** draft
"""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )


def _is_untracked(repo: Path, rel: str) -> bool:
    """True si git NO conoce el fichero (verificado contra el repo del fixture)."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--error-unmatch", rel],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode != 0


def _build_motor(tmp_path: Path, planning_files: dict[str, str]) -> Path:
    """Motor fixture: repo git propio + MANIFEST.workspace que distribuye planning."""
    root = tmp_path / "motor"
    planning = root / ".agent" / "planning"
    planning.mkdir(parents=True)
    (root / "MANIFEST.workspace").write_text(
        "# comentario ignorado\n.agent/planning/\n.agent/config/agents.json\n",
        encoding="utf-8",
    )
    for name, body in planning_files.items():
        (planning / name).write_text(body, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixture")
    return root


def test_manifest_entries_only_planning_no_comments(tmp_path):
    """Solo entradas de planning; comentarios y otras rutas quedan fuera."""
    root = _build_motor(tmp_path, {"plan_graph.md": _NEUTRAL_PLANNING})

    assert read_distributable_planning_entries(root) == [".agent/planning/"]


def test_tracked_real_contract_is_caught(tmp_path):
    """ROJO del guard: un contrato WOT real y trackeado en planning contamina."""
    root = _build_motor(tmp_path, {"ticket_contracts.md": _REAL_CONTRACT})

    hits = find_contaminated(root)

    assert ".agent/planning/ticket_contracts.md" in hits
    assert "WOT" in str(hits[".agent/planning/ticket_contracts.md"])
    assert main(["--motor-root", str(root)]) == 1


def test_neutral_planning_is_clean(tmp_path):
    """Planning sin contratos reales -> verde. Distingue 'hay planning' de
    'hay contratos reales': si no distinguiera, seria un gate inutil que prohibe
    al destino tener su propio planning."""
    root = _build_motor(tmp_path, {"plan_graph.md": _NEUTRAL_PLANNING})

    assert find_contaminated(root) == {}
    assert main(["--motor-root", str(root)]) == 0


def test_untracked_contract_is_caught_because_the_installer_copies_it(tmp_path):
    """UNTRACKED tambien contamina: el instalador copia del FILESYSTEM, no de git.

    Este test nace de un FALSO VERDE real. La primera version del guard filtraba
    por `git ls-files` y daba exit 0 con este mismo estado; el probe en la ruta
    productiva demostro que `install_agent_system.py --install --dest <tmp>` SI
    deposita ese fichero en el destino (cabecera `## WOT-2026-021k` medida en el
    destino, 2026-07-21). Git-tracked era el oraculo equivocado: la pregunta es
    "lo copia el instalador?", no "se publica en el repo?".
    """
    root = _build_motor(tmp_path, {"plan_graph.md": _NEUTRAL_PLANNING})
    # Contrato real presente en disco pero NUNCA anadido al indice.
    (root / ".agent" / "planning" / "ticket_contracts.md").write_text(
        _REAL_CONTRACT, encoding="utf-8"
    )
    assert _is_untracked(root, ".agent/planning/ticket_contracts.md"), (
        "el fixture debe dejar el fichero UNTRACKED o no prueba nada"
    )

    assert ".agent/planning/ticket_contracts.md" in find_contaminated(root)
    assert main(["--motor-root", str(root)]) == 1


def test_mut_reinstating_the_tracked_filter_reopens_the_false_green(tmp_path):
    """MUTATION: volver a filtrar por git-tracked resucita el falso verde.

    Par de exit-codes LITERAL sobre la MISMA entrada (un contrato real untracked):
    guard actual -> 1; guard con el filtro tracked reinstaurado -> 0. Aisla que
    medir el filesystem (y no el indice) es lo load-bearing.
    """
    root = _build_motor(tmp_path, {"plan_graph.md": _NEUTRAL_PLANNING})
    (root / ".agent" / "planning" / "ticket_contracts.md").write_text(
        _REAL_CONTRACT, encoding="utf-8"
    )

    assert main(["--motor-root", str(root)]) == 1

    import scripts.check_distributable_planning_clean as guard

    original = guard.find_contaminated

    def _tracked_only(motor_root):
        """La logica VIEJA: descarta lo que git no conoce."""
        return {
            rel: ids
            for rel, ids in original(motor_root).items()
            if not _is_untracked(motor_root, rel)
        }

    guard.find_contaminated = _tracked_only
    try:
        assert main(["--motor-root", str(root)]) == 0, (
            "con el filtro tracked el contrato untracked se vuelve invisible: "
            "ese era exactamente el falso verde"
        )
    finally:
        guard.find_contaminated = original


def test_real_motor_distributable_surface_is_clean():
    """El motor REAL, aqui y ahora: su superficie distribuible no lleva contratos.

    Es el test que habria estado ROJO antes de WOT-2026-024h (el seed trackeado
    con 021k/023r/023s) y que se queda de centinela contra su reintroduccion.
    """
    hits = find_contaminated(MOTOR_ROOT)

    assert hits == {}, f"el motor volvio a embarcar contratos reales: {hits}"


def test_e2e_untracked_seed_really_reaches_a_fresh_destination(tmp_path):
    """El vinculo que justifica el guard: UNTRACKED -> el destino lo recibe.

    Sin este test, el guard afirma una consecuencia ('viajarian a cada destino
    nuevo') que ningun test comprueba: quedaria como una CREENCIA del docstring.
    Aqui se ejecuta el instalador REAL sobre un motor-fixture cuyo contrato NO
    esta trackeado, y se afirma sobre el DESTINO.
    """
    from scripts.install_agent_system import copy_tree, read_manifest_allowlist

    root = _build_motor(tmp_path, {"plan_graph.md": _NEUTRAL_PLANNING})
    (root / ".agent" / "planning" / "ticket_contracts.md").write_text(
        _REAL_CONTRACT, encoding="utf-8"
    )
    dest_agent = tmp_path / "dest" / ".agent"
    dest_agent.mkdir(parents=True)

    copy_tree(root / ".agent", dest_agent, allowlist=read_manifest_allowlist(root))

    landed = dest_agent / "planning" / "ticket_contracts.md"
    assert landed.exists(), (
        "premisa del guard: un contrato untracked bajo el manifiesto SI viaja "
        "(el instalador copia del filesystem, no de git)"
    )
    assert "WOT-2026-021k" in landed.read_text(encoding="utf-8")
    # ...y por eso el guard debe cazarlo en el ORIGEN.
    assert main(["--motor-root", str(root)]) == 1


# ---------------------------------------------------------------------------
# Huecos cerrados tras la review adversarial con lector-FS (Codex).
# ---------------------------------------------------------------------------


def test_non_markdown_file_with_real_contract_is_caught(tmp_path):
    """El instalador copia TODO lo allowlisted, no solo .md.

    Escanear unicamente `*.md` dejaba pasar un contrato real en .txt/.json/.yaml
    bajo la misma ruta distribuible.
    """
    root = _build_motor(tmp_path, {"plan_graph.md": _NEUTRAL_PLANNING})
    (root / ".agent" / "planning" / "contratos.txt").write_text(
        _REAL_CONTRACT, encoding="utf-8"
    )

    assert ".agent/planning/contratos.txt" in find_contaminated(root)
    assert main(["--motor-root", str(root)]) == 1


def test_other_heading_levels_and_prefixes_are_caught(tmp_path):
    """`# WOT-`, `### WOT-` y prefijos de OTROS repos (CTL-/EXF-) contaminan igual.

    Atar el regex a `##` + {WOT,WP,WT} dejaba pasar contratos reales por dos vias
    distintas; el motor declara un ticket_prefix POR DESTINO.
    """
    root = _build_motor(tmp_path, {"plan_graph.md": _NEUTRAL_PLANNING})
    (root / ".agent" / "planning" / "a.md").write_text(
        "# CTL-2026-008k\n\n- **status:** frozen\n", encoding="utf-8"
    )
    (root / ".agent" / "planning" / "b.md").write_text(
        "### EXF-2026-007a\n\n- **status:** frozen\n", encoding="utf-8"
    )

    hits = find_contaminated(root)

    assert ".agent/planning/a.md" in hits
    assert ".agent/planning/b.md" in hits
    assert main(["--motor-root", str(root)]) == 1


def test_reported_ids_are_complete_not_just_the_prefix(tmp_path):
    """El remedio debe nombrar el ID COMPLETO, no 'WOT'.

    Con un grupo CAPTURANTE, findall devolvia solo el prefijo y el operador leia
    `- .agent/planning/x.md: WOT` -- inutil para localizar que contrato retirar
    (gate self-service: debe decir QUE fallo y como reproducirlo).
    """
    root = _build_motor(tmp_path, {"plan_graph.md": _NEUTRAL_PLANNING})
    (root / ".agent" / "planning" / "ticket_contracts.md").write_text(
        "# T\n\n## WOT-2026-021k\n\n## WOT-2026-023r\n", encoding="utf-8"
    )

    ids = find_contaminated(root)[".agent/planning/ticket_contracts.md"]

    assert sorted(set(ids)) == ["WOT-2026-021k", "WOT-2026-023r"], ids


def test_template_placeholders_still_do_not_trigger(tmp_path):
    """Anti falso-rojo: las plantillas del bootstrap NO deben disparar el guard.

    Si un `## <TICKET_ID>` o un `## T-008A-001` contase como contrato real, el
    guard prohibiria el propio flujo documentado de bootstrap por plantillas.
    """
    root = _build_motor(tmp_path, {"plan_graph.md": _NEUTRAL_PLANNING})
    (root / ".agent" / "planning" / "plantilla.md").write_text(
        "## <TICKET_ID>\n\n## T-008A-001\n\n## PLAN-001\n", encoding="utf-8"
    )

    assert find_contaminated(root) == {}
    assert main(["--motor-root", str(root)]) == 0
