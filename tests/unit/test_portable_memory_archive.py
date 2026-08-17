"""WOT-2026-024r (A1): el loader LEE el archive portable tracked.

Hasta este ticket la memoria portable se escribia, se versionaba y se pusheaba --
y nadie la leia de vuelta. Los 4 consumidores medidos del archive
(`check_portable_memory_archive_schema`, `check_portable_memory_promotion`,
`prepush_check`, `reconcile_portable_memory`) son guards y reconciliadores:
ninguno CONSUME. Coste medido (2026-07-27): una leccion guardada DOS veces se
reincidio igual y destruyo 7 tests. No fue laguna de memoria: fue memoria
escrita, versionada y NO LEIDA.

Las tres mutaciones del DoD estan implementadas como tests, no descritas:
  (i)   archive vacio            -> el test de comportamiento CAE.
  (ii)  sin L1/L2/L3, con archive -> SIGUE PASANDO. Es la que mata el falso
        verde: sin ella el DoD no se distingue del estado anterior, porque el
        contexto podria venir de la proyeccion gitignored.
  (iii) precedencia contra FIXTURE AISLADO -> gana L1.

PROHIBIDO medir la precedencia contra el `observations.jsonl` VIVO: el hook
`post_tool_hook.py` lo abre en modo APPEND, asi que puede crecer DURANTE la
medicion y el canario ganaria por una linea que llego despues, no por la logica.
El modo de fallo es asimetrico -- produce falso VERDE, no rojo.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bus import memory_loader  # noqa: E402
from bus.portable_memory_archive import (  # noqa: E402
    CorruptArchiveError,
    dedup_key,
    iter_archive_months,
    read_archive_observations,
)


def _observation(
    canary: str, topic: str = "lesson", ticket: str = "WOT-2026-024r"
) -> dict:
    return {
        "id": canary,
        "timestamp": "2026-07-28T00:00:00+00:00",
        "topic": topic,
        "signal": f"canario {canary}",
        "source": "test",
        "source_ticket": ticket,
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Un repo HERMETICO con `.git` PROPIO y solo el archive portable.

    El `git init` no es ceremonia: sin `.git` propio, el walk-up de git alcanza
    el repo REAL y el fixture deja de ser hermetico -- ya refutado en este repo.
    """
    root = tmp_path / "fixture_repo"
    (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q"],
        cwd=str(root),
        check=True,
        capture_output=True,
    )
    return root


