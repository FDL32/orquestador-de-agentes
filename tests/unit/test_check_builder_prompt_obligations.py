"""Contrato del guard de obligaciones de cierre en prompts de Builder (WOT-2026-067z).

Lo que estos tests fijan:

- La MUTACION con ambos rc publicados: el MISMO prompt sin los verbos de cierre
  da exit 1; el mismo prompt CON el bloque de handoff canonico da exit 0.
- El CONTROL CONTRARIO: menciones SOLO en contexto negativo o como dato (celda
  no-primeras de una fila pipe) NO transportan la obligacion y el guard sigue
  rojo; la mencion en primera celda de tabla SI transporta.
- La DERIVACION: la lista de verbos sale del canonico real (frase de existencia
  del handoff + tabla de codigos de parada), no de una cura a mano; y si un
  anclaje desaparece la derivacion FALLA CERRADA (exit 3), nunca audita con una
  lista vacia que dejaria pasar todo el universo.
- El DENOMINADOR: publicado siempre, incluso en fallo; universo vacio es
  exit 1, nunca un verde vacuo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


MOTOR_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MOTOR_ROOT / "scripts"))

from check_builder_prompt_obligations import (  # noqa: E402
    DerivationError,
    audit_prompt_universe,
    derive_closure_verbs,
    derive_verbs_from_file,
    main,
    mention_contexts,
    scan_prompt,
)


REAL_CANONICAL = MOTOR_ROOT / "prompts" / "orchestrator_launch_builder.md"

# Espejo ESTRUCTURAL del canonico real: la frase de existencia envuelta en tres
# lineas y la tabla de codigos con un codigo de seccion handoff y otro que no.
MINIMAL_CANONICAL = """\
# Canonico de prueba
contract_id: cid-bui-implement-v1

## Referencia rapida: codigos de parada

| Codigo | Seccion | Disparador |
|---|---|---|
| `CONTRACT_MISMATCH` | Paso -1 | El hash del contrato difiere |
| `HANDOFF_IMPOSSIBLE` | Contrato de handoff canonico | No puedes emitir `BUILDER_EXIT`+`STATE_CHANGED` canonicos |

## Registro y cierre

Contrato de handoff canonico:

- El handoff solo existe cuando `--mark-ready` completa con exito y deja
  evidencia canonica de `BUILDER_EXIT` + `STATE_CHANGED` hacia
  `READY_FOR_REVIEW`.
