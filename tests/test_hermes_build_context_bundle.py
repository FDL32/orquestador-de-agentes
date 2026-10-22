from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from scripts import hermes_build_context_bundle


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _write_motor_fixture(root: Path) -> None:
    (root / "prompts").mkdir(parents=True)
    (root / "AGENTS.md").write_text(
        """# Agents

## Vocabulario canonico
repo_motor y repo_destino.

## CEM v0 - Contrato, Evidencia y Memoria
Evidencia antes que relato.

## Secretos y seguridad
No exponer secretos.

## Siguiente
Fin.
""",
        encoding="utf-8",
    )
    (root / "prompts" / "orchestrator_destination_bootstrap.md").write_text(
        "# Destination Bootstrap\n\nUsa AGENT_PROJECT_ROOT.\n", encoding="utf-8"
    )
    (root / "prompts" / "orchestrator_session_close_chat.md").write_text(
        "# Session Close\n\nEjecuta dry-run antes del cierre.\n", encoding="utf-8"
    )
    (root / "prompts" / "hermes_soul.md").write_text(
        "# Hermes Soul\n\nNo aceptes relato como evidencia.\n", encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "motor"\nversion = "9.17.1"\n', encoding="utf-8"
    )
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test User")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")


def test_build_bundle_writes_versioned_hashed_artifacts(tmp_path: Path) -> None:
    motor = tmp_path / "motor"
    output = tmp_path / "hermes" / "uploads"
    soul = tmp_path / "hermes" / "soul.md"
    motor.mkdir()
    _write_motor_fixture(motor)

    manifest = hermes_build_context_bundle.build_bundle(
        motor,
        output,
        soul_output=soul,
        generated_at="2026-06-20T12:00:00+00:00",
    )

    context = (output / "01_motor_context.md").read_text(encoding="utf-8")
    closeout = (output / "30_closeout_checklist.md").read_text(encoding="utf-8")
    disk_manifest = json.loads(
        (output / "bundle_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == disk_manifest
    assert manifest["motor_version"] == "v9.17.1"
    assert len(manifest["source_commit"]) == 40
    assert manifest["source_tree_dirty"] is False
    assert manifest["source_status"] == []
    assert "repo_motor y repo_destino" in context
    assert "Model B" not in context
    assert "Ejecuta dry-run" in closeout
    assert soul.read_text(encoding="utf-8").startswith("# Hermes Soul")
    for record in manifest["generated_files"][:2]:
        path = output / record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_build_bundle_fails_when_required_section_is_missing(tmp_path: Path) -> None:
    motor = tmp_path / "motor"
    motor.mkdir()
    _write_motor_fixture(motor)
    (motor / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Required section not found"):
        hermes_build_context_bundle.build_bundle(motor, tmp_path / "out")


# ---------------------------------------------------------------------------
# WOT-2026-036g: el lector ancla por REGISTRY, no por header exacto.
# ROJO MEDIDO 2026-08-27: `_extract_section` hacia `lines.index(heading)` --
# igualdad literal de la linea entera -- asi que un renombrado CONSERVADOR
# ("## Vocabulario canonico" -> "## Vocabulario Canonico"), o un simple
# ESPACIO FINAL invisible, rompian el bundle con ValueError.
# ---------------------------------------------------------------------------

_VOCAB_DOC = "# T\n\n## Vocabulario canonico\n\ncuerpo A\n\n## Otra\n\nx\n"


def test_036g_registry_existe_y_saca_los_literales_del_hot_path() -> None:
    """El registry es la lista CERRADA de secciones que el bundle necesita."""
    import scripts.hermes_build_context_bundle as mod

    ids = [sid for sid, _, _ in mod.AGENTS_SECTIONS_REGISTRY]
    assert ids == ["vocabulario_canonico", "cem_v0", "secretos_y_seguridad"]

    # Los titulos literales solo pueden vivir en el REGISTRY (como patron).
    # Si reaparecen como argumento de una llamada de extraccion, el hot-path
    # volvio a anclar por header exacto y esta mutacion debe verse.
    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert '_extract_section(agents, "##' not in source, (
        "el hot-path volvio a anclar por titulo literal; debe usar el registry"
    )
    # WOT-2026-114a: el invariante ya no es "3 llamadas con este texto
    # literal" (fragil ante refactors de la indireccion por `source`) sino
    # "los 3 ids resuelven cada uno desde su `source` declarada en el
    # registro, y ningun id carece de `source`".
    for sid, _, registered_source in mod.AGENTS_SECTIONS_REGISTRY:
        assert registered_source, f"{sid} no declara source"
        assert mod._registered_section_source(sid) == registered_source


def test_036g_renombrado_conservador_ya_no_rompe_el_lector() -> None:
    """La MUTACION del ticket: renombrar el header sin tocar el registry.

    Con el lector viejo (`lines.index`) cada una de estas variantes lanzaba
    ValueError. Con el registry, las tres resuelven.
    """
    import scripts.hermes_build_context_bundle as mod

    variantes = (
        "## Vocabulario Canonico",  # capitalizacion
        "## Vocabulario canonico  ",  # espacio final invisible
        "##  Vocabulario  canonico",  # espaciado interno
    )
    for variante in variantes:
        doc = _VOCAB_DOC.replace("## Vocabulario canonico", variante)
        seccion = mod._extract_registered_section(doc, "vocabulario_canonico")
        assert "cuerpo A" in seccion, f"la variante {variante!r} no resolvio"


def test_036g_tolerante_no_es_laxo_una_seccion_distinta_no_se_cuela() -> None:
    """Tolerar tipografia no es tolerar OTRA seccion."""
    import scripts.hermes_build_context_bundle as mod

    doc = _VOCAB_DOC.replace("## Vocabulario canonico", "## Vocabulario extendido")
    with pytest.raises(ValueError):
        mod._extract_registered_section(doc, "vocabulario_canonico")


def test_036g_error_nombra_el_id_y_el_patron() -> None:
    """Un fallo debe distinguir 'renombrado de mas' de 'id mal escrito'."""
    import scripts.hermes_build_context_bundle as mod

    with pytest.raises(ValueError, match="vocabulario_canonico"):
        mod._extract_registered_section("# nada\n", "vocabulario_canonico")
    with pytest.raises(ValueError, match="Unknown section id"):
        mod._extract_registered_section(_VOCAB_DOC, "no_registrado")


def test_036g_las_tres_anclas_reales_resuelven_contra_agents_md() -> None:
    """Control de realidad: el registry sirve para el fichero de verdad."""
    import scripts.hermes_build_context_bundle as mod

    agents = (Path(mod.__file__).resolve().parents[1] / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    for sid, _, _ in mod.AGENTS_SECTIONS_REGISTRY:
        assert mod._extract_registered_section(agents, sid).strip(), sid


# ---------------------------------------------------------------------------
# WOT-2026-114a (Fase 1 Palanca A): registro re-apuntable por `source`.
# docs/followups/palanca-a-raiz-agents-md-diseno.md Seccion 4, D1/D1-bis/D2.
# ---------------------------------------------------------------------------


def test_114a_manifiesto_cubre_cada_source_distinta_del_registro(
    tmp_path: Path,
) -> None:
    """D1-bis: `source_files` del manifiesto debe incluir TODA `source`
    distinta declarada en el registro, no solo los 4 ficheros hardcodeados
    historicos. Hoy las tres colapsan en "AGENTS.md" (ya cubierto); esto fija
    el invariante por el que una fase futura que repunte una seccion a un
    modulo nuevo entra aqui sin que nadie edite build_bundle a mano."""
    motor = tmp_path / "motor"
    motor.mkdir()
    _write_motor_fixture(motor)

    manifest = hermes_build_context_bundle.build_bundle(motor, tmp_path / "out")

    hashed_paths = {record["path"] for record in manifest["source_files"]}
    for registry_source in hermes_build_context_bundle._registry_sources():
        assert registry_source in hashed_paths, (
            f"{registry_source!r} no aparece en source_files del manifiesto"
        )


def test_114a_baseline_e7_indireccion_identica_a_lectura_directa(
    tmp_path: Path,
) -> None:
    """D2/E7: para CADA id registrado, resolver por indireccion (`source`)
    debe devolver una seccion BYTE-IDENTICA (sha256) a extraerla leyendo
    AGENTS.md directamente -- el guard de no-degradacion que una fase futura
    (repuntar `source` a un modulo) tiene que seguir satisfaciendo."""
    motor = tmp_path / "motor"
    motor.mkdir()
    _write_motor_fixture(motor)
    agents_text = (motor / "AGENTS.md").read_text(encoding="utf-8")

    for sid, _, _ in hermes_build_context_bundle.AGENTS_SECTIONS_REGISTRY:
        direct = hermes_build_context_bundle._extract_registered_section(
            agents_text, sid
        )
        via_registry = hermes_build_context_bundle._read_registered_section(motor, sid)
        assert hashlib.sha256(via_registry.encode("utf-8")).hexdigest() == (
            hashlib.sha256(direct.encode("utf-8")).hexdigest()
        ), f"{sid}: la indireccion por source diverge de la lectura directa"
        assert via_registry == direct


def test_114a_mutacion_fuente_no_registrada_se_detecta(tmp_path: Path) -> None:
    """Mutacion obligatoria del guard E7: si `source` apuntara a un fichero
    con contenido DISTINTO del AGENTS.md real, la indireccion debe devolver
    ese contenido distinto (prueba de que el campo `source` esta REALMENTE
    cableado al hot-path, no un campo muerto que nadie lee)."""
    motor = tmp_path / "motor"
    motor.mkdir()
    _write_motor_fixture(motor)

    mutated_source = motor / "AGENTS_MUTATED.md"
    mutated_source.write_text(
        "# Agents\n\n## Vocabulario canonico\nCUERPO MUTADO.\n",
        encoding="utf-8",
    )

    original = hermes_build_context_bundle.AGENTS_SECTIONS_REGISTRY
    try:
        hermes_build_context_bundle.AGENTS_SECTIONS_REGISTRY = tuple(
            (sid, pattern, "AGENTS_MUTATED.md")
            if sid == "vocabulario_canonico"
            else (sid, pattern, source)
            for sid, pattern, source in original
        )
        hermes_build_context_bundle._REGISTRY_BY_ID = {
            sid: (pattern, source)
            for sid, pattern, source in hermes_build_context_bundle.AGENTS_SECTIONS_REGISTRY
        }
        seccion = hermes_build_context_bundle._read_registered_section(
            motor, "vocabulario_canonico"
        )
        assert "CUERPO MUTADO" in seccion
        assert "repo_motor y repo_destino" not in seccion
    finally:
        hermes_build_context_bundle.AGENTS_SECTIONS_REGISTRY = original
        hermes_build_context_bundle._REGISTRY_BY_ID = {
            sid: (pattern, source) for sid, pattern, source in original
        }