@pytest.fixture
def wired(repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Apunta el loader al fixture parcheando UNA sola cosa: `get_agent_dir`.

    Deliberadamente NO se parchea `_get_repo_root`: ese patch era REDUNDANTE
    (medido en review -- los 10 tests pasan igual sin el) porque la produccion
    deriva la raiz de `_get_memory_dir()`. Un mock redundante es justo lo que
    enmascara una ruta real rota: si manana alguien volviera a resolver la raiz
    por su cuenta -- reintroduciendo la fuga de aislamiento que este ticket ya
    corrigio una vez --, con el patch puesto estos tests seguirian verdes.
    Sin el, se ponen rojos.
    """
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: repo / ".agent")
    return repo


def _archive(repo: Path) -> Path:
    return repo / ".agent/runtime/memory/archive/observations.2026-07.jsonl"


# --- DoD.1: comportamiento, con RECIBO de hermeticidad --------------------


def test_bootstrap_context_contains_archive_canary(wired: Path):
    """Archive con canario y CERO L1/L2/L3 -> el uuid llega al contexto.

    Recibo obligatorio: imprime `git rev-parse --show-toplevel` y asserta que
    resuelve AL FIXTURE. Sin este assert, un fixture no hermetico daria verde
    leyendo el repo real.
    """
    canary = f"CANARY-024R-{uuid.uuid4()}"
    _write_jsonl(_archive(wired), [_observation(canary)])

    toplevel = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(wired),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    print(f"RECIBO git rev-parse --show-toplevel = {toplevel}")
    assert Path(toplevel).resolve() == wired.resolve(), (
        "el fixture NO es hermetico: el walk-up de git alcanzo otro repo"
    )

    # Cero proyecciones: lo unico que puede aportar el canario es el archive.
    assert not memory_loader._get_profile_file().exists()
    assert not memory_loader._get_rules_file().exists()
    assert not memory_loader._get_observations_file().exists()

    assert canary in memory_loader.get_bootstrap_context()


# --- DoD.3: MUTACION (i) -- archive vacio -> ROJO -------------------------


def test_mutation_i_empty_archive_loses_the_canary(wired: Path):
    """Trunca el archive: el canario desaparece del contexto.

    Es la mutacion que demuestra que el verde de arriba viene DEL ARCHIVE.
    """
    canary = f"CANARY-024R-{uuid.uuid4()}"
    archive = _archive(wired)
    _write_jsonl(archive, [_observation(canary)])
    assert canary in memory_loader.get_bootstrap_context()  # antes de mutar

    archive.write_text("", encoding="utf-8")  # MUTACION
    assert canary not in memory_loader.get_bootstrap_context()

    _write_jsonl(archive, [_observation(canary)])  # restauracion declarada
    assert canary in memory_loader.get_bootstrap_context()


# --- DoD.4: MUTACION (ii) -- la que mata el falso verde -------------------


def test_mutation_ii_archive_survives_without_projections(wired: Path):
    """Borrar L1/L2/L3 dejando el archive -> SIGUE PASANDO.

    Sin esta mutacion el DoD seria indistinguible del estado ANTERIOR al
    ticket: el contexto podria estar viniendo de la proyeccion gitignored y
    nadie lo notaria. Aqui las tres proyecciones se crean y se borran, asi que
    el unico origen posible del canario es el archive tracked.
    """
    canary = f"CANARY-024R-{uuid.uuid4()}"
    _write_jsonl(_archive(wired), [_observation(canary)])

    profile = memory_loader._get_profile_file()
    rules = memory_loader._get_rules_file()
    obs = memory_loader._get_observations_file()
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("# L3 profile\n", encoding="utf-8")
    rules.write_text("# L2 rules\n", encoding="utf-8")
    _write_jsonl(obs, [_observation("L1-entry", topic="otro")])
    assert canary in memory_loader.get_bootstrap_context()

    for path in (profile, rules, obs):  # MUTACION
        path.unlink()
    assert canary in memory_loader.get_bootstrap_context(), (
        "el archive dejo de alcanzar el contexto sin las proyecciones: el "
        "verde anterior venia de la proyeccion gitignored, no del archive"
    )


# --- DoD.5: MUTACION (iii) -- precedencia, FIXTURE AISLADO ---------------


def test_mutation_iii_live_l1_wins_over_archived_copy(wired: Path):
    """Misma entrada (mismo `id`) en archive y en L1 VIVO -> gana L1.

    Medido contra fixture AISLADO, nunca contra el `observations.jsonl` real:
    ese fichero lo abre en APPEND `post_tool_hook.py`, y si un vuelo ajeno esta
    activo appendea durante la medicion -> el canario ganaria por una linea que
    llego despues, no por la logica de precedencia (falso VERDE).
    """
    shared_id = f"CANARY-024R-{uuid.uuid4()}"
    archived = _observation(shared_id)
    archived["signal"] = "VERSION ARCHIVADA"
    live = _observation(shared_id)
    live["signal"] = "VERSION VIVA"

    _write_jsonl(_archive(wired), [archived])
    _write_jsonl(memory_loader._get_observations_file(), [live])

    assert dedup_key(archived) == dedup_key(live), "el fixture no colisiona"

    context = memory_loader.get_bootstrap_context()
    assert "VERSION VIVA" in context
    assert "VERSION ARCHIVADA" not in context, (
        "gano la copia archivada: L1 es la copia viva y pudo editarse despues"
    )


# --- El modulo extraido ---------------------------------------------------


def test_reads_every_month_not_only_the_current(wired: Path):
    """La convencion es mes-a-mes y hay que recorrer TODOS los meses.

    Una leccion promovida un mes anterior ya viajo; ignorarla la haria
    invisible al lector aunque este versionada.
    """
    old = f"CANARY-024R-{uuid.uuid4()}"
    new = f"CANARY-024R-{uuid.uuid4()}"
    base = _archive(wired).parent
    _write_jsonl(base / "observations.2026-06.jsonl", [_observation(old)])
    _write_jsonl(base / "observations.2026-07.jsonl", [_observation(new)])

    assert len(iter_archive_months(wired)) == 2
    context = memory_loader.get_bootstrap_context()
    assert old in context and new in context


def test_missing_archive_dir_is_empty_not_an_error(tmp_path: Path):
    """Un repo sin memoria portable es legitimo, no un fallo."""
    assert read_archive_observations(tmp_path) == []
    assert iter_archive_months(tmp_path) == []


def test_corrupt_archive_raises_with_file_and_line(repo: Path):
    """JSONL roto -> error explicito con fichero y linea, no traceback opaco."""
    _archive(repo).parent.mkdir(parents=True, exist_ok=True)
    _archive(repo).write_text(
        '{"topic":"ok","source_ticket":"T-1"}\n{ROTO\n', encoding="utf-8"
    )
    with pytest.raises(CorruptArchiveError) as exc:
        read_archive_observations(repo)
    assert "observations.2026-07.jsonl:2" in str(exc.value)


def test_loader_degrades_instead_of_breaking_on_corrupt_archive(wired: Path):
    """El loader nunca revienta: contrato "never raises" del modulo.

    La barrera fail-CLOSED de un archive corrupto es
    `validate_observations --strict` (cableada en prepush), no el loader: si el
    loader lanzara, un archive roto romperia bootstrap, review bridge y
    pre-compact hook a la vez.
    """
    _archive(wired).write_text("{ROTO\n", encoding="utf-8")
    assert memory_loader.get_bootstrap_context() == ""


def test_dedup_key_prefers_stable_id_and_falls_back():
    """`id` estable cuando existe; si no, la clave de reconcile + timestamp.

    143 de 153 entradas del archive real tienen `id` (medido 2026-07-28); las
    10 restantes no pueden distinguirse sin inventar schema, que es NON-GOAL.
    """
    with_id = _observation("ID-1")
    assert dedup_key(with_id) == ("id", "ID-1")

    without = {"topic": "t", "source_ticket": "WOT-1", "timestamp": "2026-07-28"}
    assert dedup_key(without) == ("fallback", "t", "WOT-1", "2026-07-28")


# --- DoD.2: invariante contra el archive REAL -----------------------------


def test_real_archive_entries_reach_the_context():
    """INVARIANTE, no medicion: el contenido del archive REAL llega al contexto.

    No fija QUE entrada: cualquier id o ticket concreto caduca solo en cuanto
    alguien consolide. Corre contra el repo real (sin fixture) porque es la
    prueba de equivalencia de ruta productiva: el loader real sobre el archive
    real.

    Se mide por `source_ticket` + `signal`, NO por `id`: medido 2026-07-28, las
    153 entradas del archive tienen `source_ticket`, asi que el formateador
    imprime el ticket y el `id` solo aparece si esta embebido en el texto de la
    senal. Un invariante sobre `id` pasaba por COINCIDENCIA (1 de 93 entradas
    exclusivas del archive), que es la clase de verde que este ticket existe
    para eliminar.
    """
    archived = read_archive_observations(_ROOT)
    if not archived:
        pytest.skip("el motor no tiene archive portable en este checkout")

    context = memory_loader.get_bootstrap_context()
    reached = [
        r
        for r in archived
        if str(r.get("signal") or "")[:60] and str(r.get("signal"))[:60] in context
    ]
    assert reached, (
        "ninguna senal del archive tracked aparece en el contexto: el puente "
        "archive -> contexto no existe"
    )
    # WOT-2026-057a: el umbral pasa de "la mitad del archive" a "el indice va
    # LLENO y DECLARA el resto". El invariante que este test protege -- que
    # nada FILTRE la memoria portable en silencio -- sigue intacto; lo que
    # cambia es que el indice ya no pretende ser el corpus entero.
    #
    # Por que cambia: unir motor+destino (el fix de D1) llevo el corpus de 135
    # a 342 entradas y el bootstrap a ~28.7k tokens. Un indice sin tope crece
    # con el corpus (~52 entradas/mes), asi que se acota por RECENCIA y se
    # declara el resto. Un recorte DECLARADO es shaping; uno silencioso seria
    # el defecto que este ticket corrige.
    esperado = min(len(archived), memory_loader._BOOTSTRAP_INDEX_CAP)
    assert len(reached) >= esperado // 2, (
        f"solo {len(reached)} de {len(archived)} entradas llegan al contexto "
        f"(cap del indice: {memory_loader._BOOTSTRAP_INDEX_CAP}): algo esta "
        "filtrando la memoria portable por encima del shaping declarado"
    )
    if len(archived) > memory_loader._BOOTSTRAP_INDEX_CAP:
        assert "no mostrada" in context, (
            "el indice recorta pero NO lo declara: un agente creeria que el "
            "corpus entero cabe en lo que ve"
        )


# --- WOT-2026-047d: la puerta de RECALL tambien lee el archive ------------
#
# `get_bootstrap_context` (A1, arriba) es UNA de las dos puertas de memoria.
# La otra es `recall_observations`, y hasta este ticket delegaba entera en
# `_read_observations` -> `observations.jsonl`, el buffer GITIGNORED. Medido el
# 2026-08-03 sobre el repo real: L1 tenia 427 entradas de las que 343 (80%) eran
# telemetria de `post_tool_hook`, mientras el archive TRACKED tenia 174 lecciones
# y CERO telemetria. No son subconjunto: el recall no alcanzaba ni una de las
# entradas que viajan por git. `f6e9068` mando a los builders de Kilo y Codex
# exactamente a esa funcion.


def test_recall_reaches_a_lesson_only_in_the_archive(wired: Path):
    """DoD.2 -- una leccion AUSENTE de L1 se encuentra por `--query`.

    Mutacion (1): si `recall_observations` vuelve a leer solo L1, el canario del
    archive desaparece y este test cae. Es la mutacion INDEPENDIENTE de la de
    telemetria: aqui no hay ningun record de `post_tool_hook`.

    L1 existe y NO esta vacio a proposito: un L1 ausente haria pasar el test por
    un fallback trivial en vez de por la union real de las dos fuentes.
    """
    canary = f"CANARY-047D-{uuid.uuid4()}"
    _write_jsonl(_archive(wired), [_observation(canary, topic="lesson")])
    _write_jsonl(
        memory_loader._get_observations_file(),
        [_observation("OTRA-ENTRADA-VIVA", topic="lesson")],
    )

    hits = memory_loader.recall_observations(query=canary, limit=50)

    assert [h for h in hits if h.get("id") == canary], (
        f"la leccion {canary} vive SOLO en el archive tracked y el recall no la "
        "encuentra: la puerta de recall sigue ciega a la memoria portable"
    )


def test_recall_drops_hook_telemetry(wired: Path):
    """DoD.3 -- la telemetria de `post_tool_hook` NO sale en el recall.

    Mutacion (3) INDEPENDIENTE de la (1): aqui el canario de telemetria vive en
    L1, asi que revertir SOLO el filtro pone este test rojo sin tocar el de
    arriba.

    Discrimina por PROCEDENCIA (`is_lesson`), nunca por la etiqueta: un record
    con el mismo `topic` pero con `id`/`source_ticket` es una leccion legitima y
    DEBE seguir apareciendo. Esa segunda mitad es lo que impide que el filtro se
    convierta en un falso NEGATIVO silencioso.
    """
    marker = f"MARCA-047D-{uuid.uuid4()}"
    telemetry = {
        "timestamp": "2026-08-03T00:00:00+00:00",
        "topic": "tool_usage",
        "signal": f"{marker} telemetria mecanica",
        "source": "post_tool_hook",
    }
    # Mismo topic y misma marca, pero CON identidad promovible: es leccion.
    real_lesson = {
        "id": f"LECCION-{marker}",
        "timestamp": "2026-08-03T00:00:00+00:00",
        "topic": "tool_usage",
        "signal": f"{marker} leccion legitima sobre uso de herramientas",
        "source": "post_tool_hook",
        "source_ticket": "WOT-2026-047d",
    }
    _write_jsonl(memory_loader._get_observations_file(), [telemetry, real_lesson])

    hits = memory_loader.recall_observations(query=marker, limit=50)

    assert not [h for h in hits if h.get("signal") == telemetry["signal"]], (
        "la telemetria de post_tool_hook aparece en el recall: es el 80% de L1 "
        "y ahoga las lecciones reales"
    )
    assert [h for h in hits if h.get("id") == real_lesson["id"]], (
        "se filtro una LECCION legitima por compartir `topic` con la "
        "telemetria: el filtro discrimina por etiqueta, no por procedencia"
    )


def test_live_entry_that_stopped_being_a_lesson_still_wins(wired: Path):
    """La precedencia por-entrada se mide contra L1 COMPLETO, no contra el filtrado.

    Hallazgo del bucle L800/BA05 (codex), reproducido con probe antes de
    corregir: si una entrada VIVA deja de ser leccion (se reescribio con un
    topic autogenerado), desaparecia de la lista filtrada y por tanto de `seen`
    -- y entonces el archive REINTRODUCIA su copia vieja. El resultado era el
    opuesto exacto de la regla de A1: la version archivada y OBSOLETA ganaba a
    la viva.

    Mutation: calcular `seen` desde `live` (filtrado) en vez de `live_all` ->
    este test se pone ROJO.
    """
    marker = f"PRECEDENCIA-047D-{uuid.uuid4()}"
    stale_but_live = {
        "id": marker,
        "timestamp": "2026-08-01T00:00:00+00:00",
        # Topic autogenerado: `is_lesson` lo excluye del recall...
        "topic": "architecture",
        "signal": f"{marker} version VIVA reescrita",
        "source": "session-close",
        "source_ticket": "WOT-2026-047d",
    }
    archived_copy = {
        "id": marker,
        "timestamp": "2026-07-01T00:00:00+00:00",
        "topic": "lesson",
        "signal": f"{marker} version ARCHIVADA obsoleta",
        "source": "test",
        "source_ticket": "WOT-2026-047d",
    }
    _write_jsonl(memory_loader._get_observations_file(), [stale_but_live])
    _write_jsonl(_archive(wired), [archived_copy])

    hits = memory_loader.recall_observations(query=marker, limit=50)

    assert not [h for h in hits if h.get("signal") == archived_copy["signal"]], (
        "la copia ARCHIVADA y obsoleta reaparecio: `seen` se calculo sobre L1 "
        "ya filtrado, asi que la entrada viva no la tapo (precedencia de A1 rota)"
    )


def test_plain_recall_without_query_also_drops_telemetry(wired: Path):
    """El filtro cubre la rama SIN query, no solo la de `--query`.

    Hallazgo del bucle L800/BA05: el DoD dice "la telemetria NO aparece en el
    resultado del recall", sin acotar a la rama con query. Una mutacion que
    aplicara `is_lesson` SOLO dentro del `if query:` dejaba verde el test de
    telemetria y reintroducia el ruido en `memory_context.py --recall` plano,
    que es justo la ruta que un agente usa sin argumentos.
    """
    marker = f"PLANO-047D-{uuid.uuid4()}"
    telemetry = {
        "timestamp": "2026-08-03T00:00:00+00:00",
        "topic": "tool_usage",
        "signal": f"{marker} telemetria mecanica",
        "source": "post_tool_hook",
    }
    lesson = {
        "id": f"LECCION-{marker}",
        "timestamp": "2026-08-03T00:00:01+00:00",
        "topic": "lesson",
        "signal": f"{marker} leccion real",
        "source": "test",
        "source_ticket": "WOT-2026-047d",
    }
    _write_jsonl(memory_loader._get_observations_file(), [telemetry, lesson])

    hits = memory_loader.recall_observations(limit=50)

    assert not [h for h in hits if h.get("signal") == telemetry["signal"]], (
        "el recall SIN query devuelve telemetria de hook: el filtro solo cubre "
        "la rama con query"
    )
    assert [h for h in hits if h.get("id") == lesson["id"]], (
        "el recall sin query perdio la leccion legitima"
    )


def test_recall_pool_is_newest_first_across_both_sources(wired: Path):
    """El pool unido sale NEWEST-FIRST, no "L1 entero y luego el archive".

    Hallazgo del bucle L800/BA05: `_read_observations` es newest-first pero
    `read_archive_observations` va en orden de fichero y linea (mas antiguo
    primero), asi que `live + archived` NO era newest-first. Importa porque los
    consumidores truncan: `memory_context.py --recall` hace `[:limit]`, de modo
    que el orden decide QUE lecciones ve el agente -- y con la concatenacion el
    archive quedaba siempre detras, inalcanzable con un `--limit` pequeño.

    El fixture pone la entrada MAS NUEVA en el archive y la mas vieja en L1,
    que es el caso que la concatenacion ordenaba mal. Mutation: volver a
    `return live + archived` -> ROJO.
    """
    marker = f"ORDEN-047D-{uuid.uuid4()}"
    old_live = {
        "id": f"VIEJA-{marker}",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "topic": "lesson",
        "signal": f"{marker} entrada VIEJA en L1",
        "source": "test",
        "source_ticket": "WOT-2026-047d",
    }
    new_archived = {
        "id": f"NUEVA-{marker}",
        "timestamp": "2026-12-31T00:00:00+00:00",
        "topic": "lesson",
        "signal": f"{marker} entrada NUEVA en el archive",
        "source": "test",
        "source_ticket": "WOT-2026-047d",
    }
    _write_jsonl(memory_loader._get_observations_file(), [old_live])
    _write_jsonl(_archive(wired), [new_archived])

    hits = memory_loader.recall_observations(query=marker, limit=50)
    stamps = [str(h.get("timestamp") or "") for h in hits]

    assert stamps == sorted(stamps, reverse=True), (
        f"el pool no sale newest-first: {stamps}"
    )
    assert hits[0]["id"] == new_archived["id"], (
        "la entrada mas NUEVA vive en el archive y no encabeza el recall: el "
        "archive quedo detras de L1 y un --limit pequeño la haria invisible"
    )


# --- WOT-2026-024r (A2): las DOS puertas que quedaban ciegas ---------------
#
# `get_bootstrap_context` (A1) y el recall (047d) ya leian el archive. Faltaban
# `get_review_context` -- el contexto del MANAGER, el que decide si un trabajo
# se aprueba -- y `get_compact_context`, que alimenta el pre-compact hook, o
# sea el momento exacto en que una sesion esta a punto de PERDER su contexto.
# Las dos leian solo superficies gitignoradas.
#
# El filtro de `get_review_context` va por `domain` y no por `topic`: medido
# sobre el archive REAL (2026-08-03), las 175 entradas traen `domain` poblado
# (CERO nulos) en 9 valores que hablan el MISMO vocabulario que el consumidor
# (`delivery-hygiene` 55, `review-quality` 55, `testing` 15, ...), mientras que
# L2 solo declara `architecture` y `lesson`.


def _domain_observation(canary: str, domain: str) -> dict:
    obs = _observation(canary)
    obs["domain"] = domain
    return obs


def test_a2_review_context_reaches_a_lesson_only_in_the_archive(wired: Path):
    """La puerta del MANAGER ve una leccion que solo vive en el archive."""
    canary = f"CANARY-A2-REVIEW-{uuid.uuid4()}"
    _write_jsonl(_archive(wired), [_domain_observation(canary, "delivery-hygiene")])

    assert not memory_loader._get_rules_file().exists()
    assert not memory_loader._get_observations_file().exists()

    assert canary in memory_loader.get_review_context(domain="delivery-hygiene")


def test_a2_mutation_review_gate_alone_goes_red(wired: Path):
    """MUTACION INDEPENDIENTE de la puerta de review.

    Truncar el archive deja en rojo SOLO el review; compact se comprueba en su
    propio test, que es lo que exige el DoD (mutaciones independientes).
    """
    canary = f"CANARY-A2-MUT-REVIEW-{uuid.uuid4()}"
    archive = _archive(wired)
    _write_jsonl(archive, [_domain_observation(canary, "delivery-hygiene")])
    assert canary in memory_loader.get_review_context(domain="delivery-hygiene")

    archive.write_text("", encoding="utf-8")  # MUTACION
    assert canary not in memory_loader.get_review_context(domain="delivery-hygiene")

    _write_jsonl(archive, [_domain_observation(canary, "delivery-hygiene")])
    assert canary in memory_loader.get_review_context(domain="delivery-hygiene")


def test_a2_review_context_filters_by_domain_not_by_topic(wired: Path):
    """Una leccion de OTRO dominio no contamina una review especializada.

    Es el anti-ruido del filtro: sin el, una review de `delivery-hygiene`
    recibiria las 175 entradas del archive entero.
    """
    mine = f"CANARY-A2-MINE-{uuid.uuid4()}"
    other = f"CANARY-A2-OTHER-{uuid.uuid4()}"
    _write_jsonl(
        _archive(wired),
        [
            _domain_observation(mine, "delivery-hygiene"),
            _domain_observation(other, "bus-architecture"),
        ],
    )

    ctx = memory_loader.get_review_context(domain="delivery-hygiene")
    assert mine in ctx
    assert other not in ctx, (
        "una leccion de otro dominio se colo en la review: el filtro por "
        "`domain` no esta discriminando y la review recibe ruido"
    )


def test_a2_review_context_without_domain_gets_the_whole_archive(wired: Path):
    """Sin dominio no hay nada que acotar: entra el archive completo."""
    a = f"CANARY-A2-NODOM-A-{uuid.uuid4()}"
    b = f"CANARY-A2-NODOM-B-{uuid.uuid4()}"
    _write_jsonl(
        _archive(wired),
        [_domain_observation(a, "delivery-hygiene"), _domain_observation(b, "testing")],
    )

    ctx = memory_loader.get_review_context()
    assert a in ctx and b in ctx


def test_a2_compact_context_reaches_a_lesson_only_in_the_archive(wired: Path):
    """La puerta del pre-compact hook ve el archive, sin filtrar por dominio."""
    canary = f"CANARY-A2-COMPACT-{uuid.uuid4()}"
    _write_jsonl(_archive(wired), [_domain_observation(canary, "testing")])

    assert not memory_loader._get_profile_file().exists()
    assert not memory_loader._get_rules_file().exists()

    assert canary in memory_loader.get_compact_context()


def test_a2_mutation_compact_gate_alone_goes_red(wired: Path):
    """MUTACION INDEPENDIENTE de la puerta de compact (la hermana de la de review)."""
    canary = f"CANARY-A2-MUT-COMPACT-{uuid.uuid4()}"
    archive = _archive(wired)
    _write_jsonl(archive, [_domain_observation(canary, "testing")])
    assert canary in memory_loader.get_compact_context()

    archive.write_text("", encoding="utf-8")  # MUTACION
    assert canary not in memory_loader.get_compact_context()

    _write_jsonl(archive, [_domain_observation(canary, "testing")])
    assert canary in memory_loader.get_compact_context()


def test_a2_live_l1_wins_over_archived_copy_in_both_gates(wired: Path):
    """Precedencia POR ENTRADA, igual que A1: la copia VIVA de L1 gana.

    L1 pudo editarse DESPUES de archivarse, asi que ante colision de `id`
    estable manda la viva. Se ejerce en las dos puertas con el mismo dato.
    """
    stable_id = f"A2-DEDUP-{uuid.uuid4()}"
    live_marker = "VERSION-VIVA"
    archived_marker = "VERSION-ARCHIVADA"

    live = {
        "id": stable_id,
        "timestamp": "2026-08-01T00:00:00+00:00",
        "topic": "lesson",
        "domain": "delivery-hygiene",
        "signal": live_marker,
        "source": "test",
        "source_ticket": "WOT-2026-024r",
    }
    archived = dict(live)
    archived["signal"] = archived_marker

    _write_jsonl(memory_loader._get_observations_file(), [live])
    _write_jsonl(_archive(wired), [archived])
    assert not memory_loader._get_rules_file().exists()
    assert not memory_loader._get_profile_file().exists()

    for ctx in (
        memory_loader.get_review_context(domain="delivery-hygiene"),
        memory_loader.get_compact_context(),
    ):
        assert live_marker in ctx
        assert archived_marker not in ctx, (
            "la copia ARCHIVADA piso a la VIVA: la precedencia por-entrada de "
            "A1 no se esta aplicando en esta puerta"
        )


def test_a2_gates_still_work_with_no_archive_at_all(tmp_path: Path, monkeypatch):
    """CONTROL POSITIVO: sin archive, las puertas siguen sirviendo lo local.

    Sin este control, un fallo que vaciara SIEMPRE la salida pasaria los tests
    de mutacion de arriba (que solo comprueban que el canario desaparece).
    """
    root = tmp_path / "sin_archive"
    (root / ".agent" / "runtime" / "memory").mkdir(parents=True)
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: root / ".agent")

    rules = "## Domain: delivery-hygiene\n\nREGLA-LOCAL-VIVA\n"
    memory_loader._get_rules_file().write_text(rules, encoding="utf-8")

    assert "REGLA-LOCAL-VIVA" in memory_loader.get_review_context(
        domain="delivery-hygiene"
    )
    assert "REGLA-LOCAL-VIVA" in memory_loader.get_compact_context()


# --- A2, correccion del MANAGER_REVIEW: el cap por recencia ----------------
#
# Dos lentes independientes devolvieron CAMBIOS por el mismo motivo: el archive
# entero (~12400 tokens) llegaba SIN TRUNCAR al pre_compact_hook, justo cuando
# la sesion compacta por falta de contexto. El cap es la mitigacion.


def test_a2_compact_context_caps_the_archive_by_recency(wired: Path):
    """Por encima del cap se conservan las entradas MAS NUEVAS, no las primeras.

    Mutation: `[:cap]` sin ordenar -> el archive llega en orden de fichero
    (oldest first) y este test cae, porque se quedarian las VIEJAS.
    """
    cap = memory_loader._COMPACT_ARCHIVE_CAP
    entries = []
    for i in range(cap + 10):
        obs = _observation(f"CANARY-A2-CAP-{i:03d}")
        # Orden de FICHERO ascendente por fecha: las primeras son las VIEJAS.
        obs["timestamp"] = f"2026-01-01T00:{i:02d}:00+00:00"
        entries.append(obs)
    _write_jsonl(_archive(wired), entries)

    ctx = memory_loader.get_compact_context()

    newest = entries[-1]["id"]
    oldest = entries[0]["id"]
    assert newest in ctx, "la entrada MAS NUEVA debe sobrevivir al cap"
    assert oldest not in ctx, (
        "la entrada MAS VIEJA sobrevivio al cap: se esta truncando sin ordenar "
        "por recencia, que es justo lo contrario de lo que una compactacion "
        "necesita"
    )


def test_a2_compact_cap_does_not_drop_anything_below_the_limit(wired: Path):
    """CONTROL POSITIVO: por debajo del cap no se pierde NADA.

    Sin este control, un cap roto que devolviera siempre pocas entradas pasaria
    el test de arriba igualmente.
    """
    cap = memory_loader._COMPACT_ARCHIVE_CAP
    entries = [_observation(f"CANARY-A2-UNDER-{i:03d}") for i in range(cap - 5)]
    _write_jsonl(_archive(wired), entries)

    ctx = memory_loader.get_compact_context()
    missing = [e["id"] for e in entries if e["id"] not in ctx]
    assert not missing, f"el cap descarto entradas estando por debajo: {missing}"


def test_a2_review_context_is_not_capped(wired: Path):
    """El cap es SOLO de compact: la review ya acota por dominio.

    Mutation: aplicar el cap tambien en `get_review_context` -> este test cae.
    """
    cap = memory_loader._COMPACT_ARCHIVE_CAP
    entries = []
    for i in range(cap + 10):
        obs = _domain_observation(f"CANARY-A2-NOCAP-{i:03d}", "delivery-hygiene")
        obs["timestamp"] = f"2026-01-01T00:{i:02d}:00+00:00"
        entries.append(obs)
    _write_jsonl(_archive(wired), entries)

    ctx = memory_loader.get_review_context(domain="delivery-hygiene")
    assert entries[0]["id"] in ctx, (
        "la review perdio la entrada mas vieja de su dominio: el cap de compact "
        "se ha filtrado a una puerta que acota por dominio, no por volumen"
    )


# --- WOT-2026-048g: el filtro por `domain` necesita que `domain` exista ------
#
# Hallazgo de DOS lentes del MANAGER_REVIEW de A2: filtrar por `domain` se
# sostiene en la medicion (175/175 poblado) pero asume no-nulidad FUTURA.
#
# Medido al verificarlo: el riesgo es REAL y alcanzable, no hipotetico.
# `validate_observations --strict` exige `domain` en su rama por defecto, PERO
# tiene una rama `has_category` que lo permite AUSENTE, y 34 de las 175 entradas
# del archive real llevan `category`. Una entrada sin `domain` no casaria NUNCA
# con ningun dominio y desapareceria del contexto de review en SILENCIO.


def test_048g_every_archive_entry_carries_a_domain(wired: Path):
    """Una entrada sin `domain` es INVISIBLE para la puerta de review.

    No casa con ningun dominio, asi que se pierde sin ruido -- justo el modo de
    fallo silencioso que WOT-2026-024r existe para cerrar. Este test lo
    convierte en un rojo explicito.

    Mutation: quitar `domain` de la entrada -> este test cae.
    """
    sin_dominio = _observation("CANARY-048G-SIN-DOMINIO")
    sin_dominio.pop("domain", None)
    con_dominio = _domain_observation("CANARY-048G-CON-DOMINIO", "testing")
    _write_jsonl(_archive(wired), [sin_dominio, con_dominio])

    huerfanas = [
        e for e in memory_loader._read_portable_archive() if not e.get("domain")
    ]
    assert huerfanas, "fixture invalido: se esperaba al menos una entrada sin domain"

    # La entrada CON dominio llega; la que no lo tiene, no llega por NINGUN
    # dominio. Se asevera el sintoma real, no una propiedad del formateador.
    ctx = memory_loader.get_review_context(domain="testing")
    assert "CANARY-048G-CON-DOMINIO" in ctx
    assert "CANARY-048G-SIN-DOMINIO" not in ctx, (
        "una entrada sin `domain` no puede colarse en un dominio que no declara"
    )

    # Y no aparece en NINGUNO de los dominios conocidos: esta huerfana.
    for dom in ("testing", "delivery-hygiene", "review-quality"):
        assert "CANARY-048G-SIN-DOMINIO" not in memory_loader.get_review_context(
            domain=dom
        )
    # El unico sitio donde sigue siendo alcanzable es la puerta sin filtro.
    assert "CANARY-048G-SIN-DOMINIO" in memory_loader.get_compact_context(), (
        "compact no filtra por dominio: es la unica red que recoge una entrada "
        "huerfana. Si esto cae, una entrada sin `domain` seria INALCANZABLE por "
        "todas las puertas"
    )


def test_048g_real_archive_has_no_orphan_entries():
    """CONTRATO sobre el archive REAL: cero entradas sin `domain`.

    Es el invariante, no la medicion: no fija un numero de entradas (que caduca
    solo), fija que NINGUNA carece de dominio. Si una entrada nueva entra por la
    rama `has_category` del validador -- que permite `domain` ausente y la usan
    34 entradas hoy -- este test la caza antes de que se pierda en silencio.
    """
    archive = memory_loader._read_portable_archive()
    if not archive:
        pytest.skip("sin archive portable en este arbol")
    huerfanas = [
        (e.get("id") or e.get("source_ticket") or "?")
        for e in archive
        if not e.get("domain")
    ]
    assert not huerfanas, (
        f"{len(huerfanas)} entrada(s) del archive sin `domain`: serian invisibles "
        f"para get_review_context en TODOS los dominios -> {huerfanas[:5]}"
    )


# =========================================================== WOT-2026-057a
# Bucle L914: el arranque en frio no recibia la memoria del MOTOR, y lo que
# recibia llegaba MUTILADO SIN MARCADOR. Tres defectos medidos, tres barreras.


def test_057a_union_keeps_destination_only_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-1 (DOS patas): la union NO puede perder lo exclusivo del destino.

    Hallazgo BA12 del bucle L914: con `AGENT_PROJECT_ROOT` al destino -- la
    forma CANONICA de operar segun AGENTS.md -- el loader veia 135 entradas del
    destino y CERO de las 207 del motor (interseccion medida = 0 bajo 5 claves).

    La primera version del fix decia "leer el motor y OPCIONALMENTE unir el
    destino". Esa palabra habria borrado de la vista las 14 lecciones exclusivas
    del destino, que son justo las de TOPOLOGIA motor/destino (donde vive el
    backlog, donde vive el last-run canonico) -- las que mas necesita un agente
    frio EN el destino.

    Por que DOS patas: un DoD de una sola pata ("aparece un id solo-motor") lo
    satisface TAMBIEN la variante destructiva. No discrimina. La pata 2 es la
    que muerde.

    MUTACION ALCANZABLE: implementar "reemplazar" en vez de "unir" -> pata 2 cae.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    for root in (motor, destino):
        (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)

    _write_jsonl(
        motor / ".agent/runtime/memory/archive/observations.2026-07.jsonl",
        [_observation("CANARY-SOLO-MOTOR", topic="solo-motor")],
    )
    _write_jsonl(
        destino / ".agent/runtime/memory/archive/observations.2026-07.jsonl",
        [_observation("CANARY-SOLO-DESTINO", topic="solo-destino")],
    )

    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: destino / ".agent")
    monkeypatch.setattr(memory_loader, "_resolve_motor_root", lambda: motor)

    signals = [
        str(e.get("signal") or "") for e in memory_loader._read_portable_archive()
    ]
    joined = " ".join(signals)

    # Pata 1: lo del MOTOR llega (era invisible antes del fix).
    assert "CANARY-SOLO-MOTOR" in joined, (
        "el archive del MOTOR debe alcanzar al agente que opera en el destino"
    )
    # Pata 2: lo del DESTINO SOBREVIVE (la que mata a la variante destructiva).
    assert "CANARY-SOLO-DESTINO" in joined, (
        "la union NO puede perder las lecciones exclusivas del destino: son las "
        "de topologia motor/destino y NADIE mas las tiene"
    )


def test_057a_motor_resolution_ignores_agent_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-2: la raiz del MOTOR no se resuelve con `AGENT_PROJECT_ROOT`.

    Hallazgo del lector-FS: D1 es CONDICIONAL. Sin esa env var el loader lee
    bien las 207 del motor; el desvio aparece SOLO cuando vale el destino. Es
    una COLISION DE CONTRATOS: esa variable responde "donde vive el ESTADO
    OPERATIVO", y se estaba usando para decidir "donde vive la MEMORIA
    PORTABLE". Son dos preguntas distintas.

    La primera version del fix ponia `AGENT_PROJECT_ROOT` PRIMERA en la
    precedencia: reproducia exactamente la causa. Este test lo impide.

    MUTACION ALCANZABLE: hacer que `_resolve_motor_root` mire esa env var ->
    devuelve el destino y el test cae.
    """
    falso_destino = tmp_path / "no-soy-el-motor"
    (falso_destino / ".agent").mkdir(parents=True)
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(falso_destino))

    resolved = memory_loader._resolve_motor_root()

    assert resolved != falso_destino, (
        "AGENT_PROJECT_ROOT apunta al ESTADO OPERATIVO, no a la memoria "
        "portable: usarla para resolver el motor reintroduce el defecto D1"
    )


