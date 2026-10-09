"""Tests de la barrera del recibo DEC (WOT-2026-042x).

MUTATION en las CUATRO direcciones que exige el DoD, cada una con su node-id:

  ficha SIN recibo                  -> ROJO   test_receipt_absent_is_rejected
  recibo con DEC-<id> INEXISTENTE   -> ROJO   test_receipt_with_unknown_dec_is_rejected
  recibo con DEC-<id> existente     -> VERDE  test_receipt_with_known_dec_is_accepted
  `DEC-no-aplica: <motivo>`         -> VERDE  test_dec_no_aplica_with_motive_is_accepted

Las cuatro se ejercen sobre la funcion PURA `receipt_is_valid` y, donde el
veredicto depende del disco (grandfathering, scope no verificable), sobre
`check_file` con ficheros REALES en `tmp_path` -- no mocks: el defecto que este
guard previene vive en la frontera con ficheros de verdad.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest


_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_dec_receipt.py"
_spec = importlib.util.spec_from_file_location("check_dec_receipt", _MODULE_PATH)
assert _spec and _spec.loader
cdr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cdr)


REGISTRY = {"008B-001", "008B-002", "025H-001", "MOTOR-CHARTER-001"}


# ---------------------------------------------------------------------------
# Las CUATRO direcciones de la mutation
# ---------------------------------------------------------------------------


def test_receipt_absent_is_rejected() -> None:
    """Direccion 1: una ficha sin recibo NO pasa."""
    receipt = "Titulo: algo\nscope: motor\nDoD: binario\n"
    assert cdr.receipt_is_valid(receipt, REGISTRY) is False


def test_receipt_with_unknown_dec_is_rejected() -> None:
    """Direccion 2: citar un DEC que NO existe en el registro declarado -> ROJO.

    Es el corazon del guard: sin esto, un recibo con formato correcto y un id
    inventado pasaria, que es indistinguible de no tener barrera.
    """
    assert cdr.receipt_is_valid("DEC-999Z-001 (motor)", REGISTRY) is False


def test_receipt_with_known_dec_is_accepted() -> None:
    """Direccion 3: un DEC existente en el registro declarado -> VERDE."""
    assert cdr.receipt_is_valid("Recibo: DEC-008B-001 (motor)", REGISTRY) is True


def test_dec_no_aplica_with_motive_is_accepted() -> None:
    """Direccion 4: `DEC-no-aplica: <motivo>` con motivo escrito -> VERDE."""
    receipt = "DEC-no-aplica: el ticket no adjudica nada, solo mide un censo"
    assert cdr.receipt_is_valid(receipt, REGISTRY) is True


# ---------------------------------------------------------------------------
# Bordes de la funcion pura
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("empty_motive", ["", "   ", "n/a", "N/A", "na"])
def test_dec_no_aplica_without_motive_is_rejected(empty_motive: str) -> None:
    """`DEC-no-aplica` sin motivo es una casilla marcada, no una decision."""
    assert cdr.receipt_is_valid(f"DEC-no-aplica: {empty_motive}", REGISTRY) is False


def test_receipt_without_scope_is_rejected() -> None:
    """Un `DEC-<id>` SIN scope no es resoluble: no se sabe contra que registro va."""
    assert cdr.receipt_is_valid("DEC-008B-001", REGISTRY) is False


def test_all_cited_decs_must_exist() -> None:
    """Si el recibo cita varios ids, UNO inexistente basta para rechazar.

    Evita el falso verde de "cita algo valido, ya vale": un override que nombra
    una DEC real y otra inventada sigue siendo irresoluble.
    """
    receipt = "DEC-008B-001 (motor) supersedes: DEC-777X-001 (motor)"
    assert cdr.receipt_is_valid(receipt, REGISTRY) is False


def test_multi_segment_dec_id_is_not_truncated() -> None:
    """Regresion medida (2026-07-29): el id es `<familia>-<numero>`, no un segmento.

    Un patron de un solo segmento colapsaba `DEC-008B-001` y `DEC-008B-002` en
    `008B` -- 6 ficheros del registro real producian 5 ids -- y habria rechazado
    un recibo que cita el id COMPLETO. FAIL sin el fix, PASS con el.
    """
    assert cdr.receipt_is_valid("DEC-008B-002 (motor)", REGISTRY) is True
    assert cdr.receipt_is_valid("DEC-MOTOR-CHARTER-001 (motor)", REGISTRY) is True


# ---------------------------------------------------------------------------
# Resolucion POR SCOPE (endurecida en review) y sus asimetrias declaradas
# ---------------------------------------------------------------------------


def test_scope_selects_the_registry_cross_scope_is_rejected(tmp_path: Path) -> None:
    """El scope ELIGE el registro: citar el id del repo equivocado es ROJO.

    Regresion del review (bucle L700, 2026-07-29): tres lentes independientes y
    la refutacion final de Codex cazaron que `check_file` fusionaba los dos
    registros y `receipt_is_valid` descartaba el scope, asi que un
    `DEC-<id> (motor)` cuyo id solo vivia en el DESTINO pasaba VERDE.

    Contradecia la clausula D5 del propio prompt que este vuelo escribio: "un
    DEC-<id> que NO EXISTE en el registro que su propio scope declara es recibo
    INVALIDO". La NORMA y la BARRERA no pueden discrepar. FAIL sin el fix
    (ambos daban OK), PASS con el.
    """
    solo_destino = {"010D-001"}
    solo_motor = {"008B-001"}

    cruzado = tmp_path / "FP-20260730-cruzado.tickets.md"
    cruzado.write_text("Recibo: DEC-010D-001 (motor)\n", encoding="utf-8")
    assert cdr.check_file(cruzado, solo_motor, solo_destino)[0] == "ERROR"

    cruzado.write_text("Recibo: DEC-008B-001 (destino)\n", encoding="utf-8")
    assert cdr.check_file(cruzado, solo_motor, solo_destino)[0] == "ERROR"

    # Y cada uno contra SU registro sigue en verde (anti-falso-rojo).
    cruzado.write_text("Recibo: DEC-008B-001 (motor)\n", encoding="utf-8")
    assert cdr.check_file(cruzado, solo_motor, solo_destino)[0] == "OK"
    cruzado.write_text("Recibo: DEC-010D-001 (destino)\n", encoding="utf-8")
    assert cdr.check_file(cruzado, solo_motor, solo_destino)[0] == "OK"


def test_receipt_is_valid_accepts_scope_mapping_and_plain_set() -> None:
    """La funcion PURA admite mapping (scope-estricto) y set plano (scope-agnostico)."""
    mapping = {"motor": {"008B-001"}, "destino": {"010D-001"}}
    assert cdr.receipt_is_valid("DEC-008B-001 (motor)", mapping) is True
    assert cdr.receipt_is_valid("DEC-008B-001 (destino)", mapping) is False
    # set plano: se aplica a cualquier scope (llamante con un solo registro)
    assert cdr.receipt_is_valid("DEC-008B-001 (destino)", {"008B-001"}) is True


def test_dec_no_aplica_short_circuits_co_cited_ids() -> None:
    """PRECEDENCIA declarada: un `DEC-no-aplica` con motivo vale por si solo.

    Un id inventado que ACOMPANE al no-aplica no se caza. Se pinea porque es
    una asimetria real de la funcion pura, no un descuido: el contrato promete
    "referencia verificable U override declarado", y el no-aplica ES el
    override.
    """
    receipt = "DEC-no-aplica: no adjudica nada\nVer tambien DEC-999Z-001 (motor)"
    assert cdr.receipt_is_valid(receipt, REGISTRY) is True


def test_module_docstring_declares_scope_resolution_and_its_gap() -> None:
    """La promesa y el hueco van ESCRITOS: una promesa falsa es peor que un limite.

    El docstring debe (a) decir que resuelve POR SCOPE -- lo que el codigo hace
    de verdad tras el endurecimiento -- y (b) nombrar al dueno del hueco de
    alcance que Codex levanto (los planes de `queued/` no se miran).
    """
    source = " ".join(_MODULE_PATH.read_text(encoding="utf-8").lower().split())
    assert "su propio scope declara" in source, (
        "el docstring debe declarar que el id se resuelve contra el registro "
        "que su scope declara, no contra la union"
    )
    assert "wot-2026-043a" in source, (
        "el hueco de alcance (planes de queued/ sin mirar, buzones por ruta "
        "fija) debe salir con dueno declarado, no en silencio"
    )


# ---------------------------------------------------------------------------
# Registros reales del repo (frontera, no mocks)
# ---------------------------------------------------------------------------


def test_motor_registry_ids_round_trip_against_real_repo() -> None:
    """Todo id del registro REAL del motor valida como recibo con scope (motor).

    Un guard cuyo parser no reconoce los ids que el propio repo escribe seria un
    falso rojo permanente. Se mide contra `docs/decisions/`, no contra fixtures
    (un barrido contra tus propios fixtures mide tus fixtures).
    """
    motor_root = Path(__file__).resolve().parents[2]
    registry = cdr.load_motor_registry(motor_root)
    assert registry, "docs/decisions/ debe contener al menos una DEC"
    for dec_id in registry:
        assert cdr.receipt_is_valid(f"DEC-{dec_id} (motor)", registry) is True, (
            f"el id REAL {dec_id} no round-trip: el parser del recibo y el del "
            "registro han divergido"
        )


# ---------------------------------------------------------------------------
# Grandfathering: el anti-falso-positivo (censo medido 14/14 sin recibo)
# ---------------------------------------------------------------------------


def test_grandfather_cutoff_is_a_declared_constant() -> None:
    """La fecha esta FIJADA en el modulo, no derivada de `today()`.

    Una fecha calculada del reloj haria que el gate cambiara de veredicto solo,
    sin que nadie tocara codigo (caducidad silenciosa, `WOT-2026-024t`).
    """
    assert cdr.GRANDFATHER_CUTOFF == "2026-07-29"
    # Se mide sobre el CODIGO, no sobre el texto crudo: el propio modulo explica
    # en un comentario POR QUE no usa `today()`, y grepear el texto entero
    # convertiria esa explicacion en un falso positivo (medido 2026-07-29).
    code = "\n".join(
        line.split("#", 1)[0]
        for line in _MODULE_PATH.read_text(encoding="utf-8").splitlines()
    )
    assert "today()" not in code and "datetime.now" not in code, (
        "GRANDFATHER_CUTOFF debe ser constante declarada, nunca calculada"
    )


def test_pre_cutoff_ficha_without_receipt_warns_not_errors(tmp_path: Path) -> None:
    """Una ficha ANTERIOR al cutoff sin recibo pasa con WARN.

    Un gate que bloquease las 14 fichas preexistentes seria inservible y se le
    rodearia; ese es el fallo que este test fija.
    """
    ficha = tmp_path / "FP-20260726-041j-algo.tickets.md"
    ficha.write_text("Titulo: sin recibo\n", encoding="utf-8")
    level, _ = cdr.check_file(ficha, REGISTRY, None)
    assert level == "WARN"


def test_post_cutoff_ficha_without_receipt_errors(tmp_path: Path) -> None:
    """Una ficha con fecha IGUAL o POSTERIOR al cutoff sin recibo -> ERROR.

    Sin esta direccion el grandfathering seria una amnistia universal y el
    guard no bloquearia jamas.
    """
    ficha = tmp_path / "FP-20260730-nueva.tickets.md"
    ficha.write_text("Titulo: sin recibo\n", encoding="utf-8")
    level, _ = cdr.check_file(ficha, REGISTRY, None)
    assert level == "ERROR"


def test_ficha_on_cutoff_date_errors(tmp_path: Path) -> None:
    """El borde exacto: la fecha IGUAL al cutoff ya exige recibo (`<`, no `<=`)."""
    ficha = tmp_path / "FP-20260729-borde.tickets.md"
    ficha.write_text("Titulo: sin recibo\n", encoding="utf-8")
    level, _ = cdr.check_file(ficha, REGISTRY, None)
    assert level == "ERROR"


def test_ficha_without_parseable_date_is_not_grandfathered(tmp_path: Path) -> None:
    """Sin fecha parseable NO hay amnistia: ante duda, se exige el recibo."""
    ficha = tmp_path / "NOTE-sin-fecha.tickets.md"
    ficha.write_text("Titulo: sin recibo\n", encoding="utf-8")
    level, _ = cdr.check_file(ficha, REGISTRY, None)
    assert level == "ERROR"


# ---------------------------------------------------------------------------
# Topologia: el guard NO cruza repos
# ---------------------------------------------------------------------------


def test_destino_scope_without_registry_is_not_verifiable(tmp_path: Path) -> None:
    """Scope (destino) sin `--destino-registry` -> ERROR, nunca "valido".

    STOP condition del contrato: el registro del destino se pasa como ARGUMENTO.
    Si no se pasa, el recibo se marca NO VERIFICABLE con motivo; darlo por bueno
    seria exactamente el falso verde que la barrera existe para impedir.
    """
    ficha = tmp_path / "FP-20260730-destino.tickets.md"
    ficha.write_text("Recibo: DEC-010D-001 (destino)\n", encoding="utf-8")
    level, message = cdr.check_file(ficha, REGISTRY, None)
    assert level == "ERROR"
    assert "NO VERIFICABLE" in message


def test_destino_scope_resolves_against_passed_registry(tmp_path: Path) -> None:
    """Con el registro del destino PASADO, el scope (destino) si resuelve."""
    registry_file = tmp_path / "decisions.md"
    registry_file.write_text(
        "# Decisiones\n\n### DEC-010D-001 -- Autoridad de lectura\n\ncuerpo\n",
        encoding="utf-8",
    )
    destino = cdr.load_destino_registry(registry_file)
    assert destino == {"010D-001"}

    ficha = tmp_path / "FP-20260730-destino.tickets.md"
    ficha.write_text("Recibo: DEC-010D-001 (destino)\n", encoding="utf-8")
    level, _ = cdr.check_file(ficha, REGISTRY, destino)
    assert level == "OK"


def test_module_docstring_declares_no_topology_resolution() -> None:
    """El DoD exige que el docstring declare que NO resuelve topologia."""
    assert cdr.receipt_is_valid.__doc__ is not None
    assert "NO resuelve topologia" in cdr.receipt_is_valid.__doc__


def test_empty_inbox_skips_explicitly(capsys: pytest.CaptureFixture[str]) -> None:
    """0 fichas imprime SKIP EXPLICITO con un rc DISTINGUIBLE (no un exit 0 mudo).

    WOT-2026-067x (TT-6): el vacio deja de salir `rc=0` (indistinguible de
    "valide y paso") y publica su denominador. Cambio de contrato DELIBERADO.
    """
    rc = cdr.main(["--motor-root", str(Path(__file__).resolve().parents[2])])
    out = capsys.readouterr().out
    assert rc == cdr.EXIT_EMPTY_UNIVERSE
    assert rc != 0
    assert "SKIP EXPLICITO" in out
    assert "inspeccionados=0" in out
    assert "hits=0" in out
    assert "saltados=0" in out
    assert "lista_saltados=[]" in out


def test_universo_vacio_publica_denominador_y_rc_distinguible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D2: en el vacio el denominador completo y el rc viajan JUNTOS.

    Control de mutacion de D2: quitar cualquiera de los campos del denominador
    (o el rc distinguible) pone este test en ROJO.
    """
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    rc = cdr.main(
        [
            "--motor-root",
            str(Path(__file__).resolve().parents[2]),
            "--inbox",
            str(inbox),
        ]
    )
    out = capsys.readouterr().out
    assert rc == cdr.EXIT_EMPTY_UNIVERSE
    assert "inspeccionados=0" in out
    assert "hits=0" in out
    assert "saltados=0" in out
    assert "lista_saltados=[]" in out
    assert "No es un PASS." in out