"""

DERIVED_VERBS = [
    "--mark-ready",
    "BUILDER_EXIT",
    "STATE_CHANGED",
    "READY_FOR_REVIEW",
    "HANDOFF_IMPOSSIBLE",
]

CID_LINE = "contract_id: cid-bui-implement-v1"

# El bloque de handoff tal como el canonico lo redacta: todas las menciones en
# contexto portador (imperativo y definicion, sin disparador de negacion).
CARRYING_BLOCK = (
    "- El handoff solo existe cuando `--mark-ready` completa con exito y deja"
    "\n  evidencia canonica de `BUILDER_EXIT` + `STATE_CHANGED` hacia"
    "\n  `READY_FOR_REVIEW`."
    "\n- Si no puedes emitir esos eventos, detente y reporta `HANDOFF_IMPOSSIBLE`."
)

NEGATIVE_BLOCK = (
    "Prohibiciones duras:"
    "\n- NO fabricar `BUILDER_EXIT` ni `STATE_CHANGED` sinteticos."
    "\n- Sin `BUILDER_EXIT` no hay handoff que contar."
    "\n- no uses `--mark-ready` (no reports `HANDOFF_IMPOSSIBLE`: el cierre lo"
    "\n  lleva el Manager)."
    "\n- Y no declares `READY_FOR_REVIEW` por narrativa."
)


def _canonico(root: Path, body: str = MINIMAL_CANONICAL) -> Path:
    prompts = root / "canonico" / "prompts"
    prompts.mkdir(parents=True, exist_ok=True)
    path = prompts / "orchestrator_launch_builder.md"
    path.write_text(body, encoding="utf-8")
    return path


def _prompt(root: Path, relpath: str, body: str) -> Path:
    path = root / ".agent" / "planning" / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _run(root: Path, canonico: Path, capsys):
    rc = main(["--project-root", str(root), "--canonical", str(canonico)])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


# ---------------------------------------------------------------------------
# MUTACION: mismo prompt, sin y con los verbos. rc rojo=1, rc verde=0.
# ---------------------------------------------------------------------------
def test_mutacion_prompt_sin_verbos_rojo_con_verbos_verde(tmp_path, capsys):
    """MUTACION (rc publicados): sin el bloque de handoff -> rc 1; con el
    bloque de handoff canonico (mismo fichero, misma declaracion de cid) ->
    rc 0. Es el par rojo/verde del DoD, no dos fixtures distintos."""
    canonico = _canonico(tmp_path)
    base = f"# Prompt Builder\n{CID_LINE}\n\nObjetivo: implementar el ticket.\n"
    _prompt(tmp_path, "PROMPT_BUILDER_WOT-2026-000a.md", base)
    rc_rojo, out_rojo, _ = _run(tmp_path, canonico, capsys)
    assert rc_rojo == 1, out_rojo
    assert "5 hallazgo(s)" in out_rojo, out_rojo

    verde = base + "\n" + CARRYING_BLOCK + "\n"
    _prompt(tmp_path, "PROMPT_BUILDER_WOT-2026-000a.md", verde)
    rc_verde, out_verde, _ = _run(tmp_path, canonico, capsys)
    assert rc_verde == 0, out_verde
    assert "0 hallazgo(s)" in out_verde, out_verde


def test_cada_verbo_ausente_produce_su_propio_hallazgo(tmp_path):
    """El hallazgo es POR VERBO, no un rojo opaco: el redactor debe saber QUE
    obligacion falta, no solo que algo falta."""
    root = tmp_path
    _prompt(root, "PROMPT_BUILDER_WOT-2026-000b.md", f"# Prompt\n{CID_LINE}\n")
    findings, prompts = audit_prompt_universe(root, DERIVED_VERBS)
    assert len(prompts) == 1
    missing = {f.line.split(" ")[0] for f in findings}
    assert missing == set(DERIVED_VERBS)
    assert all(f.rule == "V1-verbo-cierre-ausente" for f in findings)


# ---------------------------------------------------------------------------
# CONTROL CONTRARIO: negacion y dato no transportan; primera celda si.
# ---------------------------------------------------------------------------
def test_control_contrario_menciones_solo_negativas_sigue_rojo(tmp_path, capsys):
    """CONTROL CONTRARIO (negacion): un prompt que menciona TODOS los verbos
    pero solo bajo negacion NO transporta la obligacion y el guard sigue rojo.
    Medido en el corpus real: `arranque_20260905_vuelo_p0.md` menciona
    `--mark-ready` solo en contexto negativo y el guard lo reporta ausente."""
    canonico = _canonico(tmp_path)
    body = f"# Prompt\n{CID_LINE}\n\n{NEGATIVE_BLOCK}\n"
    _prompt(tmp_path, "PROMPT_BUILDER_WOT-2026-000c.md", body)
    rc, out, _ = _run(tmp_path, canonico, capsys)
    assert rc == 1, out
    for verb in DERIVED_VERBS:
        assert f"{verb} (solo neg)" in out, (
            f"{verb} deberia salir como solo neg:\n{out}"
        )


def test_control_contrario_mencion_solo_como_dato_sigue_rojo(tmp_path, capsys):
    """CONTROL CONTRARIO (dato): el codigo copiado como VALOR en celdas
    no-primeras de una fila pipe (bus log, descripcion del disparador) no es la
    orden. Es el caso real de `builder_prompt_WOT-2026-072b.md`, que copia la
    tabla de codigos pero omite `--mark-ready`."""
    canonico = _canonico(tmp_path)
    fila = (
        "| Codigo | Seccion | Disparador |\n"
        "|---|---|---|\n"
        "| `HANDOFF_IMPOSSIBLE` | Cierre | No puedes emitir "
        "`BUILDER_EXIT`+`STATE_CHANGED` canonicos |\n"
    )
    body = f"# Prompt\n{CID_LINE}\n\n{fila}\n"
    _prompt(tmp_path, "PROMPT_BUILDER_WOT-2026-000d.md", body)
    rc, out, _ = _run(tmp_path, canonico, capsys)
    assert rc == 1, out
    assert "BUILDER_EXIT (solo data)" in out, out
    assert "STATE_CHANGED (solo data)" in out, out


def test_mencion_en_primera_celda_si_transporta(tmp_path):
    """CONTROL POSITIVO del anterior: el codigo en la PRIMERA celda (la columna
    del propio codigo) SI transporta; sin esto, la regla de datos marcaria la
    copia legitima de la tabla de codigos."""
    root = tmp_path
    fila = "| `HANDOFF_IMPOSSIBLE` | Contrato de handoff canonico | disparador |\n"
    _prompt(
        root, "PROMPT_BUILDER_WOT-2026-000e.md", f"# Prompt\n{CID_LINE}\n\n{fila}\n"
    )
    findings, _prompts = audit_prompt_universe(root, DERIVED_VERBS)
    ausentes = {f.line.split(" ")[0] for f in findings}
    assert "HANDOFF_IMPOSSIBLE" not in ausentes
    assert ausentes == {
        "--mark-ready",
        "BUILDER_EXIT",
        "STATE_CHANGED",
        "READY_FOR_REVIEW",
    }


def test_la_prosa_portadora_con_no_ajeno_no_es_falso_positivo(tmp_path, capsys):
    """El barrido de falsos positivos de la negacion: lineas portadoras que
    contienen 'no' en otra clausula o como marcador discursivo NO se marcan.
    El texto del fixture es la propia redaccion del canonico."""
    canonico = _canonico(tmp_path)
    body = f"# Prompt\n{CID_LINE}\n\n{CARRYING_BLOCK}\n"
    _prompt(tmp_path, "PROMPT_BUILDER_WOT-2026-000f.md", body)
    rc, out, _ = _run(tmp_path, canonico, capsys)
    assert rc == 0, out


def test_la_negacion_se_acota_a_su_ventana_y_a_su_marcador():
    """Ventana y marcadores discursivos: 'no' a 2 tokens del verbo niega;
    'sin embargo, ejecuta X' no niega; la negacion no cruza la clausula."""
    assert mention_contexts(
        "no debes emitir `BUILDER_EXIT` sin evento", "BUILDER_EXIT"
    ) == {"neg"}
    assert mention_contexts("sin embargo, ejecuta `--mark-ready`", "--mark-ready") == {
        "pos"
    }
    assert mention_contexts(
        "No hagas rondas vacias: cada nuevo `--mark-ready` aporta evidencia.",
        "--mark-ready",
    ) == {"pos"}
    assert mention_contexts(
        "Si no puedes emitir esos eventos, detente y reporta `HANDOFF_IMPOSSIBLE`.",
        "HANDOFF_IMPOSSIBLE",
    ) == {"pos"}


# ---------------------------------------------------------------------------
# DERIVACION: del canonico real, fail-closed si un anclaje desaparece.
# ---------------------------------------------------------------------------
def test_la_lista_se_deriva_del_canonico_real_no_de_una_cura():
    """La lista de verbos sale del canonico REAL del motor. Este test es el
    EFECTO DECLARADO de un cambio del canonico: si se reescribe la frase de
    existencia o la tabla de codigos, este test cae y alguien actualiza los
    anclajes del guard (o ficha CG); el guard nunca se queda con una lista
    vacia silenciosa."""
    if not REAL_CANONICAL.exists():
        pytest.skip("canonico real no presente en este checkout")
    commands, stop_codes = derive_verbs_from_file(REAL_CANONICAL)
    assert "--mark-ready" in commands
    assert {"BUILDER_EXIT", "STATE_CHANGED", "READY_FOR_REVIEW"} <= set(commands)
    assert stop_codes == ["HANDOFF_IMPOSSIBLE"]


def test_la_derivacion_del_canonico_de_prueba_coincide_con_el_esquema(tmp_path):
    """El fixture estructural produce el mismo ESQUEMA de derivacion que el
    canonico real: 4 comandos/eventos de la frase de existencia + 1 codigo de
    la tabla con seccion handoff; el codigo de otra seccion queda fuera."""
    commands, stop_codes = derive_closure_verbs(MINIMAL_CANONICAL)
    assert commands == [
        "--mark-ready",
        "BUILDER_EXIT",
        "STATE_CHANGED",
        "READY_FOR_REVIEW",
    ]
    assert stop_codes == ["HANDOFF_IMPOSSIBLE"]


def test_canonico_sin_frase_de_existencia_falla_cerrado(tmp_path, capsys):
    """FAIL-CLOSED (exit 3): si el canonico reescribe la frase de existencia,
    el guard NUNCA audita con una lista vacia o parcial (eso dejaria pasar todo
    el universo); devuelve exit 3 de CONTRACT_GAP y lo dice."""
    canonico = _canonico(
        tmp_path,
        MINIMAL_CANONICAL.replace(
            "El handoff solo existe cuando", "El cierre requiere"
        ),
    )
    root = tmp_path
    _prompt(root, "PROMPT_BUILDER_WOT-2026-000g.md", f"# Prompt\n{CID_LINE}\n")
    rc, out, err = _run(root, canonico, capsys)
    assert rc == 3
    assert "CONTRACT_GAP" in err
    assert "auditado(s)" not in out, "no debe auditar con una lista rota"


def test_canonico_sin_tabla_de_codigos_falla_cerrado(tmp_path, capsys):
    """FAIL-CLOSED (exit 3), anclaje 2: sin la tabla de codigos el verbo de
    fallo del cierre (HANDOFF_IMPOSSIBLE) queda sin derivar y no se prosigue."""
    canonico = _canonico(
        tmp_path,
        MINIMAL_CANONICAL.replace(
            "## Referencia rapida: codigos de parada", "## Codigos"
        ),
    )
    rc, _out, err = _run(tmp_path, canonico, capsys)
    assert rc == 3
    assert "anclaje 2" in err


def test_canonico_con_frase_sin_comando_falla_cerrado(tmp_path, capsys):
    """FAIL-CLOSED (exit 3): una frase de existencia sin comando backticked no
    expone una obligacion ejecutable; derivar solo estados no es el contrato."""
    canonico = _canonico(
        tmp_path,
        MINIMAL_CANONICAL.replace("`--mark-ready` completa", "el comando completo"),
    )
    rc, _out, err = _run(tmp_path, canonico, capsys)
    assert rc == 3
    assert "anclaje 1 degradado" in err


def test_canonico_ilegible_es_exit_2(tmp_path, capsys):
    """El canonico inexistente no es un verde ni un CG: es exit 2 (fallo de
    lectura), distinguible del exit 3 de derivacion."""
    rc, _out, err = _run(tmp_path, tmp_path / "no" / "existe.md", capsys)
    assert rc == 2
    assert "canonico ilegible" in err


# ---------------------------------------------------------------------------
# DENOMINADOR y universo
# ---------------------------------------------------------------------------
def test_universo_vacio_es_rojo_no_verde_vacuo(tmp_path, capsys):
    """DENOMINADOR: sin prompts, exit 0 seria indistinguible de '0 hallazgos
    sobre 3'. Universo vacio es exit 1 con el error nombrado (fail-closed)."""
    canonico = _canonico(tmp_path)
    (tmp_path / ".agent" / "planning").mkdir(parents=True)
    rc, _out, err = _run(tmp_path, canonico, capsys)
    assert rc == 1
    assert "universo VACIO" in err


