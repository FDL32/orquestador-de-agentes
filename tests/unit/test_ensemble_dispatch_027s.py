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
# Falso positivo obvio de un gate de entropia mal acotado: entropia 0.00.
_CADENA_REPETIDA = "a" * 64
# WOT-2026-041q: _SHA_HEX ERA un caso anti-falso-positivo de 027s y DEJO DE
# SERLO a proposito. Un SHA hex de 40 chars es INDISTINGUIBLE por forma de una
# clave API hex de 40 chars, y 027s dejaba escapar el formato mas comun de clave
# API por tratarlo como benigno. Hoy la capa 3b lo caza: el falso positivo se
# acepta por asimetria de dano (bloquear un bundle que cita un SHA es
# recuperable; dejar salir una clave, no). Vive ahora en
# test_041q_las_longitudes_de_hash_nunca_se_excluyen como contrato POSITIVO.
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
    # WOT-2026-041r: la exclusion nominal de CREDITS.md (que 041q necesitaba) se
    # RETIRA. Era el SINTOMA, no la solucion: silenciaba por nombre un fichero que
    # el guardia de ETIQUETA ya no muerde. Hoy CREDITS.md entra en el barrido como
    # cualquier otra prosa.
    prosa = list(root.glob("*.md")) + list((root / "prompts").glob("*.md"))
    # Coste MEDIDO y declarado de admitir el alfabeto url-safe (`_`, `-`), que es
    # lo que cierra la salida de tokens OAuth/JWT: 2 ficheros de prosa muerden por
    # llevar NOMBRES DE FICHERO largos con guiones bajos. Se nombran aqui para que
    # el numero no crezca en silencio: si aparece un tercero, este test lo caza.
    coste_url_safe = {"CHANGELOG.md", "audit_portability_legacy_surface.md"}
    prosa = [p for p in prosa if p.name not in coste_url_safe]
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


# ---------------------------------------------------------------------------
# CAPA 3b -- hex puro (WOT-2026-041q). El hueco que 027s dejo abierto.
#
# Lo encontro un bucle adversarial EXTERNO (4 lentes convergieron), no la suite
# de 027s: el mismo sesgo que escribio la capa 3 escribio sus tests, y ninguno
# probo hex. Es la leccion de AGENTS.md "aplicate tu propia vara" pagada en el
# vuelo siguiente.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secreto_hex",
    [
        "d41d8cd98f00b204e9800998ecf8427e5f1a2b3c",
        "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ],
)
def test_041q_capa3b_caza_hex_puro(secreto_hex):
    """EL ROJO de 041q: hex -- el formato mas comun de clave API -- escapaba.

    Par medido 2026-07-27 ANTES del fix: los 3 daban None. Causa: el hex tiene
    solo DOS clases de caracter (letras + digitos), asi que el guardia
    `classes < 3` de la capa 3 lo descartaba ANTES de mirar su entropia.

    WOT-2026-041r CAMBIA EL CONTRATO a proposito: el hex ya no se caza DESNUDO,
    sino solo con ETIQUETA de credencial cerca. Motivo medido: sin etiqueta, un
    SHA citado en prosa es indistinguible de una clave, y la version desnuda
    bloqueo el bundle de gobernanza de su propio ticket. De los 15 hex del repo
    real que 041q mordia, CERO llevaban etiqueta: exigirla elimina el 100% del
    falso positivo sin perder ningun secreto realmente presente.
    """
    etiquetado = f'api_key = "{secreto_hex}"'
    assert ed._entropy_leak(etiquetado) is not None, (
        "un secreto hex ETIQUETADO escapa: es el formato mas comun de clave API"
    )
    assert ed._entropy_leak(secreto_hex) is None, (
        "un hex DESNUDO no debe morder (041r): sin etiqueta es indistinguible "
        "de un SHA citado, y morderlo entrena al operador a evadir el gate"
    )