def test_una_ficha_valida_sigue_rc_cero(tmp_path: Path) -> None:
    """Control positivo (D5): con 1 ficha valida el vacio no aplica, rc=0."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "FP-20261001-prueba.tickets.md").write_text(
        "Titulo: prueba\n**recibo:** DEC-no-aplica: no toca el motor\n",
        encoding="utf-8",
    )
    rc = cdr.main(
        [
            "--motor-root",
            str(Path(__file__).resolve().parents[2]),
            "--inbox",
            str(inbox),
        ]
    )
    assert rc == 0


def test_una_ficha_invalida_sigue_rc_uno(tmp_path: Path) -> None:
    """No-regresion (D5): una ficha SIN recibo valido sigue rc=1."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "FP-20261001-mala.tickets.md").write_text(
        "Titulo: sin recibo\nscope: motor\n", encoding="utf-8"
    )
    rc = cdr.main(
        [
            "--motor-root",
            str(Path(__file__).resolve().parents[2]),
            "--inbox",
            str(inbox),
        ]
    )
    assert rc == 1


# ---------------------------------------------------------------------------
# WOT-2026-061e: el regex y los ficheros que el motor ENSENA no pueden divergir
# ---------------------------------------------------------------------------


_MOTOR_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PROMPT = _MOTOR_ROOT / "prompts" / "contract_formation_pipeline.md"
_EXAMPLES_DIR = _MOTOR_ROOT / "docs" / "contract_formation" / "examples"