def test_el_denominador_se_publica_siempre(tmp_path, capsys):
    """Un probe que no publica su denominador y su lista derivada no permite
    distinguir '0 hallazgos sobre N' de 'no mire nada'."""
    canonico = _canonico(tmp_path)
    _prompt(
        tmp_path,
        "PROMPT_BUILDER_WOT-2026-000h.md",
        f"# Prompt\n{CID_LINE}\n\n{CARRYING_BLOCK}\n",
    )
    rc, out, _ = _run(tmp_path, canonico, capsys)
    assert rc == 0
    assert "1 prompt(s) auditado(s), 0 hallazgo(s)" in out
    assert "verbos derivados del canonico: --mark-ready" in out


def test_el_universo_es_por_contenido_y_cubre_staged(tmp_path):
    """El universo se selecciona por CONTENIDO (declaracion del cid como linea
    propia) y por rglob: los prompts staged de los vuelos
    (`staged/WOT-*/PROMPT_BUILDER_*.md`) entran; una mencion en prosa, un
    fichero en `_archive/` y una plantilla `{{...}}` no."""
    root = tmp_path
    _prompt(
        root,
        "staged/WOT-2026-000a/PROMPT_BUILDER_WOT-2026-000a.md",
        f"# Prompt\n{CID_LINE}\n\n{CARRYING_BLOCK}\n",
    )
    _prompt(root, "informe.md", f"El revisor cita: {CID_LINE} como contexto.\n")
    _prompt(root, "_archive/PROMPT_BUILDER_viejo.md", f"# Prompt\n{CID_LINE}\n")
    _prompt(
        root, "plantilla.md", f"Eres el BUILDER de {{{{TICKET_ID}}}}.\n{CID_LINE}\n"
    )
    findings, prompts = audit_prompt_universe(root, DERIVED_VERBS)
    assert [p.name for p in prompts] == ["PROMPT_BUILDER_WOT-2026-000a.md"]
    assert findings == []


