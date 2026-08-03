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
    # No es solo "alguna": el archive entra COMPLETO (el shaping es A2).
    assert len(reached) >= len(archived) // 2, (
        f"solo {len(reached)} de {len(archived)} entradas del archive llegan al "
        "contexto: algo esta filtrando la memoria portable"
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