def test_schema_documentado_del_registro_es_cargable_por_el_guard() -> None:
    """D2: la cabecera del schema del prompt REAL carga con `_RE_DESTINO_HEADING`.

    El defecto original (WOT-2026-061e) vivio porque ningun test unia documento
    y regex: el prompt ensenaba un formato que el guard rechazaba. Cero
    coincidencias NO es verde: el bloque debe tener EXACTAMENTE una cabecera
    `### DEC-` y esa cabecera (con `<familia>`/`<NNN>` sustituidos) debe cargar.
    """
    lines = _SCHEMA_PROMPT.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("## 6.")]
    assert starts, "el prompt debe conservar la seccion '## 6.' con el schema"
    starts_at = starts[0]
    ends = [i for i in range(starts_at + 1, len(lines)) if lines[i].startswith("## ")]
    assert ends, "la seccion del schema debe cerrarse con otra seccion '## '"
    schema_lines = [line.strip() for line in lines[starts_at : ends[0]]]

    headings = [line for line in schema_lines if line.startswith("### DEC-")]
    assert len(headings) == 1, (
        "el bloque de schema debe tener EXACTAMENTE una cabecera '### DEC-'; "
        f"encontradas {len(headings)}: {headings}"
    )

    heading = headings[0].replace("<familia>", "RDS").replace("<NNN>", "001")
    match = cdr._RE_DESTINO_HEADING.match(heading)
    assert match is not None, (
        f"la cabecera del schema ({heading!r}) NO es cargable por el guard: el "
        "documento ensena un formato que _RE_DESTINO_HEADING rechaza"
    )
    assert match.group(1) == "RDS-001"


