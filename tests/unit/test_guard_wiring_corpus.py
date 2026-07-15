"""The wiring CORPUS, executed (WOT-2026-024u).

`tests/fixtures/guard_wiring_corpus.yaml` is the executable specification of
check_guard_wiring: every case plants a synthetic motor and asserts the verdict.

Why the corpus is a FILE and not a pile of hand-written tests: this module has failed
three times with the same shape -- the author enumerates the invocation positions he can
imagine, writes tests for exactly those, and the mutation-verify comes back green because
it only proves the tests cover the branches the author thought of. Enumeration is not
completeness. Moving the enumeration into versioned data makes it reviewable, diffable,
and appendable: every case an adversarial audit finds gets added here, with its origin.

A negative case that comes out WIRED is the CRITICAL defect: it silently disables the one
asymmetric rule that stops the debt growing ("a NEW guard, wired nowhere, FAILS").
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "check_guard_wiring", _ROOT / "scripts" / "check_guard_wiring.py"
)
cgw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cgw)

CORPUS = yaml.safe_load(
    (_ROOT / "tests" / "fixtures" / "guard_wiring_corpus.yaml").read_text(
        encoding="utf-8"
    )
)
GUARD = CORPUS["guard_name"]
CASES = CORPUS["cases"]


def _plant(tmp_path: Path, case: dict) -> Path:
    """Build the synthetic motor described by one corpus case."""
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / f"{GUARD}.py").write_text("# guard\n", encoding="utf-8")

    for rel, body in (case.get("files") or {}).items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.replace("{GUARD}", GUARD), encoding="utf-8")

    # A case that plants no pre-commit config gets an EMPTY one: nothing is wired through
    # it. Without this, a missing file could be mistaken for "no hooks" by accident.
    cfg = tmp_path / ".pre-commit-config.yaml"
    if not cfg.exists():
        cfg.write_text(
            "repos:\n  - repo: local\n    hooks:\n      []\n", encoding="utf-8"
        )
    return tmp_path


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_corpus_case(tmp_path, case):
    root = _plant(tmp_path, case)
    wired, unwired = cgw.audit(root)

    got = GUARD in wired
    # should_wire_override: un negativo que v4 clasifica WIRED por un residual DECLARADO
    # (p.ej. un wrapper-local con sink que nadie llama -- codigo muerto CON un sink real,
    # no prosa). El caso conserva negative_reason para documentar la familia, pero el
    # veredicto esperado es el residual.
    want = case.get("should_wire_override", case["should_wire"])

    if want:
        assert got, (
            f"FALSO-UNWIRED en '{case['case_id']}': una invocacion REAL dejo de verse.\n"
            f"  por que deberia estar cableado: {case['why'].strip()}\n"
            f"  origen: {case['regression_origin'].strip()}\n"
            f"  unwired={unwired}"
        )
    else:
        assert not got, (
            f"FALSO-WIRED en '{case['case_id']}': el guard sale CABLEADO y NADIE lo ejecuta.\n"
            f"  Este es el defecto CRITICO: desactiva en silencio la regla asimetrica.\n"
            f"  por que NO ejecuta nada: {case['why'].strip()}\n"
            f"  origen: {case['regression_origin'].strip()}"
        )


def test_the_corpus_covers_both_verdicts():
    """A corpus with no negatives (or no positives) would pass against a classifier that
    always answers the same thing. Guards the corpus itself."""
    assert any(c["should_wire"] for c in CASES), (
        "sin positivos: 'nunca WIRED' aprobaria"
    )
    assert any(not c["should_wire"] for c in CASES), (
        "sin negativos: 'siempre WIRED' aprobaria"
    )


def test_every_case_declares_its_origin():
    """A case without a `regression_origin` is a case someone invented. Every entry must
    trace to a version that got it wrong, or to a REAL call-site that justifies it."""
    for c in CASES:
        assert c.get("regression_origin", "").strip(), f"{c['case_id']} sin origen"
        assert c.get("why", "").strip(), f"{c['case_id']} sin justificacion"
        assert c.get("surface", "").strip(), f"{c['case_id']} sin superficie"


# A CLOSED taxonomy of how a mention can fail to be an invocation. Free text rots; an enum
# forces every new case to say WHICH KIND of non-execution it is -- which is how you
# notice that a whole class has no coverage at all.
NEGATIVE_REASONS = {
    "prose",  # el guard aparece dentro de una FRASE, no como token ejecutable
    "manual_only",  # existe el comando, pero un humano tiene que acordarse (stages/dispatch)
    "disabled_ci",  # el step existe pero esta apagado (if: false)
    "disabled_code",  # codigo Python muerto/deshabilitado (if False:, funcion no llamada)
    "inversion",  # declarar que un guard esta DESACTIVADO (SKIP_GUARDS, deny) lo marcaba
    "label_only",  # aparece en una etiqueta humana (name:), no en el comando (entry:)
    "path_nonexecuted",  # se construye el path... y no se ejecuta
    "config_nonexec",  # vive en un config, en una clave que no ejecuta nada
}


def test_every_negative_declares_a_reason_from_the_closed_taxonomy():
    """Y ningun positivo lleva `negative_reason`: no puede haber un caso ambiguo."""
    for c in CASES:
        if c["should_wire"]:
            assert "negative_reason" not in c, (
                f"{c['case_id']} es POSITIVO y declara negative_reason"
            )
        else:
            reason = c.get("negative_reason")
            assert reason in NEGATIVE_REASONS, (
                f"{c['case_id']}: negative_reason={reason!r} fuera de la taxonomia cerrada "
                f"{sorted(NEGATIVE_REASONS)}"
            )


def test_the_taxonomy_has_no_dead_classes():
    """Cada clase de la taxonomia debe tener al menos un caso. Una clase declarada y sin
    caso es una clase que nadie comprueba -- exactamente el agujero que dejo v3 al
    arreglar `stages: [manual]` en pre-commit y olvidar su gemelo en CI."""
    covered = {c["negative_reason"] for c in CASES if not c["should_wire"]}
    missing = NEGATIVE_REASONS - covered
    assert not missing, f"clases de la taxonomia SIN NINGUN CASO: {sorted(missing)}"


def test_case_ids_are_unique_and_stable():
    """El corpus se revisa por DIFF. Un id duplicado hace que un caso pise a otro en el
    report; el harness debe leer los casos en el orden del fichero (determinista)."""
    ids = [c["case_id"] for c in CASES]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"case_id duplicados: {sorted(dupes)}"
    # El orden lo fija el fichero YAML (no un set): mismo fichero -> misma secuencia.
    assert ids == [c["case_id"] for c in CORPUS["cases"]]


def corpus_report() -> int:
    """Reporte POR CASO, no un conteo. Un '10 failed' no dice QUE clase de prosa se cuela.

    Ejecutar:  python tests/unit/test_guard_wiring_corpus.py
    """
    import tempfile

    rows, bad = [], 0
    for case in CASES:
        with tempfile.TemporaryDirectory() as td:
            root = _plant(Path(td), case)
            wired, _ = cgw.audit(root)
            got = GUARD in wired
            want = case.get("should_wire_override", case["should_wire"])
            ok = got == want
            bad += not ok
            kind = "" if ok else ("FALSO-WIRED" if got else "FALSO-UNWIRED")
            rows.append(
                (case["case_id"], case.get("negative_reason", "-"), want, got, kind)
            )

    print(f"{'case_id':<38} {'reason':<18} {'want':<6} {'got':<6} defecto")
    print("-" * 92)
    for cid, reason, want, got, kind in rows:
        print(
            f"{cid:<38} {reason:<18} "
            f"{'wire' if want else 'no':<6} {'wire' if got else 'no':<6} {kind}"
        )
    print("-" * 92)
    print(f"{len(rows) - bad}/{len(rows)} correctos, {bad} defectos")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(corpus_report())
