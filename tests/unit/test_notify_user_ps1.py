"""Pruebas de scripts/flight/notify_user.ps1 (WOT-2026-153i, caja 1C, filas 75-77 del Anexo B).

Before: Windows con ``powershell.exe`` en su ruta absoluta; el ps1 vive junto a ``comms_alert.py``
    (o junto a la copia que apunta ``COMMS_ALERT_UNDER_TEST``, usada por el arnes de mutacion).
During: ejecuta el ps1 REAL sin ``-ExecutionPolicy Bypass`` y SIEMPRE con ``-NoFlash``: la prueba nunca
    parpadea ventanas ni pita. Tampoco hay prueba del toast correcto: mostraria un aviso real en la
    pantalla de quien corre la suite (limite declarado: el toast visible, el parpadeo real y el pitido
    quedan como prueba humana; aqui solo se comprueba la FORMA del codigo que los guarda).
After: asevera rc y salida del camino de fallo simulado, que ``-NoFlash`` no omite el toast y que el
    fichero no conserva ``-Banner`` ni ``NOTIFY_*``.
"""

import base64
import binascii
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="notify_user.ps1 es solo Windows (D11)"
)

REPO = Path(__file__).resolve().parents[2]
PS1 = (
    Path(
        os.environ.get("COMMS_ALERT_UNDER_TEST")
        or REPO / "scripts" / "flight" / "comms_alert.py"
    )
    .resolve()
    .with_name("notify_user.ps1")
)
POWERSHELL = (
    Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)


def _cmd(*args):
    """Orden de la prueba A: PowerShell absoluto, sin perfil, SIN ExecutionPolicy Bypass (D26)."""
    return [
        str(POWERSHELL),
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(PS1),
        *args,
    ]


def _run(*args):
    return subprocess.run(
        _cmd(*args), capture_output=True, text=True, timeout=60, check=False
    )


def _src():
    return PS1.read_text(encoding="utf-8")


def test_fila75_toast_simulado_falla_sale_con_exit_3_y_lo_dice():
    """fila 75: -SimulateToastFailure suprime el toast, lo declara FALLO y sale con exit 3."""
    r = _run(
        "-Title",
        "prueba 153i",
        "-Message",
        "no es real",
        "-SimulateToastFailure",
        "-NoFlash",
    )
    assert r.returncode == 3
    assert "toast=FALLO(" in r.stdout
    assert "toast=ok" not in r.stdout


def test_fila75b_la_prueba_a_no_copia_el_bypass_de_la_politica():
    """D26: la orden de la prueba A no lleva ExecutionPolicy ni Bypass (el ps1 local corre con RemoteSigned)."""
    cmd = " ".join(_cmd("-Title", "t", "-Message", "m"))
    assert "Bypass" not in cmd
    assert "ExecutionPolicy" not in cmd


def test_fila76_noflash_omite_parpadeo_y_pitido_pero_no_el_toast():
    """fila 76: con -NoFlash no hay flash_ventanas ni flash=FALLO y el toast SI se intenta (rc 3 con fallo simulado)."""
    r = _run(
        "-Title",
        "prueba 153i",
        "-Message",
        "no es real",
        "-SimulateToastFailure",
        "-NoFlash",
    )
    assert "flash_ventanas=" not in r.stdout
    assert "flash=FALLO" not in r.stdout
    assert r.stdout.startswith("toast="), r.stdout
    assert r.returncode == 3


def test_fila76b_el_pitido_cuelga_de_noflash():
    """fila 76b: el pitido no suena en un test (no deja rastro en la salida), asi que se asevera la FORMA del guard."""
    assert re.search(
        r"^if \(-not \$XmlOnly -and -not \$NoFlash\) \{ \[console\]::beep\(880,250\); \[console\]::beep\(660,250\) \}$",
        _src(),
        re.MULTILINE,
    )


def test_fila77_sin_banner_ni_variables_notify_y_con_los_parametros_exactos():
    """fila 77 (censo del ps1): ni -Banner, ni banner.ps1, ni NOTIFY_*, ni Bypass; param exacto (D26)."""
    src = _src()
    for prohibido in ("Banner", "banner", "NOTIFY_", "Bypass", "ExecutionPolicy"):
        assert prohibido not in src, prohibido
    cabecera = src[: src.index("$DismissExplanation")]
    assert cabecera.startswith("param(")
    nombres = re.findall(r"\]\$([A-Za-z]+)", cabecera)
    assert nombres == [
        "Title",
        "Message",
        "Tag",
        "Group",
        "OpenUri",
        "AppId",
        "Urgent",
        "XmlOnly",
        "Remove",
        "ClearGroup",
        "SimulateNotifierSetting",
        "SimulateToastFailure",
        "NoFlash",
    ]
    # sin Zone.Identifier (flujo alterno NTFS de un fichero descargado): el censo de D26
    with pytest.raises(OSError):
        open(f"{PS1}:Zone.Identifier", "rb").close()