def test_ejemplos_de_decisions_son_cargables_por_el_guard() -> None:
    """D2: cada cabecera del ejemplo REAL carga con `_RE_DESTINO_HEADING`.

    Los ejemplos son la segunda superficie donde el motor ENSENA el formato.
    Cero ficheros o cero cabeceras no es verde (control positivo explicito).
    """
    example_files = sorted(_EXAMPLES_DIR.glob("*/decisions.md"))
    assert example_files, "debe existir al menos un ejemplo con decisions.md"

    checked = 0
    for path in example_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s.startswith("### DEC-"):
                continue
            checked += 1
            assert cdr._RE_DESTINO_HEADING.match(s) is not None, (
                f"{path.name}: la cabecera {s!r} NO es cargable por el guard; "
                "el ejemplo ensena un formato que _RE_DESTINO_HEADING rechaza"
            )
    assert checked > 0, "los ejemplos deben contener al menos una cabecera '### DEC-'"


def test_061e_el_regex_no_acepta_guion_simple_ni_id_de_un_segmento() -> None:
    """D5: el invariante del guard NO se relaja (control negativo por formato)."""
    assert cdr._RE_DESTINO_HEADING.match("### DEC-012 - x") is None
    assert cdr._RE_DESTINO_HEADING.match("### DEC-001 -- x") is None
    assert cdr._RE_DESTINO_HEADING.match("### DEC-010D-001 - x") is None


def test_061e_el_regex_acepta_familia_numero_con_doble_guion() -> None:
    """D5: el formato aceptado es `<familia>-<NNN>` con separador ` -- `."""
    assert cdr._RE_DESTINO_HEADING.match("### DEC-010D-001 -- x").group(1) == "010D-001"
    assert cdr._RE_DESTINO_HEADING.match("### DEC-RDS-001 -- x").group(1) == "RDS-001"