def test_057a_resolution_stays_hermetic_when_only_memory_dir_is_patched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-4: redirigir la raiz DEBE redirigir tambien la busqueda del motor.

    Esta es la objecion BA12-H2 del bucle, y la primera version del fix la
    incumplia: `_resolve_motor_root` caia a `Path(__file__)`, que apunta SIEMPRE
    al motor de ESTA maquina. Medido: 11 tests hermeticos se pusieron ROJOS
    porque empezaron a leer el archive real de 207 entradas.

    Es exactamente la fuga que el docstring de `_get_repo_root` advierte y que
    el fixture `wired` documenta al NO parchear esa funcion a proposito.

    MUTACION ALCANZABLE: reintroducir el fallback `__file__` en
    `_resolve_motor_root` -> este test cae (ve el archive real del motor).
    """
    vacio = tmp_path / "repo_sin_memoria"
    (vacio / ".agent" / "runtime" / "memory").mkdir(parents=True)
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: vacio / ".agent")

    assert memory_loader._read_portable_archive() == [], (
        "con la raiz redirigida a un repo SIN archive, el loader debe devolver "
        "vacio; si devuelve entradas esta leyendo la memoria de esta maquina"
    )


def test_057a_truncation_is_marked_and_id_is_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-3: si se trunca, se MARCA; y el `id` debe poder alcanzarse.

    Dos defectos medidos en L914 sobre `_format_archive_as_text`:

    (a) truncaba a 200 chars SIN marcador -- 118 de 197 señales quedaban
        cortadas A MEDIA PALABRA y 82 tenian su regla operativa DESPUES del
        corte. `memory_consolidate` marca sus cortes con `...[truncated]`; el
        loader no, asi que el agente no podia saber que faltaba nada.
    (b) imprimia `source_ticket or id`, y con `source_ticket` poblado al 100%
        (207/207 medido) el `id` NO se imprimia NUNCA -> la expansion por `id`
        era imposible.

    MUTACION ALCANZABLE: quitar el marcador -> primer assert cae; volver a
    `source_ticket or id` -> segundo assert cae.
    """
    root = tmp_path / "repo"
    (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    larga = "A" * 400 + "REGLA-ENTERRADA-TRAS-EL-CORTE"
    entry = _observation(larga, topic="entrada-larga")
    entry["id"] = "obs-canary-expandible"
    entry["source_ticket"] = "WOT-2026-999z"
    _write_jsonl(
        root / ".agent/runtime/memory/archive/observations.2026-07.jsonl", [entry]
    )
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: root / ".agent")
    monkeypatch.setattr(memory_loader, "_resolve_motor_root", lambda: root)

    text = memory_loader._format_archive_as_text(memory_loader._read_portable_archive())

    # El marcador se busca EN LA LINEA DE LA ENTRADA, no en el texto entero:
    # la cabecera fija contiene el literal "[truncated]" para explicarlo, asi
    # que un `in text` lo satisface SIEMPRE. Medido por el lector-FS en el
    # bucle L915: con `_TRUNCATION_MARKER = ""` el test seguia VERDE -- barrera
    # muerta por spurious hit contra su propia documentacion.
    fila = next(ln for ln in text.splitlines() if ln.startswith("- [") and "AAAA" in ln)
    assert memory_loader._TRUNCATION_MARKER, "el marcador no puede ser vacio"
    assert (
        fila.rstrip().endswith(
            memory_loader._TRUNCATION_MARKER
            + f" ({entry['source_ticket']} | id: {entry['id']})"
        )
        or memory_loader._TRUNCATION_MARKER in fila
    ), (
        "un corte SIN marcador miente: el agente recibe una frase cortada a "
        f"media palabra y no puede saber que falta contenido. Fila: {fila[:120]}"
    )
    assert "REGLA-ENTERRADA-TRAS-EL-CORTE" not in fila, (
        "la fila no esta truncada: el fixture no ejercita el corte"
    )
    assert "obs-canary-expandible" in text, (
        "sin el `id` en la proyeccion, la expansion por --recall es imposible; "
        "`source_ticket or id` lo ocultaba en 207/207 entradas"
    )