def test_041q_capa3b_es_ortogonal_a_la_capa3_base64():
    """AISLAMIENTO: cada rama caza lo suyo y no depende de la otra."""
    solo_hex = "d41d8cd98f00b204e9800998ecf8427e5f1a2b3c"
    solo_b64 = "kJ8vQz3XpR7mNw2LtY6bHc4FdA9sG1eU5iO0"
    assert ed._HEX_SECRET.search(solo_hex) is not None
    assert ed._HEX_SECRET.search(solo_b64) is None, "la rama hex no debe ver base64"
    assert ed._entropy_leak(solo_b64) is not None, "base64 sigue cazandose (regresion)"


@pytest.mark.parametrize(
    "benigno",
    [
        "a1b2c3d4e5f6a1b2",
        "esta es prosa tecnica normal sobre api_key y tokens de acceso",
        "el commit 4cffb30 y el tag v9.17.1 no son secretos",
    ],
)
def test_041q_capa3b_no_muerde_hex_corto_ni_prosa(benigno):
    """ANTI-FALSO-POSITIVO de la rama hex: <32 chars y prosa NO muerden."""
    assert ed._entropy_leak(benigno) is None, f"falso positivo: {benigno!r}"


def test_041q_las_longitudes_de_hash_nunca_se_excluyen():
    """ITERACION MEDIDA Y DESCARTADA -- contrato para que nadie la repita.

    Excluir las longitudes canonicas de hash (32/40/64) deja el repo real en 0
    falsos positivos, y por eso resulta tentador. Pero hace ESCAPAR MD5, SHA-1 y
    SHA-256, que es justo donde caen las claves API hex reales: compra silencio a
    costa de la cobertura que esta capa viene a dar.

    Un SHA-1 de 40 chars y una clave API hex de 40 chars son INDISTINGUIBLES por
    forma. Se acepta el falso positivo A PROPOSITO, por asimetria de dano:
    bloquear un bundle que cita un SHA es recuperable; dejar salir una clave no.
    """
    for longitud_de_hash in (32, 40, 64):
        token = "a1b2c3d4" * (longitud_de_hash // 8)
        assert len(token) == longitud_de_hash
        # 041r: con ETIQUETA, porque el contrato del hex desnudo cambio.
        assert ed._entropy_leak(f"secret: {token}") is not None, (
            f"un hex de {longitud_de_hash} chars (longitud de hash) NO debe "
            "excluirse: es la longitud de las claves API hex reales"
        )


def test_041q_el_comentario_de_la_capa3_ya_no_promete_hex():
    """El comentario decia "base64/hex" y el codigo solo cubria base64.

    Familia "barrera del alcance" (AGENTS.md): un guard que anuncia mas alcance
    del que tiene se lee como cobertura. Este contrato fija la correccion.
    """
    src = Path(ed.__file__).read_text(encoding="utf-8")
    assert "WOT-2026-041q" in src, "la capa 3b perdio su ticket dueno"
    i = src.index("_ENTROPY_MIN_TOKEN_LEN = 32")
    cabecera = src[:i]
    assert "secreto opaco (base64/hex)" not in cabecera, (
        "el comentario de la capa 3 vuelve a prometer hex sin cubrirlo"
    )


# ---------------------------------------------------------------------------
# WOT-2026-041r -- contexto en la capa 3b + alfabeto url-safe.
#
# LA LECCION MAS CARA DEL VUELO, y por eso vive aqui como CONTRATO y no como
# anecdota en un commit: la capa 3b de 041q bloqueo EN PRODUCCION el bundle de
# gobernanza de su propio ticket, por citar el hash de ejemplo que documentaba
# el fix. La reaccion del operador fue OMITIR el literal para poder enviarlo, es
# decir, la barrera enseno su propia evasion al primer contacto con trabajo
# legitimo. AGENTS.md: "un gate que se saltan es peor que no tenerlo".
#
# Si un cambio futuro vuelve a bloquear un documento que MENCIONA un hash sin
# etiquetarlo como credencial, el arreglo NO esta hecho: estos tests lo cazan.
# ---------------------------------------------------------------------------


_HASH_CITADO = "d41d8cd98f00b204e9800998ecf8427e5f1a2b3c"


@pytest.mark.parametrize(
    "cita",
    [
        "Par medido: {h} ANTES escapa / DESPUES cazado.",
        "el commit {h} toca la capa 3",
        "https://github.com/langgenius/dify/tree/{h}",
        "| docs-hotfix | [dify@{h}](https://x/tree/{h}) | patron |",
    ],
)
def test_041r_un_hash_citado_no_bloquea(cita):
    """EL ROJO de 041r: documentar un hash no puede bloquear el envio.

    Los 4 casos son prosa REAL del repo (bundle de gobernanza, CHANGELOG,
    CREDITS.md). Con la capa 3b de 041q los 4 bloqueaban.
    """
    payload = cita.format(h=_HASH_CITADO)
    assert ed._entropy_leak(payload) is None, (
        f"un hash CITADO bloquea el envio: {payload[:60]!r}. Eso entrena al "
        "operador a omitir literales, que es evadir el gate (AGENTS.md)."
    )


@pytest.mark.parametrize(
    "etiquetado",
    [
        'api_key = "{h}"',
        "AWS_SECRET: {h}",
        "Authorization: Bearer {h}",
        'access_key="{h}"',
    ],
)
def test_041r_un_hash_etiquetado_si_bloquea(etiquetado):
    """La otra cara: con etiqueta de credencial, el MISMO hex debe bloquear.

    Sin este test, "no bloquear citas" se cumpliria trivialmente no bloqueando
    nada. El par cita/etiqueta es lo que hace falsable el guardia de contexto.
    """
    payload = etiquetado.format(h=_HASH_CITADO)
    assert ed._entropy_leak(payload) is not None, (
        f"un secreto hex ETIQUETADO escapa: {payload[:60]!r}"
    )


def test_041r_el_bundle_de_gobernanza_pasa_sin_omitir_literales():
    """DoD (a) literal: el caso de prueba que la realidad dio gratis.

    Reconstruye el fragmento exacto que provoco el DispatchBlockedError al
    enviar el bundle de gobernanza de este cierre a challenger_codex.
    """
    bundle = (
        "## HALLAZGO QUE ORIGINO 041q\n\n"
        "027s entrego una capa 3 de entropia que NO cazaba hex puro.\n"
        f"Par medido: {_HASH_CITADO} ANTES escapa / DESPUES cazado.\n"
        "Los 18 tests de 027s daban VERDE.\n"
    )
    allowed, reason = ed.privacy_preflight(bundle, "public", {}, [])
    assert allowed is True, (
        f"el bundle de gobernanza vuelve a bloquearse ({reason}). Es el "
        "incidente medido de 041r: la barrera bloquea su propia auditoria."
    )


@pytest.mark.parametrize(
    "token_url_safe",
    [
        "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        "ABCDabcd0123_-EFGHijkl4567_-MNOPqrst8901_-UVWXyz",
    ],
)
def test_041r_base64url_ya_no_escapa(token_url_safe):
    """Vector (B): un token OAuth/JWT salia LIMPIO desde 027s.

    `_OPAQUE_TOKEN` no admitia `_` ni `-`, asi que el alfabeto url-safe quedaba
    fuera. Hallado por dos lentes independientes del bucle L700.
    """
    assert ed._entropy_leak(token_url_safe) is not None, (
        "un token base64url escapa a las 3 capas: es el formato estandar de "
        "los tokens de sesion web"
    )


def test_041r_la_barra_sigue_fuera_del_alfabeto():
    """ITERACION MEDIDA Y DESCARTADA: incluir `/` reintroduce el FP de rutas.

    Medido 2026-07-27: con `/` dentro, una ruta entera casa como un solo token
    y el repo real pasa de 11 a 26 ficheros mordidos (prosa de 2 a 4), con
    `docs/BUS_ARCHITECTURE_WT-2026-210` y
    `repos/FDL32/orquestador-de-agentes/rules/branches/main` como falsos
    positivos. Es el mismo defecto que 027s ya habia medido y descartado.
    """
    ruta = "repos/FDL32/orquestador-de-agentes/rules/branches/main"
    assert ed._entropy_leak(ruta) is None, (
        "una RUTA muerde: `/` volvio al alfabeto de _OPAQUE_TOKEN"
    )