def _write_registry_file(path: Path, headings: list[str], newline: str = "\n") -> Path:
    path.write_text(newline.join(headings) + newline, encoding="utf-8")
    return path


def test_061e_diagnostico_12_cabeceras_en_el_formato_antiguo(tmp_path: Path) -> None:
    """D3: 12 candidatas antiguas -> (12, 0, primera); el denominador es 12."""
    headings = [f"### DEC-{i:03d} - titulo {i}" for i in range(1, 13)]
    registry = _write_registry_file(tmp_path / "decisions.md", headings)
    assert cdr.destino_heading_diagnostic(registry) == (
        12,
        0,
        "### DEC-001 - titulo 1",
    )


def test_061e_diagnostico_mezcla_cuenta_exacto(tmp_path: Path) -> None:
    """D3: la mezcla se cuenta exacta y el ejemplo es la PRIMERA no cargable."""
    headings = [
        "### DEC-001 - viejo",
        "### DEC-RDS-001 -- nuevo",
        "#### DEC-010D-002 -- anidado nuevo",
        "### DEC-002 - viejo",
        "### DEC-EX-003 -- nuevo",
    ]
    registry = _write_registry_file(tmp_path / "decisions.md", headings)
    assert cdr.destino_heading_diagnostic(registry) == (
        5,
        3,
        "### DEC-001 - viejo",
    )


def test_061e_diagnostico_todas_cargables_no_da_ejemplo(tmp_path: Path) -> None:
    """D3: si todas cargan, no hay ejemplo que publicar -> None."""
    headings = [
        "### DEC-001-001 -- a",
        "### DEC-RDS-002 -- b",
        "#### DEC-010D-003 -- c",
    ]
    registry = _write_registry_file(tmp_path / "decisions.md", headings)
    assert cdr.destino_heading_diagnostic(registry) == (3, 3, None)


def test_061e_diagnostico_sin_fichero_es_cero(tmp_path: Path) -> None:
    """D3: None y fichero ausente -> (0, 0, None) sin lanzar."""
    assert cdr.destino_heading_diagnostic(None) == (0, 0, None)
    assert cdr.destino_heading_diagnostic(tmp_path / "no_existe.md") == (0, 0, None)


def test_061e_diagnostico_con_finales_crlf_cuenta_igual_que_con_lf(
    tmp_path: Path,
) -> None:
    """D3: CRLF y LF dan el mismo recuento (splitlines + strip)."""
    headings = [
        "### DEC-001 - viejo",
        "### DEC-RDS-001 -- nuevo",
        "### DEC-002 - viejo",
    ]
    lf = _write_registry_file(tmp_path / "lf.md", headings)
    crlf = _write_registry_file(tmp_path / "crlf.md", headings, newline="\r\n")
    assert cdr.destino_heading_diagnostic(crlf) == cdr.destino_heading_diagnostic(lf)