def test_057a_bootstrap_index_is_bounded_and_declares_what_it_omits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-5: el INDICE de bootstrap esta acotado y dice cuanto no muestra.

    Defecto que el propio fix introdujo y que la vara de escalabilidad de BA13
    caza: unir motor+destino llevo el corpus de 135 a 342 entradas y el
    bootstrap de ~5.2k a ~28.7k tokens. Arreglar la ceguera creando un
    desbordamiento no es arreglar: es mover el problema.

    Y el crecimiento es el argumento, no el numero: ~52 entradas/mes medidas.
    Cualquier cap fijo caduca, por eso lo que se pinea es el INVARIANTE
    ("acotado Y declarado"), nunca una cifra.

    MUTACION ALCANZABLE: quitar el cap -> el indice crece con el corpus y el
    primer assert cae. Quitar el aviso -> cae el segundo.
    """
    root = tmp_path / "repo"
    (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    entradas = []
    for i in range(memory_loader._BOOTSTRAP_INDEX_CAP + 25):
        e = _observation(f"CANARY-{i}", topic=f"tema{i}")
        e["timestamp"] = f"2026-07-{(i % 28) + 1:02d}T00:00:00+00:00"
        entradas.append(e)
    _write_jsonl(
        root / ".agent/runtime/memory/archive/observations.2026-07.jsonl", entradas
    )
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: root / ".agent")

    # Se mide la puerta REAL de arranque, no el formateador suelto: el cap es
    # del bootstrap y solo se aplica ahi (ver DoD-7).
    text = memory_loader.get_bootstrap_context()

    emitidas = len(re.findall(r"^- \[", text, re.M))
    # COTA ABSOLUTA, no `<= _BOOTSTRAP_INDEX_CAP`: comparar contra la propia
    # constante es una TAUTOLOGIA -- ambos lados se mueven juntos, y BA22 midio
    # en el bucle L915 que subir el cap a 10000 dejaba este test VERDE. El
    # invariante es "el arranque cabe en un presupuesto", no "el codigo respeta
    # su propia constante", asi que el techo se fija de forma independiente.
    assert emitidas <= 150, (
        f"el indice emitio {emitidas} lineas: por encima de ~150 el arranque "
        "deja de caber en su presupuesto, valga lo que valga la constante"
    )
    assert emitidas <= memory_loader._BOOTSTRAP_INDEX_CAP
    assert "mas no mostrada" in text or "omitida" in text, (
        "un indice que recorta en SILENCIO repite el defecto que este ticket "
        "corrige: el agente debe saber que hay mas y como alcanzarlo"
    )


def test_057a_index_reserves_room_for_both_origins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-6: el cap por RECENCIA no puede expulsar a un origen entero.

    Defecto que el propio cap introdujo, medido en el bucle L915. Unir dos
    corpus y despues recortar por recencia GLOBAL trata la union como si fuera
    homogenea, y no lo es: el archive del destino termina en 2026-07-31 y el del
    motor llega a 2026-08-16, asi que el motor copa el top-60 y las 14 lecciones
    EXCLUSIVAS del destino -- las de topologia motor/destino, las que mas
    necesita un agente que opera ALLI -- caen fuera del indice.

    Es el mismo defecto que D1, con el signo invertido: antes se perdia el motor
    por resolucion de ruta; ahora se perderia el destino por recencia. Arreglar
    una ceguera creando la contraria no es arreglar.

    La recencia NO es relevancia: por eso cada origen tiene cuota reservada y el
    reparto se declara en la cabecera del indice.

    MUTACION ALCANZABLE: volver a `_cap_by_recency` global sobre la union -> el
    origen con timestamps mas antiguos desaparece y el assert cae.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    for root in (motor, destino):
        (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)

    # El MOTOR domina en recencia: todas sus entradas son mas nuevas.
    nuevas = []
    for i in range(memory_loader._BOOTSTRAP_INDEX_CAP + 20):
        e = _observation(f"MOTOR-{i}", topic=f"motor{i}")
        e["timestamp"] = f"2026-08-{(i % 28) + 1:02d}T00:00:00+00:00"
        nuevas.append(e)
    _write_jsonl(
        motor / ".agent/runtime/memory/archive/observations.2026-08.jsonl", nuevas
    )
    # El DESTINO es entero MAS ANTIGUO: por recencia global caeria fuera.
    viejas = []
    for i in range(10):
        e = _observation(f"DESTINO-{i}", topic=f"destino{i}")
        e["timestamp"] = f"2026-06-{(i % 28) + 1:02d}T00:00:00+00:00"
        viejas.append(e)
    _write_jsonl(
        destino / ".agent/runtime/memory/archive/observations.2026-06.jsonl", viejas
    )

    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: destino / ".agent")
    monkeypatch.setattr(memory_loader, "_resolve_motor_root", lambda: motor)

    text = memory_loader._format_archive_as_text(memory_loader._read_portable_archive())

    assert "CANARY-MOTOR-" in text or "motor" in text, (
        "el origen mas reciente debe estar representado"
    )
    assert "canario DESTINO-0" in text, (
        "el origen con timestamps mas ANTIGUOS quedo expulsado del indice: un "
        "cap por recencia global sobre corpus unidos borra un origen entero"
    )


def test_057a_index_cap_does_not_leak_into_review_or_compact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-7: el cap del INDICE es del arranque; review y compact no lo heredan.

    Hallazgo BA21 del bucle L915, medido sobre el corpus real: el cap se metio
    DENTRO del formateador, asi que las tres puertas lo heredaban. Consecuencia
    material -- `get_review_context('review-quality')` tenia 74 lecciones y
    emitia 60: el Manager perdia 14 al decidir APPROVE/CHANGES, y las que se
    caian eran las MAS VIEJAS por recencia, o sea las cicatrices sedimentadas
    que existen para vetar la reincidencia.

    Un review degradado APRUEBA trabajo que debia rechazar, y eso se commitea.
    El cap del arranque protege un presupuesto de arranque; no tiene ninguna
    autoridad sobre una decision de review.

    MUTACION ALCANZABLE: volver a capar dentro de `_format_archive_as_text` sin
    parametro -> review vuelve a emitir 60 de 74 y el assert cae.
    """
    root = tmp_path / "repo"
    (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    n = memory_loader._BOOTSTRAP_INDEX_CAP + 14
    entradas = []
    for i in range(n):
        e = _observation(f"REV-{i}", topic=f"rev{i}")
        e["domain"] = "review-quality"
        e["timestamp"] = f"2026-07-{(i % 28) + 1:02d}T00:00:00+00:00"
        entradas.append(e)
    _write_jsonl(
        root / ".agent/runtime/memory/archive/observations.2026-07.jsonl", entradas
    )
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: root / ".agent")

    review = memory_loader.get_review_context("review-quality")
    emitidas = len(re.findall(r"^- \[", review, re.M))

    assert emitidas == n, (
        f"el review emitio {emitidas} de {n} lecciones del dominio: el cap del "
        "INDICE de arranque se filtro a la puerta que decide APPROVE/CHANGES"
    )


