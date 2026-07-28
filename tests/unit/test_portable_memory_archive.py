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
    """Apunta el loader al fixture: `.agent` y raiz de repo del fixture."""
    agent_dir = repo / ".agent"
    monkeypatch.setattr(memory_loader, "get_agent_dir", lambda: agent_dir)
    monkeypatch.setattr(memory_loader, "_get_repo_root", lambda: repo)
    return repo


def _archive(repo: Path) -> Path:
    return repo / ".agent/runtime/memory/archive/observations.2026-07.jsonl"


# --- DoD.1: comportamiento, con RECIBO de hermeticidad --------------------


def test_bootstrap_context_contains_archive_canary(wired: Path, capsys):
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


def test_dedup_key_prefers_stable_id_and_falls_back(wired: Path):
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