def _run_cli_check_dec_receipt(
    registry: Path, inbox: Path
) -> subprocess.CompletedProcess[str]:
    """D6: MISMA ruta de produccion que arma `prepush_check.py` (argv identico)."""
    return subprocess.run(
        [
            sys.executable,
            str(_MODULE_PATH),
            "--motor-root",
            str(_MOTOR_ROOT),
            "--destino-registry",
            str(registry),
            "--inbox",
            str(inbox),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(_MOTOR_ROOT),
    )


def _write_ficha_061e(inbox: Path) -> Path:
    ficha = inbox / "FP-20261001-prueba.tickets.md"
    ficha.write_text(
        "Titulo: prueba\n**recibo:** DEC-012-001 (destino)\n", encoding="utf-8"
    )
    return ficha


def test_061e_cli_con_registro_no_cargable_avisa_y_sigue_fallando(
    tmp_path: Path,
) -> None:
    """D6(a): el aviso publica `0 de 3` y el recibo (destino) SIGUE fallando."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_ficha_061e(inbox)
    registry = _write_registry_file(
        tmp_path / "decisions.md",
        ["### DEC-001 - a", "### DEC-002 - b", "### DEC-003 - c"],
    )

    proc = _run_cli_check_dec_receipt(registry, inbox)

    assert proc.returncode == 1
    assert "[dec-receipt] WARN" in proc.stdout
    assert "0 de 3" in proc.stdout
    assert "[dec-receipt] ERROR" in proc.stdout


def test_061e_cli_con_registro_renombrado_valida_el_recibo(tmp_path: Path) -> None:
    """D6(b): CONTROL POSITIVO -- renombrar las cabeceras desbloquea el recibo."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_ficha_061e(inbox)
    registry = _write_registry_file(
        tmp_path / "decisions.md",
        [
            "### DEC-012-001 -- a",
            "### DEC-012-002 -- b",
            "### DEC-012-003 -- c",
        ],
    )

    proc = _run_cli_check_dec_receipt(registry, inbox)

    assert proc.returncode == 0
    assert "WARN" not in proc.stdout


def test_061e_cli_con_registro_inexistente_no_avisa_ni_lanza(tmp_path: Path) -> None:
    """D6(c): sin registro no hay aviso (0 candidatas) ni traceback."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_ficha_061e(inbox)

    proc = _run_cli_check_dec_receipt(tmp_path / "no_existe.md", inbox)

    assert proc.returncode == 1
    assert "WARN" not in proc.stdout
    assert "Traceback" not in proc.stderr


# ---------------------------------------------------------------------------
# WOT-2026-061e R2: propiedades de D4/T2 sobre el WARN (B1-B4)
# ---------------------------------------------------------------------------


def test_061e_cli_warn_linea_exacta_y_una_sola_vez(tmp_path: Path) -> None:
    """B1+B2 (D4: `EXACTAMENTE esta linea`, `UNA vez por registro`).

    B1: la igualdad de lista contra la linea LITERAL completa fija nombre del
    registro, conteo `0 de 3`, ejemplo y clausula `formato esperado`. B2: que la
    lista tenga UN solo elemento fija que el WARN sale una unica vez (la ficha
    es POST-cutoff: una anterior emitiria otro `[dec-receipt] WARN` de
    grandfathering con el mismo prefijo y falsearia la cuenta).
    """
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_ficha_061e(inbox)
    registry = _write_registry_file(
        tmp_path / "decisions.md",
        ["### DEC-001 - a", "### DEC-002 - b", "### DEC-003 - c"],
    )

    proc = _run_cli_check_dec_receipt(registry, inbox)

    warn_lines = [
        line
        for line in proc.stdout.splitlines()
        if line.startswith("[dec-receipt] WARN")
    ]
    assert proc.returncode == 1
    assert warn_lines == [
        "[dec-receipt] WARN decisions.md: 0 de 3 cabeceras 'DEC-' cargables; "
        "no cargable p.ej. '### DEC-001 - a'; formato esperado: "
        "'### DEC-<familia>-<NNN> -- <titulo>'"
    ]


def test_061e_cli_warn_sale_en_el_camino_skip(tmp_path: Path) -> None:
    """B3 (D4: `asi tambien sale en un SKIP`).

    Inbox VACIO (el directorio existe, 0 fichas): el unico camino que retorna 0
    sin validar ninguna ficha. El WARN debe salir igualmente, con la linea
    exacta, antes del `SKIP EXPLICITO`.
    """
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    registry = _write_registry_file(
        tmp_path / "decisions.md",
        ["### DEC-001 - a", "### DEC-002 - b", "### DEC-003 - c"],
    )

    proc = _run_cli_check_dec_receipt(registry, inbox)

    warn_lines = [
        line
        for line in proc.stdout.splitlines()
        if line.startswith("[dec-receipt] WARN")
    ]
    assert proc.returncode == cdr.EXIT_EMPTY_UNIVERSE
    assert warn_lines == [
        "[dec-receipt] WARN decisions.md: 0 de 3 cabeceras 'DEC-' cargables; "
        "no cargable p.ej. '### DEC-001 - a'; formato esperado: "
        "'### DEC-<familia>-<NNN> -- <titulo>'"
    ]
    assert "SKIP EXPLICITO" in proc.stdout


def test_061e_cli_warn_no_cambia_el_exit_code(tmp_path: Path) -> None:
    """B4 (T2/D4: `no cambia ningun codigo de salida`).

    Registro MIXTO y la ficha literal de D6 (recibo `DEC-012-001 (destino)`):
    el id SI existe en el registro, asi que el guard sale 0 mientras el WARN
    explica que 1 de 2 cabeceras no carga. Si el WARN abriese el guard (o
    subiese el exit), este test cae; el sentido contrario (WARN con rc=1) esta
    en el test D6(a).
    """
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_ficha_061e(inbox)
    registry = _write_registry_file(
        tmp_path / "decisions.md",
        ["### DEC-012-001 -- a", "### DEC-001 - b"],
    )

    proc = _run_cli_check_dec_receipt(registry, inbox)

    warn_lines = [
        line
        for line in proc.stdout.splitlines()
        if line.startswith("[dec-receipt] WARN")
    ]
    assert proc.returncode == 0
    assert warn_lines == [
        "[dec-receipt] WARN decisions.md: 1 de 2 cabeceras 'DEC-' cargables; "
        "no cargable p.ej. '### DEC-001 - b'; formato esperado: "
        "'### DEC-<familia>-<NNN> -- <titulo>'"
    ]
    assert "1 ok" in proc.stdout
    assert "destino=1" in proc.stdout


# ---------------------------------------------------------------------------
# WOT-2026-061e R3: instancias que D1, D3 y D4 nombran literalmente
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lineas", "esperado"),
    [
        pytest.param(
            ["####### DEC-RDS-001 -- x"],
            (0, 0, None),
            id="siete_almohadillas_no_cuentan",
        ),
        pytest.param(
            ["###### DEC-RDS-001 -- x"], (1, 1, None), id="seis_almohadillas_cuentan"
        ),
        pytest.param(["# DEC-RDS-001 -- x"], (1, 1, None), id="una_almohadilla_cuenta"),
        pytest.param(
            ["###DEC-RDS-001 -- x"], (0, 0, None), id="sin_espacio_no_es_candidata"
        ),
        pytest.param(
            ["```", "### DEC-001 - a", "```"],
            (1, 0, "### DEC-001 - a"),
            id="las_de_bloques_de_codigo_cuentan",
        ),
        pytest.param(
            ["   ### DEC-RDS-001 -- a", "\t### DEC-001 - b"],
            (2, 1, "### DEC-001 - b"),
            id="los_espacios_iniciales_se_recortan",
        ),
        pytest.param(
            ["### DEC-001 - " + "x" * 150],
            (1, 0, ("### DEC-001 - " + "x" * 150)[:100]),
            id="el_ejemplo_se_recorta_a_100",
        ),
        pytest.param(
            ["### DEC-001 - título"],
            (1, 0, "### DEC-001 - título"),
            id="se_lee_como_utf8",
        ),
    ],
)
def test_061e_diagnostico_tabla_de_instancias_de_d3(
    tmp_path: Path, lineas: list[str], esperado: tuple[int, int, str | None]
) -> None:
    """D3: cada instancia que el DoD nombra literalmente, con su resultado exacto."""
    registry = _write_registry_file(tmp_path / "decisions.md", lineas)
    assert cdr.destino_heading_diagnostic(registry) == esperado


def test_061e_diagnostico_bytes_no_utf8_no_lanza(tmp_path: Path) -> None:
    """D3: lee con `errors="replace"`, asi que un byte invalido no lanza y se cuenta."""
    registry = tmp_path / "decisions.md"
    registry.write_bytes(b"### DEC-RDS-001 -- \xff\n### DEC-001 - b\n")
    assert cdr.destino_heading_diagnostic(registry) == (2, 1, "### DEC-001 - b")


def test_061e_diagnostico_oserror_en_la_lectura_devuelve_ceros(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D3: un `OSError` al leer devuelve `(0, 0, None)` sin lanzar."""
    registry = _write_registry_file(tmp_path / "decisions.md", ["### DEC-001 - a"])

    def _lectura_imposible(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("lectura imposible")

    monkeypatch.setattr(Path, "read_text", _lectura_imposible)
    assert cdr.destino_heading_diagnostic(registry) == (0, 0, None)


def test_061e_diagnostico_es_de_solo_lectura(tmp_path: Path) -> None:
    """D3: `de solo lectura`; el fichero no cambia y no se crea nada."""
    registry = _write_registry_file(
        tmp_path / "decisions.md", ["### DEC-001 - a", "### DEC-RDS-001 -- b"]
    )
    antes = registry.read_bytes()
    cdr.destino_heading_diagnostic(registry)
    assert registry.read_bytes() == antes
    assert sorted(p.name for p in tmp_path.iterdir()) == ["decisions.md"]


def test_061e_cli_dos_fichas_emiten_el_warn_una_sola_vez(tmp_path: Path) -> None:
    """D4: `UNA vez por registro`; con 2 fichas el WARN no se repite por ficha."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for nombre in ("FP-20261001-a.tickets.md", "FP-20261001-b.tickets.md"):
        (inbox / nombre).write_text(
            "Titulo: x\n**recibo:** DEC-no-aplica: prueba\n", encoding="utf-8"
        )
    registry = _write_registry_file(
        tmp_path / "decisions.md", ["### DEC-001 - a", "### DEC-002 - b"]
    )

    proc = _run_cli_check_dec_receipt(registry, inbox)

    warn_lines = [
        line
        for line in proc.stdout.splitlines()
        if line.startswith("[dec-receipt] WARN")
    ]
    assert proc.returncode == 0
    assert len(warn_lines) == 1


def test_061e_schema_documentado_incluye_supersedes_y_la_frase_aclaratoria() -> None:
    """D1: la linea `supersedes` y la frase tras el bloque son parte de lo ensenado."""
    texto = " ".join(_SCHEMA_PROMPT.read_text(encoding="utf-8").split())
    assert "- supersedes: DEC-<familia>-<NNN> | -" in texto
    assert "(por ejemplo `010D-001` o `RDS-001`)" in texto
    assert "el separador es ` -- `" in texto
    assert "un id de un solo segmento como `DEC-012` no se carga" in texto


def test_061e_ejemplo_no_conserva_ids_de_un_segmento_y_el_catalogo_cita_ids_que_existen() -> (
    None
):
    """D1(b): ni decisions.md ni evidence_catalog.md conservan `DEC-00[12]`; el catalogo cita ids reales."""
    base = _EXAMPLES_DIR / "python_service_minimal"
    decisions = (base / "decisions.md").read_text(encoding="utf-8")
    catalog = (base / "evidence_catalog.md").read_text(encoding="utf-8")
    for texto in (decisions, catalog):
        assert re.search(r"DEC-00[12]", texto) is None

    headers = {
        match.group(1)
        for match in (
            cdr._RE_DESTINO_HEADING.match(line.strip())
            for line in decisions.splitlines()
        )
        if match
    }
    cited = set(re.findall(r"DEC-([A-Z0-9]+-\d+)", catalog))
    assert cited, "el catalogo debe citar al menos un DEC-<familia>-<NNN>"
    assert cited <= headers


def test_061e_cli_warn_precede_a_la_linea_skip(tmp_path: Path) -> None:
    """B3 (docstring: `antes del SKIP EXPLICITO`): el orden se asierta, no solo la presencia."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    registry = _write_registry_file(
        tmp_path / "decisions.md",
        ["### DEC-001 - a", "### DEC-002 - b", "### DEC-003 - c"],
    )

    proc = _run_cli_check_dec_receipt(registry, inbox)

    assert proc.returncode == cdr.EXIT_EMPTY_UNIVERSE
    assert proc.stdout.index("[dec-receipt] WARN") < proc.stdout.index("SKIP EXPLICITO")


# ---------------------------------------------------------------------------
# WOT-2026-061e R4: la clausula `DEC-` de la candidata y los marcadores de D1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lineas", "esperado"),
    [
        pytest.param(
            ["## Notas", "### DEC-001 - a"],
            (1, 0, "### DEC-001 - a"),
            id="una_cabecera_sin_dec_no_es_candidata",
        ),
        pytest.param(
            ["### DECISION-001 - a"],
            (0, 0, None),
            id="sin_guion_tras_dec_no_es_candidata",
        ),
        pytest.param(
            ["### dec-001 - a"], (0, 0, None), id="dec_en_minusculas_no_es_candidata"
        ),
    ],
)
def test_061e_diagnostico_solo_cuenta_cabeceras_dec(
    tmp_path: Path, lineas: list[str], esperado: tuple[int, int, str | None]
) -> None:
    r"""D3: la candidata casa `^#{1,6}\s+DEC-` literal (con `DEC-` en mayusculas y con guion)."""
    registry = _write_registry_file(tmp_path / "decisions.md", lineas)
    assert cdr.destino_heading_diagnostic(registry) == esperado