def test_057a_compact_header_states_the_real_corpus_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-8: la cabecera no puede AFIRMAR un tamaño de corpus falso.

    Hallazgo BA21: `get_compact_context` capa a 50 y el formateador recibia ya
    esas 50, asi que calculaba `total = 50` y emitia "50 lesson(s) travel with
    this repo; showing the 50 newest" sobre un corpus de 342 -- falso por un
    factor de ~7, y SIN aviso de omision porque `total == len(shown)`.

    Es peor que el silencio anterior: el agente recibe una afirmacion POSITIVA
    y falsa justo cuando esta perdiendo contexto.

    MUTACION ALCANZABLE: volver a calcular `total` sobre la lista ya capada ->
    la cabecera vuelve a mentir y el assert cae.
    """
    root = tmp_path / "repo"
    (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    n = memory_loader._COMPACT_ARCHIVE_CAP + 40
    entradas = []
    for i in range(n):
        e = _observation(f"CMP-{i}", topic=f"cmp{i}")
        e["timestamp"] = f"2026-07-{(i % 28) + 1:02d}T00:00:00+00:00"
        entradas.append(e)
    _write_jsonl(
        root / ".agent/runtime/memory/archive/observations.2026-07.jsonl", entradas
    )
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: root / ".agent")

    compact = memory_loader.get_compact_context()

    assert f"{n} lesson(s)" in compact, (
        "la cabecera declara el tamaño del subconjunto capado como si fuera el "
        f"corpus entero: debe decir {n}, no el numero de lineas que emite"
    )
    assert "no mostrada" in compact, (
        "compact recorta y no lo declara: el agente cree ver el corpus entero "
        "en el momento exacto en que esta perdiendo contexto"
    )


def test_057a_resolves_motor_from_a_real_link_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-9: la RESOLUCION real, sin mockear la funcion bajo prueba.

    Hallazgo BA22 del bucle L915, y es el hueco mas grave que encontro: los
    tests de la union mockeaban `_resolve_motor_root`, asi que probaban al
    CONSUMIDOR y dejaban la resolucion SIN COBERTURA. Medido: sustituir todo el
    cuerpo por `return None` -- que mata la union entera y reintroduce D1 --
    dejaba 4 de 5 tests VERDES.

    Ademas, `test_..._ignores_agent_project_root` era FLOOR ASSERTION: en un
    tmp_path sin link la funcion devuelve `None` siempre, y `None != falso` pasa
    sin la feature. Este test lo complementa con un assert POSITIVO: escribe un
    link REAL y exige que resuelva exactamente al motor.

    MUTACION ALCANZABLE: `return None` en `_resolve_motor_root` -> cae el primer
    assert. Leer `AGENT_PROJECT_ROOT` en vez del link -> cae el segundo.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    (motor / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    (destino / ".agent" / "config").mkdir(parents=True)
    (destino / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    (destino / ".agent" / "config" / "motor_destination_link.json").write_text(
        json.dumps(
            {
                "motor_root": str(motor),
                "destination_root": str(destino),
                "destination_id": "fixture",
                "ticket_prefix": "WOT",
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        motor / ".agent/runtime/memory/archive/observations.2026-07.jsonl",
        [_observation("CANARY-VIA-LINK", topic="via-link")],
    )
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: destino / ".agent")

    # Assert POSITIVO: resuelve al motor REAL, leyendo el link de verdad.
    assert memory_loader._resolve_motor_root() == motor, (
        "la resolucion por link no funciona: sin ella la union es codigo muerto"
    )

    # Y con AGENT_PROJECT_ROOT apuntando a otro sitio, sigue resolviendo el
    # motor por el LINK -- que es el discriminante de la colision de contratos.
    monkeypatch.setenv("AGENT_PROJECT_ROOT", str(tmp_path / "otro-sitio"))
    assert memory_loader._resolve_motor_root() == motor

    # Y el efecto extremo a extremo: la leccion del motor llega al contexto.
    assert "CANARY-VIA-LINK" in memory_loader.get_bootstrap_context()


def test_057a_quota_picks_the_newest_of_each_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-11: la cuota reparte bien Y elige lo mas RECIENTE de cada origen.

    Defecto medido en el bucle L915 sobre el corpus real: el reparto salia
    30/30 -- correcto -- y sin embargo el indice contenia las entradas MAS
    ANTIGUAS de cada archive (motor desde 2026-05-24, destino desde 2026-06-12),
    dejando fuera las lecciones recientes que son las que un agente necesita.

    Causa: `_cap_by_recency(entries, len(entries))` se estaba usando para
    ORDENAR, pero esa funcion devuelve la lista INTACTA cuando `cap >= len`.
    Un no-op silencioso: reparto correcto sobre la seleccion equivocada.

    Es la misma familia que "un conteo correcto sobre la unidad equivocada":
    la mitad visible del mecanismo funcionaba y tapaba la otra mitad.

    MUTACION ALCANZABLE: volver a `_cap_by_recency(entries, len(entries))` ->
    el indice se llena de entradas viejas y el assert cae.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    for root in (motor, destino):
        (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)

    def _lote(prefix: str, year_month: str, n: int) -> list[dict]:
        out = []
        for i in range(n):
            e = _observation(f"{prefix}-{i:03d}", topic=f"{prefix.lower()}{i}")
            e["timestamp"] = f"{year_month}-{(i % 28) + 1:02d}T00:00:00+00:00"
            out.append(e)
        return out

    _write_jsonl(
        motor / ".agent/runtime/memory/archive/observations.2026-07.jsonl",
        _lote("MOTORVIEJO", "2026-01", 40) + _lote("MOTORNUEVO", "2026-08", 40),
    )
    _write_jsonl(
        destino / ".agent/runtime/memory/archive/observations.2026-07.jsonl",
        _lote("DESTVIEJO", "2026-02", 40) + _lote("DESTNUEVO", "2026-07", 40),
    )
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: destino / ".agent")
    monkeypatch.setattr(memory_loader, "_resolve_motor_root", lambda: motor)

    text = memory_loader.get_bootstrap_context()

    assert "MOTORNUEVO" in text, "el indice no trajo lo RECIENTE del motor"
    assert "DESTNUEVO" in text, "el indice no trajo lo RECIENTE del destino"
    assert "MOTORVIEJO" not in text, (
        "el indice eligio entradas VIEJAS del motor teniendo recientes: la "
        "ordenacion por recencia dentro de cada origen es un no-op"
    )
    assert "DESTVIEJO" not in text, (
        "el indice eligio entradas VIEJAS del destino teniendo recientes"
    )


def test_057a_index_prefers_lessons_over_autogenerated_templates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD-12: las plantillas autogeneradas no pueden desplazar a las lecciones.

    Medido en el bucle L915 sobre el corpus real del destino: 135 entradas, de
    las cuales 116 son PLANTILLAS autogeneradas por el paso `observations:` del
    cierre ("Decisiones arquitectonicas documentadas en X", topic `architecture`
    o `ticket-completion`) y solo 19 son lecciones. Como las plantillas son mas
    RECIENTES, ocupaban 25 de las 30 plazas de la cuota y dejaban fuera 14 de
    las 19 lecciones reales.

    Resultado neto: el arranque gastaba su presupuesto en ruido con schema
    valido. `obs-schema-gate-certifies-empty-template-bodies` ya lo dice --
    "presencia de campo no es presencia de conocimiento" -- y `is_lesson()` ya
    existe y ya filtra en la puerta de `recall`. Aqui solo se aplica donde
    faltaba.

    NO es un borrado: las plantillas siguen en el archive y siguen siendo
    alcanzables; lo que no hacen es competir por el indice.

    MUTACION ALCANZABLE: quitar el filtro `is_lesson` del indice -> las
    plantillas vuelven a copar la cuota y el assert cae.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    for root in (motor, destino):
        (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)

    _write_jsonl(
        motor / ".agent/runtime/memory/archive/observations.2026-07.jsonl",
        [_observation(f"M-{i}", topic=f"m{i}") for i in range(5)],
    )
    # El destino: 1 leccion ANTIGUA y 50 plantillas RECIENTES que la taparian.
    leccion = _observation("LECCION-REAL-DEL-DESTINO", topic="topologia-destino")
    leccion["timestamp"] = "2026-06-01T00:00:00+00:00"
    plantillas = []
    for i in range(memory_loader._BOOTSTRAP_INDEX_CAP * 3):
        p = _observation(f"PLANTILLA-{i}", topic="architecture")
        p.pop("id", None)
        p["signal"] = f"Decisiones arquitectonicas documentadas en WOT-2026-{i:03d}"
        p["timestamp"] = f"2026-08-{(i % 28) + 1:02d}T00:00:00+00:00"
        plantillas.append(p)
    _write_jsonl(
        destino / ".agent/runtime/memory/archive/observations.2026-08.jsonl",
        [leccion, *plantillas],
    )
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: destino / ".agent")
    monkeypatch.setattr(memory_loader, "_resolve_motor_root", lambda: motor)

    text = memory_loader.get_bootstrap_context()

    assert "LECCION-REAL-DEL-DESTINO" in text, (
        "la unica leccion REAL del destino quedo fuera del indice, desplazada "
        "por plantillas autogeneradas mas recientes: el arranque gasta su "
        "presupuesto en ruido con schema valido"
    )


def test_057b_lesson_filter_never_erases_a_whole_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD: filtrar plantillas no puede borrar un ORIGEN entero del indice.

    Defecto medido en el bucle L917 (BA41/BA43, reproducido): `is_lesson` corria
    ANTES de agrupar por origen, asi que podia vaciar un origen completo antes de
    que la cuota -- el mecanismo que existe para impedir exactamente eso --
    llegase a protegerlo:

        local=80 plantillas + motor=80 lecciones, cap=60
          -> Counter({'motor': 60})    el destino DESAPARECE, sin aviso

    Es la ceguera D1 con el signo invertido, y no es hipotetica: el paso
    `observations:` del cierre genera plantillas AUTOMATICAMENTE mientras las
    lecciones se escriben a mano, asi que la ratio de un destino tiende
    monotonamente a favor de las plantillas. El dia que un destino llegue a cero
    lecciones, su archive se evapora del arranque -- justo las de topologia, las
    que mas necesita quien opera ALLI -- y el pie del indice lo contaria como
    "no mostradas por presupuesto", indistinguible de un recorte legitimo.

    MUTACION ALCANZABLE: mover el filtro `is_lesson` delante del agrupado por
    origen -> el origen de plantillas desaparece y el assert cae.
    """
    motor = tmp_path / "motor"
    destino = tmp_path / "destino"
    for root in (motor, destino):
        (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)

    lecciones = []
    for i in range(80):
        e = _observation(f"LECCION-{i}", topic=f"leccion{i}")
        e["timestamp"] = f"2026-07-{(i % 28) + 1:02d}T00:00:00+00:00"
        lecciones.append(e)
    _write_jsonl(
        motor / ".agent/runtime/memory/archive/observations.2026-07.jsonl", lecciones
    )

    # El destino: SOLO plantillas autogeneradas, el caso limite.
    plantillas = []
    for i in range(80):
        p = _observation(f"PLANTILLA-{i}", topic="architecture")
        p.pop("id", None)
        p["signal"] = f"Decisiones arquitectonicas documentadas en WOT-2026-{i:03d}"
        p["timestamp"] = f"2026-08-{(i % 28) + 1:02d}T00:00:00+00:00"
        plantillas.append(p)
    _write_jsonl(
        destino / ".agent/runtime/memory/archive/observations.2026-08.jsonl", plantillas
    )

    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: destino / ".agent")
    monkeypatch.setattr(memory_loader, "_resolve_motor_root", lambda: motor)

    shown = memory_loader._cap_preserving_origins(
        memory_loader._read_portable_archive(), memory_loader._BOOTSTRAP_INDEX_CAP
    )
    origenes = {str(e.get("_origin")) for e in shown}

    assert "local" in origenes, (
        "el origen cuyas entradas son TODAS plantillas desaparecio del indice: "
        "el filtro corre antes de la cuota y la deja sin nada que proteger"
    )
    assert "motor" in origenes, "el origen con lecciones tambien debe estar"