def test_fila77b_ningun_script_prompt_o_skill_versionado_pasa_simulate_toast_failure():
    """D26: el parametro solo existe para pruebas; un llamador que lo pasara dejaria al usuario SIN aviso."""
    ofensores = []
    for carpeta in ("scripts", "prompts", "skills"):
        for p in (REPO / carpeta).rglob("*"):
            if (
                not p.is_file()
                or "__pycache__" in p.parts
                or p.name in {"notify_user.ps1", "check_latido_alert_wiring.py"}
            ):
                continue
            if p.suffix not in {
                ".py",
                ".ps1",
                ".md",
                ".xml",
                ".json",
                ".yaml",
                ".yml",
                ".toml",
                ".txt",
            }:
                continue
            if "SimulateToastFailure" in p.read_text(
                encoding="utf-8", errors="replace"
            ):
                ofensores.append(p.relative_to(REPO).as_posix())
    assert ofensores == []


def _xmlonly(*args):
    """Ejecuta el productor real en modo XML-only, nunca en modo Show."""
    return _run(*args, "-XmlOnly", "-NoFlash")


def _parse_xmlonly(result):
    """Parsea el único documento XML emitido por el productor."""
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))  # noqa: S314
    return ET.fromstring(result.stdout, parser=parser)  # noqa: S314


def _actions(root):
    return [
        (
            node.attrib.get("content"),
            node.attrib.get("activationType"),
            node.attrib.get("arguments"),
        )
        for node in root.findall(".//action")
    ]


def _comment(root, prefix):
    """Obtiene un comentario de metadata del XML-only por prefijo."""
    return next(
        (
            node.text or ""
            for node in root
            if node.tag is ET.Comment and (node.text or "").startswith(prefix)
        ),
        None,
    )


def _decode_effective_tag(comment):
    """Decodifica la metadata segura del Tag efectivo del comentario XML."""
    prefix = "effective-tag="
    assert comment.startswith(prefix)
    return base64.b64decode(comment.removeprefix(prefix), validate=True).decode("utf-8")


def test_caja_c_metadata_effective_tag_invalida_falla_cerrado():
    """La metadata corrupta no se acepta silenciosamente como un Tag vacío."""
    with pytest.raises((binascii.Error, UnicodeDecodeError)):
        _decode_effective_tag("effective-tag=!!!!")


def test_caja_c_metadata_effective_tag_valida_se_decodifica():
    """La ruta positiva confirma que la metadata base64 válida conserva el Tag."""
    encoded = base64.b64encode(b"tag-valido").decode("ascii")
    assert _decode_effective_tag("effective-tag=" + encoded) == "tag-valido"


def test_caja_c_metadata_effective_tag_utf8_invalido_falla():
    """Base64 válida pero UTF-8 inválida debe fallar por UnicodeDecodeError."""
    with pytest.raises(UnicodeDecodeError):
        _decode_effective_tag("effective-tag=/w==")


def test_caja1_xmlonly_entendido_es_la_unica_accion_sin_open_uri():
    """RED: sin URI solo existe Entendido/system/dismiss."""
    r = _xmlonly(
        "-Title",
        'CO-29 & <sesion> "doble" simple',
        "-Message",
        "FRASE LITERAL primero < > & \" '",
    )
    root = _parse_xmlonly(r)
    assert root.find("visual/binding/text").text == 'CO-29 & <sesion> "doble" simple'
    assert (
        root.findall("visual/binding/text")[1].text
        == "FRASE LITERAL primero < > & \" '"
    )
    assert _actions(root) == [("Entendido", "system", "dismiss")]


def test_caja1_xmlonly_open_uri_escapa_y_anade_solo_abrir_sesion():
    """RED: URI t3code válido añade exactamente la acción protocol esperada."""
    uri = "t3code://threads/env/mcp:thread&x=1&y=2<z>\"'"
    r = _xmlonly(
        "-Title",
        "CO-29",
        "-Message",
        "FRASE LITERAL primero",
        "-OpenUri",
        uri,
    )
    root = _parse_xmlonly(r)
    assert _actions(root) == [
        ("Entendido", "system", "dismiss"),
        ("Abrir sesion", "protocol", uri),
    ]


def test_caja1_urgente_mantiene_frase_de_160_y_anade_texto_fijo_separado():
    """RED: URGENTE usa un tercer text fijo; normal no lo usa."""
    phrase = "F" * 160
    urgent = _parse_xmlonly(_xmlonly("-Title", "CO-29", "-Message", phrase, "-Urgent"))
    urgent_texts = urgent.findall("visual/binding/text")
    assert urgent_texts[1].text == phrase
    assert urgent_texts[2].text == (
        "Entendido solo cierra el aviso; no es reconocer la causa. "
        "URGENTE vuelve a avisar a 30/60/120/240 min."
    )
    normal = _parse_xmlonly(_xmlonly("-Title", "CO-29", "-Message", phrase))
    assert len(normal.findall("visual/binding/text")) == 2