def test_prompt_declarado_ilegible_es_hallazgo_no_silencio(tmp_path, monkeypatch):
    """FAIL-CLOSED de lectura: un prompt declarado que no se puede leer produce
    hallazgo V0; saltarselo en silencio seria un verde sobre universo podrido."""
    import check_builder_prompt_obligations as mod

    canonico = _canonico(tmp_path)
    root = tmp_path
    _prompt(root, "PROMPT_BUILDER_WOT-2026-000i.md", f"# Prompt\n{CID_LINE}\n")
    monkeypatch.setattr(mod, "_read", lambda path: None)
    findings, prompts = audit_prompt_universe(root, DERIVED_VERBS)
    assert len(prompts) == 1
    assert [f.rule for f in findings] == ["V0-ilegible"]
    assert canonico.exists()


def test_scan_prompt_no_lanza_nunca(tmp_path):
    """El guard es un detector: un fallo de lectura se reporta, no propaga."""
    assert scan_prompt(tmp_path / "inexistente.md", DERIVED_VERBS) == [
        scan_prompt(tmp_path / "inexistente.md", DERIVED_VERBS)[0]
    ]
    assert (
        scan_prompt(tmp_path / "inexistente.md", DERIVED_VERBS)[0].rule == "V0-ilegible"
    )


def test_derivation_error_es_la_excepcion_del_contrato():
    """La derivacion rota se senala con un tipo propio: main lo clasifica como
    exit 3 y el cableado de cierre lo propaga como check fallido."""
    with pytest.raises(DerivationError):
        derive_closure_verbs("un canonico sin ningun anclaje reconocible")