def test_061e_schema_conserva_los_marcadores_literales_y_nombra_el_guard() -> None:
    """D1: la cabecera del schema conserva `<familia>` y `<NNN>` LITERALES y la frase nombra el guard."""
    texto = " ".join(_SCHEMA_PROMPT.read_text(encoding="utf-8").split())
    assert "### DEC-<familia>-<NNN> -- <titulo corto>" in texto
    assert "`scripts/check_dec_receipt.py` solo carga cabeceras de ese formato" in texto


# ---------------------------------------------------------------------------
# WOT-2026-061e R5: pines de COMPORTAMIENTO (K1, K2, K5) y de lo que el
# DOCUMENTO enseña (K3/K3b, K4) sobre las mutaciones supervivientes del censo
# independiente de 221 mutaciones del Manager.
# ---------------------------------------------------------------------------

_WARN_UN_CABECERA = (
    "[dec-receipt] WARN decisions.md: 0 de 1 cabeceras 'DEC-' cargables; "
    "no cargable p.ej. '### DEC-001 - a'; formato esperado: "
    "'### DEC-<familia>-<NNN> -- <titulo>'"
)


def test_061e_cli_warn_sale_con_una_sola_cabecera_antigua(tmp_path: Path) -> None:
    """D4: `solo si candidatas > cargables`; el borde n=1 (0 de 1) tambien avisa."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "FP-20261001-a.tickets.md").write_text(
        "Titulo: x\n**recibo:** DEC-no-aplica: prueba\n", encoding="utf-8"
    )
    registry = _write_registry_file(tmp_path / "decisions.md", ["### DEC-001 - a"])

    proc = _run_cli_check_dec_receipt(registry, inbox)

    warn_lines = [
        line
        for line in proc.stdout.splitlines()
        if line.startswith("[dec-receipt] WARN")
    ]
    assert proc.returncode == 0
    assert warn_lines == [_WARN_UN_CABECERA]


def test_061e_cli_con_registro_inexistente_es_no_verificable(
    tmp_path: Path,
) -> None:
    """D6(c): un recibo `(destino)` sin registro es NO VERIFICABLE, no un ERROR de `sin recibo`."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_ficha_061e(inbox)

    proc = _run_cli_check_dec_receipt(tmp_path / "no_existe.md", inbox)

    assert proc.returncode == 1
    assert "NO VERIFICABLE" in proc.stdout
    assert "destino=no pasado" in proc.stdout