def test_caja_a_tabla_comun_de_tags_declara_el_esquema_de_python_y_ps1():
    """La tabla fija dos esquemas por compatibilidad con toasts vivos.

    No se unifican porque hacerlo cambiaria el Tag de toasts ya publicados;
    los Tags Python solo cambian si la clave empieza por ``flight-`` y ninguno
    de los productores actuales usa ese prefijo. El hash completo de PS1 solo
    lo ejerce un llamador PS1 directo; la migracion queda fuera de esta caja.
    """
    tags = ("a" * 64, "a" * 65, "a--b", "tag-")
    spec = importlib.util.spec_from_file_location(
        "comms_alert_common_tag_table", REPO / "scripts" / "flight" / "comms_alert.py"
    )
    comms_alert = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comms_alert)
    assert [comms_alert.tag_for_toast(tag) for tag in tags] == [
        "a" * 64,
        "flight-" + hashlib.sha256(("a" * 65).encode("utf-8")).hexdigest()[:57],
        "a--b",
        "tag-",
    ]
    outputs = []
    for tag in tags:
        r = _xmlonly(
            "-Title", "CO-29", "-Message", "FRASE LITERAL primero", "-Tag", tag
        )
        root = _parse_xmlonly(r)
        comment = _comment(root, "effective-tag=") or ""
        outputs.append(_decode_effective_tag(comment))
    assert outputs == [
        "a" * 64,
        hashlib.sha256(("a" * 65).encode("utf-8")).hexdigest(),
        "a--b",
        "tag-",
    ]


def test_caja1_xmlonly_tag_con_guiones_dobles_sigue_siend_xml_valido():
    """El comentario codificado es válido y reversible aunque el Tag contenga ``--``."""
    result = _xmlonly(
        "-Title",
        "CO-31",
        "-Message",
        "FRASE LITERAL primero",
        "-Tag",
        "go-a--b",
    )
    assert result.returncode == 0, result.stderr
    root = _parse_xmlonly(result)
    comment = _comment(root, "effective-tag=") or ""
    assert "--" not in comment
    assert _decode_effective_tag(comment) == "go-a--b"


def test_caja_a_xmlonly_tag_terminado_en_guion_es_valido_y_reversible():
    """El control negativo del saneador actual: un Tag terminado en ``-`` sigue parseando."""
    root = _parse_xmlonly(
        _xmlonly(
            "-Title",
            "CO-31",
            "-Message",
            "FRASE LITERAL primero",
            "-Tag",
            "tag-",
        )
    )
    comment = _comment(root, "effective-tag=") or ""
    assert _decode_effective_tag(comment) == "tag-"


def test_caja1_setting_disabled_es_fallo_y_no_toast_ok_con_doble():
    """RED: el gancho de doble Disabled debe salir rc 3 y declarar FALLO."""
    r = _run(
        "-Title",
        "CO-29",
        "-Message",
        "FRASE LITERAL primero",
        "-SimulateNotifierSetting",
        "Disabled",
        "-NoFlash",
    )
    assert r.returncode == 3
    assert "toast=FALLO" in r.stdout
    assert "toast=ok" not in r.stdout


def test_caja1_setting_unknown_tambien_es_fallo_por_la_rama_unica():
    """A1: cualquier Setting distinto de Enabled recorre la única rama de fallo."""
    r = _run(
        "-Title",
        "CO-29",
        "-Message",
        "FRASE LITERAL primero",
        "-SimulateNotifierSetting",
        "Unknown",
        "-NoFlash",
    )
    assert r.returncode == 3
    assert "toast=FALLO" in r.stdout and "toast=ok" not in r.stdout


def test_caja_b_fija_la_comprobacion_estructural_del_setting_real():
    """El tramo Windows queda diferido, pero la comparación productiva queda fijada."""
    assert re.search(
        r"^  if \(\$notifier\.Setting -ne 'Enabled'\) \{ throw "
        r'"notifier Setting=\$\(\$notifier\.Setting\)" \}$',
        _src(),
        re.MULTILINE,
    )


@pytest.mark.parametrize("uri", ["https://example.invalid/write", "t3code://otra-ruta"])
def test_caja1_open_uri_rechaza_esquema_distinto_de_t3code_sin_escribir(uri):
    """RED: solo se admite t3code://threads/... y no se ejecuta un URI externo."""
    r = _xmlonly(
        "-Title", "CO-29", "-Message", "FRASE LITERAL primero", "-OpenUri", uri
    )
    assert r.returncode == 2
    assert "OpenUri" in r.stderr
    assert "toast=ok" not in r.stdout


def test_caja1_appid_override_es_observable_y_no_registra():
    """RED: AppId debe ser único/configurable sin registrar nada por defecto."""
    r = _xmlonly(
        "-Title",
        "CO-29",
        "-Message",
        "FRASE LITERAL primero",
        "-AppId",
        "powershell-test",
    )
    root = _parse_xmlonly(r)
    assert _comment(root, "effective-app-id=") == "effective-app-id=powershell-test"


def test_caja1_appid_default_es_observable_y_no_registra():
    """RED: el AppId por defecto es el identificador actual de PowerShell."""
    r = _xmlonly("-Title", "CO-29", "-Message", "FRASE LITERAL primero")
    root = _parse_xmlonly(r)
    assert _comment(root, "effective-app-id=") == (
        "effective-app-id={1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
        "\\WindowsPowerShell\\v1.0\\powershell.exe"
    )