def test_057b_review_context_has_a_declared_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """DoD: el review tiene TECHO, y lo que omite lo DECLARA.

    Hallazgo BA43 del bucle L917, medido en la ruta productiva:

        render_loader_rules('code')  -> 126.049 chars ~31.512 tok

    La union dejo `get_review_context` SIN capar a proposito -- "un review decide
    APPROVE/CHANGES y no puede perder lecciones" -- y el invariante es correcto.
    Lo que no se midio es la consecuencia: ~31.5k tokens de memoria antes de que
    el Manager vea una sola linea de diff, creciendo ~103 entradas/mes.

    Y contradecia el argumento central de este mismo modulo, que dice literal
    que "curar la ceguera causando un desbordamiento no es una cura, es una
    reubicacion". Eso es exactamente lo que quedaba en la puerta que decide si
    el trabajo se aprueba.

    La distincion que resuelve la tension: "un review no puede PERDER lecciones"
    NO es lo mismo que "un review no puede tener PRESUPUESTO". Se aplica el
    patron que `_print_recall` ya usa -- descartar entradas ENTERAS y NOMBRARLAS
    -- en vez de un cap silencioso por cardinalidad, que es justo el defecto que
    costo 14 de 74 lecciones al Manager.

    MUTACION ALCANZABLE: quitar el presupuesto -> el output crece sin techo y el
    primer assert cae. Quitar el aviso -> cae el segundo.
    """
    root = tmp_path / "repo"
    (root / ".agent" / "runtime" / "memory" / "archive").mkdir(parents=True)
    entradas = []
    for i in range(120):
        e = _observation(f"REV-{i}", topic=f"rev{i}")
        e["domain"] = "review-quality"
        e["signal"] = "R" * 2000
        e["timestamp"] = f"2026-07-{(i % 28) + 1:02d}T00:00:00+00:00"
        entradas.append(e)
    _write_jsonl(
        root / ".agent/runtime/memory/archive/observations.2026-07.jsonl", entradas
    )
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: root / ".agent")

    review = memory_loader.get_review_context("review-quality")

    assert len(review) <= memory_loader._REVIEW_BYTE_BUDGET * 1.3, (
        f"el review emitio {len(review)} chars sin techo: ~31.5k tokens de "
        "memoria antes de ver el diff, y creciendo cada mes"
    )
    assert "no mostrada" in review, (
        "el review recorta y NO lo declara: un recorte mudo en la puerta que "
        "decide APPROVE/CHANGES es el falso verde que este ticket corrige"
    )
