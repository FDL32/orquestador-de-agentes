"""WOT-2026-027s: las 3 capas del filtro de fuga, con AISLAMIENTO POR CAPA.

DoD (e): quitar una capa hace caer SU test y SOLO el suyo. Cada bloque de este
modulo ejercita su capa por una PUERTA DISTINTA:
  - capa 1 (allowlist de LECTURA, por RUTA)   -> payload_read_allowed
  - capa 2 (credencial por NOMBRE DE CLAVE)   -> _CREDENTIAL_ASSIGNMENT
  - capa 3 (entropia de Shannon, por FORMA)   -> _entropy_leak

Las capas 2 y 3 son ortogonales A PROPOSITO: la 2 casa nombres de clave
conocidos y no mide aleatoriedad; la 3 mide aleatoriedad y no conoce nombres.
El renombrado de `_HIGH_ENTROPY_ASSIGNMENT` a `_CREDENTIAL_ASSIGNMENT` existe
justamente para que ese aislamiento sea NOMBRABLE: con el nombre viejo, "quitar
la capa de entropia" no tenia un referente unico.

Vive en un modulo PROPIO (no dentro de test_ensemble_dispatch.py) porque ese
fichero tiene un guard de hermeticidad por seccion (WOT-2026-025z) que audita su
texto crudo; anadir aqui evita interferir con ese contrato.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ensemble_dispatch as ed  # noqa: E402


_FIXTURE_BUNDLES = Path(__file__).resolve().parents[1] / "fixtures" / "ensemble_bundles"

# Secreto sintetico SIN nombre de clave ni prefijo reconocible: solo la capa 3
# puede verlo. Si la capa 2 lo cazase, el aislamiento del DoD (e) seria falso.
_OPACO = "kJ8vQz3XpR7mNw2LtY6bHc4FdA9sG1eU5iO0"
# Valor con nombre de clave conocido y valor DELIBERADAMENTE repetitivo (baja
# entropia): solo la capa 2 puede verlo.
_CON_NOMBRE = 'password = "aaaaaaaa"'
# Falsos positivos obvios de un gate de entropia mal acotado.
_CADENA_REPETIDA = "a" * 64
_SHA_HEX = "0123456789abcdef0123456789abcdef01234567"


# ---------------------------------------------------------------------------
# CAPA 1 -- allowlist de LECTURA (por RUTA, ANTES de leer)
# ---------------------------------------------------------------------------


def test_027s_capa1_payload_fuera_de_allowlist_es_rechazado(tmp_path):
    """CAPA 1, el ROJO del ticket: hoy el CLI lee CUALQUIER ruta sin filtro."""
    intruso = tmp_path / "privada" / "secretos.md"
    intruso.parent.mkdir(parents=True)
    intruso.write_text("contenido", encoding="utf-8")

    allowed, reason = ed.payload_read_allowed(
        intruso, ["orchestrator_pipeline/"], motor_root=tmp_path
    )
    assert allowed is False, "un payload fuera de la allowlist debe rechazarse"
    assert "fuera de ensemble_payload_allowlist" in reason


def test_027s_capa1_payload_dentro_de_allowlist_pasa(tmp_path):
    """CAPA 1, cara positiva: DENTRO de la allowlist pasa (no es un no-op)."""
    permitido = tmp_path / "orchestrator_pipeline" / "bundle.md"
    permitido.parent.mkdir(parents=True)
    permitido.write_text("contenido", encoding="utf-8")

    allowed, reason = ed.payload_read_allowed(
        permitido, ["orchestrator_pipeline/"], motor_root=tmp_path
    )
    assert allowed is True, f"payload legitimo bloqueado: {reason}"


def test_027s_capa1_allowlist_vacia_es_retrocompatible(tmp_path):
    """CAPA 1, ANTI-FALSO-POSITIVO: sin configurar, el pipeline de hoy sigue.

    ensemble_payload_allowlist nace VACIA en el motor (medido 2026-07-27). Si
    esta capa fuese fail-closed con lista vacia, romperia todo envio actual.
    """
    cualquiera = tmp_path / "cualquier_sitio.md"
    cualquiera.write_text("contenido", encoding="utf-8")

    allowed, reason = ed.payload_read_allowed(cualquiera, [], motor_root=tmp_path)
    assert allowed is True
    assert "no configurada" in reason


def test_027s_capa1_symlink_no_sortea_la_allowlist(tmp_path):
    """CAPA 1: la decision es sobre la ruta RESUELTA, no la nominal."""
    secreto = tmp_path / "privada" / "secretos.md"
    secreto.parent.mkdir(parents=True)
    secreto.write_text("contenido", encoding="utf-8")
    permitido_dir = tmp_path / "orchestrator_pipeline"
    permitido_dir.mkdir()
    enlace = permitido_dir / "parece_legitimo.md"
    try:
        enlace.symlink_to(secreto)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks no disponibles en este entorno")

    allowed, _ = ed.payload_read_allowed(
        enlace, ["orchestrator_pipeline/"], motor_root=tmp_path
    )
    assert allowed is False, "un symlink no debe sortear la allowlist"


def test_027s_capa1_bloquea_en_el_cli_antes_de_leer(tmp_path, monkeypatch):
    """CAPA 1 CABLEADA: el CLI lanza DispatchBlockedError ANTES de leer.

    No basta con que la funcion decida bien: si el CLI no la invoca, la barrera
    no existe. Mutation: quitar el bloque de _cmd_run -> este test cae.
    Se prueba que NO SE LEE, no solo que aborta: read_text queda envenenado, de
    modo que una lectura previa al veredicto falla de forma ruidosa.
    """
    intruso = tmp_path / "privada" / "secretos.md"
    intruso.parent.mkdir(parents=True)
    intruso.write_text("no debe leerse", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise AssertionError("el CLI LEYO el payload antes de aplicar la capa 1")

    monkeypatch.setattr(Path, "read_text", _boom)

    args = types.SimpleNamespace(
        project_root=str(tmp_path / "destino"),
        payload_file=str(intruso),
        pipeline="p",
        ticket="T",
        task_type="review",
        data_sensitivity="public",
        context_kind="none",
        max_rounds=1,
        session_id=None,
    )
    config = {"ensemble_payload_allowlist": ["orchestrator_pipeline/"]}

    with pytest.raises(ed.DispatchBlockedError) as exc:
        ed._cmd_run(args, config)
    assert "lectura de payload BLOQUEADA" in str(exc.value)


# ---------------------------------------------------------------------------
# CAPA 2 -- credencial por NOMBRE DE CLAVE (no mide entropia)
# ---------------------------------------------------------------------------


def test_027s_capa2_sigue_mordiendo_tras_el_renombrado():
    """CAPA 2 AISLADA: nombre de clave conocido + valor de BAJA entropia."""
    allowed, reason = ed.privacy_preflight(_CON_NOMBRE, "public", {}, [])
    assert allowed is False
    assert "nombre de clave" in reason


def test_027s_capa2_no_es_alcanzable_por_la_capa3():
    """AISLAMIENTO (e): el payload de la capa 2 NO dispara la capa 3."""
    assert ed._entropy_leak(_CON_NOMBRE) is None


# ---------------------------------------------------------------------------
# CAPA 3 -- entropia de Shannon (por FORMA del valor, sin conocer nombres)
# ---------------------------------------------------------------------------


def test_027s_capa3_caza_secreto_opaco_sin_patron():
    """CAPA 3 AISLADA: el vector que 027n declaro RESIDUAL y no cerraba.

    Sin nombre de clave reconocible y sin prefijo conocido: solo la entropia lo
    ve. Es el hueco "valor sin patron / base64 opaco" de la ficha.
    """
    assert ed._entropy_leak(_OPACO) is not None

    allowed, reason = ed.privacy_preflight(_OPACO, "public", {}, [])
    assert allowed is False
    assert "entropia" in reason


def test_027s_capa3_no_es_alcanzable_por_la_capa2():
    """AISLAMIENTO (e): el payload de la capa 3 NO dispara la capa 2."""
    assert ed._CREDENTIAL_ASSIGNMENT.search(_OPACO) is None


def test_027s_capa3_no_filtra_el_secreto_en_el_reason():
    """CAPA 3: el reason viaja a logs; NO debe filtrar el valor detectado."""
    reason = ed._entropy_leak(_OPACO)
    assert reason is not None
    assert _OPACO not in reason, "el reason FUGA el secreto que intenta proteger"


@pytest.mark.parametrize(
    "benigno",
    [
        _CADENA_REPETIDA,
        _SHA_HEX,
        "esta es prosa tecnica normal sobre api_key y tokens de acceso",
        "https://github.com/usuario/repositorio/blob/main/scripts/fichero.py",
    ],
)
def test_027s_capa3_anti_falso_positivo(benigno):
    """CAPA 3 ANTI-FALSO-POSITIVO: hash de commit, prosa y URLs NO muerden.

    Un gate que bloquea trabajo legitimo ensena al operador a saltarselo
    (AGENTS.md). El SHA hex y la cadena repetida son los dos falsos positivos
    obvios de un gate de entropia mal acotado.
    """
    assert ed._entropy_leak(benigno) is None, f"falso positivo: {benigno!r}"


# ---------------------------------------------------------------------------
# Las 3 capas JUNTAS -- anti-falso-positivo global y deuda declarada
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name",
    [
        "bundle_prose_technical_terms.md",
        "bundle_prose_governance.md",
        "bundle_prose_env_example.md",
    ],
)
def test_027s_bundles_reales_siguen_pasando_con_las_3_capas(fixture_name):
    """ANTI-FALSO-POSITIVO GLOBAL: las 3 capas juntas no rompen el pipeline.

    Los mismos 3 bundles que fija 027n deben seguir pasando DESPUES de anadir la
    capa 3. Si la entropia los mordiese, el vuelo se auto-bloquearia en su
    propio MANAGER_REVIEW.
    """
    payload = (_FIXTURE_BUNDLES / fixture_name).read_text(encoding="utf-8")
    allowed, reason = ed.privacy_preflight(payload, "public", {}, [])
    assert allowed is True, f"FALSO POSITIVO en {fixture_name}: {reason}"


def test_027s_umbral_de_entropia_declara_su_deuda():
    """La deuda del umbral esta DECLARADA con dueno, no escondida.

    AGENTS.md: un umbral no calibrado es una "meseta sin medir". El corpus para
    calibrarlo no existe (los bundles vivian en tmp/ gitignored y se purgaron),
    asi que la capa nace en deteccion basica con deuda de dueno explicito. Si
    alguien cambia el numero sin calibrar, debe tropezar con este contrato.
    """
    src = Path(ed.__file__).read_text(encoding="utf-8")
    assert "WOT-2026-041n" in src, "la deuda del umbral perdio su ticket dueno"
    assert ed._ENTROPY_BITS_THRESHOLD == 4.0


def test_027s_capa3_no_muerde_prosa_del_repo_real():
    """CAPA 3 ANTI-FALSO-POSITIVO contra el REPO REAL, no contra mis fixtures.

    AGENTS.md: "un barrido contra tus propios fixtures mide tus fixtures, no el
    sistema". Los 4 casos parametrizados de arriba los escribi yo y por eso
    daban verde; este test barre la PROSA REAL del motor (.md de raiz y
    prompts/), que es la forma que tiene un payload de ensemble de verdad.

    MEDIDO 2026-07-27: 0 mordidos sobre prosa. La primera version del alfabeto
    (que incluia `/ _ -`) mordia 6, todos rutas y URLs -- ese fue el ROJO que
    obligo a acotar `_OPAQUE_TOKEN`. Este test es la barrera que impide que
    vuelva a ampliarse sin medir.
    """
    root = Path(ed.__file__).resolve().parents[1]
    prosa = list(root.glob("*.md")) + list((root / "prompts").glob("*.md"))
    assert len(prosa) >= 10, "el corpus de prosa real no se resolvio"

    mordidos = []
    for path in prosa:
        try:
            texto = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if ed._entropy_leak(texto) is not None:
            mordidos.append(path.name)

    assert not mordidos, (
        f"la capa 3 muerde PROSA legitima del repo: {mordidos}. Un gate que "
        f"bloquea el trabajo real ensena al operador a saltarselo (AGENTS.md)."
    )