def test_061e_diagnostico_no_cuenta_prosa_sin_almohadilla(
    tmp_path: Path,
) -> None:
    """D3: la candidata exige `#` al principio; una linea de prosa que empieza por `DEC-` no cuenta."""
    registry = _write_registry_file(
        tmp_path / "decisions.md", ["DEC-001 - nota en prosa", "### DEC-001 - a"]
    )
    assert cdr.destino_heading_diagnostic(registry) == (1, 0, "### DEC-001 - a")


def test_061e_schema_ensena_el_id_familia_nnn_justo_despues_del_bloque() -> None:
    """D1: la frase dice que el id es `<familia>-<NNN>` y va INMEDIATAMENTE despues del bloque del schema."""
    texto = " ".join(_SCHEMA_PROMPT.read_text(encoding="utf-8").split())
    assert "El id de la cabecera es `<familia>-<NNN>` (por ejemplo" in texto
    assert "- date: YYYY-MM-DD ``` El id de la cabecera es `<familia>-<NNN>`" in texto


def test_061e_ninguna_cabecera_antigua_en_todo_el_prompt() -> None:
    """D1(a): el `grep -c` es sobre el FICHERO entero: 0 cabeceras antiguas y exactamente 1 nueva."""
    lineas = _SCHEMA_PROMPT.read_text(encoding="utf-8").splitlines()
    assert [ln for ln in lineas if ln.startswith("### DEC-001 - ")] == []
    nuevas = [
        ln
        for ln in lineas
        if ln.startswith("### DEC-<familia>-<NNN> -- <titulo corto>")
    ]
    assert len(nuevas) == 1
