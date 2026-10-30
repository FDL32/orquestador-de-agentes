"""Tests para los campos nuevos de handoff de relevo de sesion-rol (WOT-2026-136a).

Cada test lee su fuente por pathlib y verifica la presencia/ausencia de
cadenas literales requeridas por el work_plan WOT-2026-136a.
Los tests estan disenados para pasar en ROJO (10 fallan) y tras el VERDE
todos deben pasar (11 passed).

Test 2 es un INVARIANTE (ya pasa HOY, debe seguir pasando tras el VERDE).
Tests 1, 3, 4, 5, 6, 7, 8, 9, 10, 11 son discriminadores ROJO (fallan hoy).
"""

from __future__ import annotations

import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path


# Rutas absolutas del motor (se resuelven al importar el modulo, no al correr tests).
MOTOR_ROOT = Path(__file__).resolve().parents[2]
SESSION_HOP = MOTOR_ROOT / "prompts" / "session_hop.md"
T3_RELIEF = MOTOR_ROOT / "prompts" / "t3_role_session_relief.md"
PROTOCOL_PATH = MOTOR_ROOT / "docs" / "protocol" / "flight_supervision.md"

# ---------------------------------------------------------------------------
# Token constants (shared between D6 remission tests)
# ---------------------------------------------------------------------------

# Los nueve tokens que no deben aparecer en session_hop.md ni en sus remisiones.
TOKENS_AUSENCIA_HOP: list[str] = [
    "OPERACION_EN_CURSO",
    "mensaje_id",
    "SHA pedido",
    "siguiente accion segura",
    "ultima posicion leida",
    "autoritativo",
    "350k",
    "390-400k",
    "457 587",
]

# Tokens adicionales para la remision en session_hop.md Paso 5-ter.
TOKENS_AUSENCIA_REMISION_HOP: list[str] = [
    "valores a la fecha",
    "sin copia ejecutable",
    "prefijo",
    "modo",
    "intento",
]


def _extract_section(text: str, heading: str) -> str:
    """Extract body under a ## or ### heading matching the given heading prefix.

    Detects heading level dynamically so it works for both ## and ### headings.
    Stops at the next heading of equal or greater level.
    """
    lines = text.splitlines()
    in_section = False
    section_lines: list[str] = []
    found_level = 0
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("### "):
            level = 3
            h_text = stripped[4:]
        elif stripped.startswith("## "):
            level = 2
            h_text = stripped[3:]
        else:
            level = 0
            h_text = ""

        if level > 0 and h_text.startswith(heading):
            if not in_section:
                in_section = True
                found_level = level
                continue
            break

        if in_section:
            if level > 0 and level <= found_level:
                break
            section_lines.append(line)

    return "\n".join(section_lines).strip()


# ---------------------------------------------------------------------------
# Test 1: session_hop.md Paso 5-bis contiene bullet con contenido real
# ---------------------------------------------------------------------------


def test_session_hop_paso5bis_tiene_bullet_con_contenido_real():
    """Test 1: Paso 5-bis exige CONTENIDO real en DECISIONES/LATIDOS/OBREROS."""
    text = SESSION_HOP.read_text(encoding="utf-8")
    section = _extract_section(text, "Paso 5-bis: coordinacion T3")
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Paso 5-bis: coordinacion T3' -- el encabezado real no empata."
    )
    assert "DECISIONES / LATIDOS / OBREROS, con CONTENIDO real" in section, (
        "El bullet de Paso 5-bis no contiene la cadena exigida:"
        " 'DECISIONES / LATIDOS / OBREROS, con CONTENIDO real'"
    )


# ---------------------------------------------------------------------------
# Test 2: session_hop.md Paso 5-bis NO re-declara definicion completa (INVARIANTE)
# ---------------------------------------------------------------------------


def test_session_hop_paso5bis_no_redeclara_definicion_completa():
    """Test 2 (INVARIANTE): Paso 5-bis NO redeclara la definicion completa de OBREROS.

    La cadena 'ruta de sus informes' vive SOLO en t3_role_session_relief.md
    seccion 5. Si aparece en session_hop.md, es una redeclaracion X-09.
    ESTE TEST YA PASA HOY y debe seguir pasando tras el VERDE.
    """
    text = SESSION_HOP.read_text(encoding="utf-8")
    section = _extract_section(text, "Paso 5-bis: coordinacion T3")
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Paso 5-bis: coordinacion T3' -- el encabezado real no empata."
    )
    assert "ruta de sus informes" not in section, (
        "Paso 5-bis redeclara la definicion completa de OBREROS "
        "(contiene 'ruta de sus informes', que solo debe vivir en "
        "t3_role_session_relief.md seccion 5)."
    )


# ---------------------------------------------------------------------------
# Test 3: session_hop.md Salida item 9 exige contenido real
# ---------------------------------------------------------------------------


def test_session_hop_salida_item9_exige_contenido_no_solo_nombres():
    """Test 3: Salida item 9 exige contenido real, no solo nombres."""
    text = SESSION_HOP.read_text(encoding="utf-8")
    section = _extract_section(text, "Salida")
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Salida' -- el encabezado real no empata."
    )
    assert "DECISIONES, LATIDOS y OBREROS con contenido real" in section, (
        "El item 9 de Salida no contiene la cadena exigida:"
        " 'DECISIONES, LATIDOS y OBREROS con contenido real'"
    )


# ---------------------------------------------------------------------------
# Test 4: session_hop.md Paso 6-bis ya no dice known_unwired
# ---------------------------------------------------------------------------


def test_session_hop_paso6bis_ya_no_dice_known_unwired():
    """Test 4: El fichero session_hop.md completo NO contiene 'known_unwired'."""
    text = SESSION_HOP.read_text(encoding="utf-8")
    assert "known_unwired" not in text, (
        "El fichero session_hop.md contiene 'known_unwired', "
        "que debe haber sido eliminado."
    )


# ---------------------------------------------------------------------------
# Test 5: session_hop.md Paso 6-bis remite a BY-DESIGN
# ---------------------------------------------------------------------------


def test_session_hop_paso6bis_remite_a_by_design():
    """Test 5: Paso 6-bis contiene la referencia a BY-DESIGN."""
    text = SESSION_HOP.read_text(encoding="utf-8")
    section = _extract_section(
        text, "Paso 6-bis: audita el arranque contra si mismo antes de entregarlo"
    )
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Paso 6-bis: audita el arranque...' -- el encabezado real no empata."
    )
    assert "BY-DESIGN" in section, "El bloque de Paso 6-bis no contiene 'BY-DESIGN'."


# ---------------------------------------------------------------------------
# Test 6: t3_role_session_relief.md checkpoint minimo declara DECISIONES/LATIDOS/OBREROS
# ---------------------------------------------------------------------------


def test_relief_checkpoint_declara_decisiones_latidos_obreros():
    """Test 6: Contenido minimo de checkpoint incluye DECISIONES, LATIDOS, OBREROS."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "Contenido minimo")
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Contenido minimo' -- el encabezado real no empata."
    )
    assert "DECISIONES" in section, "Contenido minimo no menciona DECISIONES."
    assert "LATIDOS" in section, "Contenido minimo no menciona LATIDOS."
    assert "OBREROS" in section, "Contenido minimo no menciona OBREROS."
    assert "ruta de sus informes" in section, (
        "Contenido minimo no contiene 'ruta de sus informes'."
    )


# ---------------------------------------------------------------------------
# Test 7: excepcion relevo planificado declara estados (sin literal de sesion)
# ---------------------------------------------------------------------------


def test_relief_excepcion_relevo_planificado_declara_estados():
    """Test 7: Seccion de excepcion declara campos y transiciones.

    Scopeado a seccion 6: los estados se declaran en la excepcion de relevo.
    La regla de titularidad de la decision (E2) se asevera en
    test_relief_seccion_11_decision_saliente_muerto_sube_al_usuario.
    """
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "Excepcion: relevo planificado o self-hop")
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Excepcion: relevo planificado o self-hop' -- el encabezado real no empata."
    )
    assert "active_roles.<rol>.estado" in section, (
        "La excepcion no declara 'active_roles.<rol>.estado'."
    )
    assert "PENDIENTE_ACK" in section, "La excepcion no declara 'PENDIENTE_ACK'."
    assert "SALIENTE_MUERTO" in section, "La excepcion no declara 'SALIENTE_MUERTO'."
    assert "15 minutos" in section, "La excepcion no declara '15 minutos'."


# ---------------------------------------------------------------------------
# Test 8: decision SALIENTE_MUERTO exige 2 senales de progreso (scopeado a seccion 6)
# ---------------------------------------------------------------------------


def test_relief_decision_saliente_muerto_exige_dos_senales():
    """Test 8: La decision de completar desde SALIENTE_MUERTO exige 2 senales.

    Scopeado a la excepcion de la seccion 6: la decision remite a la regla de
    la seccion 11, nunca la toma el entrante, y exige las 2 senales verificadas.
    """
    text = T3_RELIEF.read_text(encoding="utf-8")
    section_6 = _extract_section(text, "Excepcion: relevo planificado o self-hop")
    assert len(section_6) > 0, (
        "Control positivo: _extract_section devolvio vacio para "
        "'Excepcion: relevo planificado o self-hop'."
    )
    section_6_ws = " ".join(section_6.split())
    assert "segun la regla de la seccion 11 (nunca el entrante)" in section_6_ws, (
        "La excepcion de la seccion 6 no remite a la regla de la seccion 11 "
        "ni excluye al entrante."
    )
    assert "exigiendo al menos 2 senales de progreso" in section_6_ws, (
        "La excepcion de la seccion 6 no exige 'al menos 2 senales de progreso'."
    )


def test_relief_seccion_11_decision_saliente_muerto_sube_al_usuario():
    """Regla E2: la decision sobre un SALIENTE_MUERTO sube al usuario por la cadena.

    Scopeado a la subseccion de la seccion 11, un aserto por clausula.
    """
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "Decision sobre un `SALIENTE_MUERTO`")
    assert len(section) > 0, (
        "Control positivo: _extract_section devolvio vacio para "
        "'Decision sobre un `SALIENTE_MUERTO`'."
    )
    section_ws = " ".join(section.split())
    assert "sube al USUARIO" in section_ws, (
        "E2: la decision no sube al usuario (titular de la autoridad)."
    )
    assert "La supervisora del saliente la escala" in section_ws, (
        "E2: falta la escalada por la cadena (la supervisora del saliente)."
    )
    assert "El entrante NUNCA se auto-ratifica" in section_ws, (
        "E2: falta la clausula de que el entrante nunca se auto-ratifica."
    )


def test_relief_escalada_seccion_10_supervisor_y_despues_usuario():
    """Nota m-r3-8 (a): la escalada de la seccion 10 nombra al supervisor y al usuario."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "10. Cadena de ancestros")
    assert len(section) > 0, (
        "Control positivo: _extract_section devolvio vacio para "
        "'10. Cadena de ancestros'."
    )
    section_ws = " ".join(section.split())
    assert "Escalada al supervisor de la coordinadora y despues al usuario" in (
        section_ws
    ), "m-r3-8: la escalada de la seccion 10 no cita supervisor y despues usuario."


def test_relief_escritor_del_roster_remite_a_who_edits_en_los_tres_sitios():
    """Nota m-r3-8 (b): las tres menciones del escritor del roster remiten a who_edits."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    text_ws = " ".join(text.split())
    assert (
        "(el escritor canonico, segun `rules.who_edits`, es el unico escritor)"
        in text_ws
    ), "m-r3-8: el bloque de modo del inicio no remite a `rules.who_edits`."
    assert (
        "campo declarado por este modulo, escrito por el escritor canonico "
        "segun `rules.who_edits`" in text_ws
    ), "m-r3-8: la seccion 1 no remite a `rules.who_edits`."
    assert (
        "se escribe por el escritor canonico segun `rules.who_edits` en el roster"
        in text_ws
    ), "m-r3-8: NON-GOAL no remite a `rules.who_edits`."


# ---------------------------------------------------------------------------
# Test 9: releer tras compactar usa t3_thread_read paginado
# ---------------------------------------------------------------------------


def test_relief_releer_tras_compactar_usa_thread_read_paginado():
    """Test 9: Subseccion 'Releer tras compactar' usa t3_thread_read y afterPosition."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    assert "Releer tras compactar" in text, "No se encontro 'Releer tras compactar'."
    assert "t3_thread_read" in text, "No se encontro 't3_thread_read'."
    assert "afterPosition" in text, "No se encontro 'afterPosition'."


# ---------------------------------------------------------------------------
# Test 10: cadena de ancestros declara tricotomia y registro
# ---------------------------------------------------------------------------


def test_relief_cadena_ancestros_declara_tricotomia_y_registro():
    """Test 10: Seccion de cadena de ancestros declara tricotomia y eventos."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    assert "Cadena de ancestros" in text, "No se encontro 'Cadena de ancestros'."
    assert "DESBORDADO" in text, "No se encontro 'DESBORDADO'."
    assert "NO VERIFICABLE" in text, "No se encontro 'NO VERIFICABLE'."
    assert "ancestor_unavailable" in text, "No se encontro 'ancestor_unavailable'."


# ---------------------------------------------------------------------------
# Test 11: preflight paso 4 remite a excepcion
# ---------------------------------------------------------------------------


def test_relief_preflight_paso4_remite_a_la_excepcion():
    """Test 11: Paso 4 de Secuencia de preflight remite a la excepcion."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "Secuencia de preflight")
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Secuencia de preflight' -- el encabezado real no empata."
    )
    assert "salvo la excepcion" in section, (
        "La seccion 'Secuencia de preflight' no contiene 'salvo la excepcion'."
    )
    # Verificar que 'Nunca lanzar el sucesor' y 'salvo la excepcion' estan en la misma linea
    lines_with_nunca = [
        ln for ln in section.splitlines() if "Nunca lanzar el sucesor" in ln
    ]
    assert len(lines_with_nunca) >= 1, (
        "No se encontro una linea con 'Nunca lanzar el sucesor'."
    )
    # La linea debe contener tambien 'salvo la excepcion'
    found = False
    for line in lines_with_nunca:
        if "salvo la excepcion" in line:
            found = True
            break
    assert found, (
        "La linea 'Nunca lanzar el sucesor' no contiene 'salvo la excepcion' "
        "en la misma linea."
    )


# ---------------------------------------------------------------------------
# Ronda extra (simulacro de sucesor frio previo): item 10 de Salida,
# PENDIENTE/TOMADA en DECISIONES, y Ancla de linaje con HEAD medido.
# ---------------------------------------------------------------------------


def test_session_hop_salida_item10_exige_contenido_no_solo_nombres():
    """Test 12: Salida item 10 exige CADENA_CONSULTA/AUTORIDAD/PROXIMO_PASO reales."""
    text = SESSION_HOP.read_text(encoding="utf-8")
    section = _extract_section(text, "Salida")
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Salida' -- el encabezado real no empata."
    )
    assert "CADENA_CONSULTA, AUTORIDAD y PROXIMO_PASO con contenido real" in section, (
        "El item 10 de Salida no contiene la cadena exigida:"
        " 'CADENA_CONSULTA, AUTORIDAD y PROXIMO_PASO con contenido real'"
    )


def test_session_hop_salida_item10_no_redeclara_definicion_completa():
    """Test 13 (INVARIANTE): item 10 NO redeclara la definicion completa de PROXIMO_PASO.

    La frase 'el comando exacto que la ejecuta o verifica' vive SOLO en
    t3_role_session_relief.md seccion 5. Si aparece en session_hop.md, es una
    redeclaracion X-09. ESTE TEST YA PASA HOY y debe seguir pasando tras el VERDE.
    """
    text = SESSION_HOP.read_text(encoding="utf-8")
    section = _extract_section(text, "Salida")
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Salida' -- el encabezado real no empata."
    )
    assert "el comando exacto que la ejecuta o verifica" not in section, (
        "Salida redeclara la definicion completa de PROXIMO_PASO "
        "(contiene la frase que solo debe vivir en "
        "t3_role_session_relief.md seccion 5)."
    )


def test_relief_decisiones_marca_pendiente_o_tomada():
    """Test 14: Contenido minimo exige marcar cada DECISION como PENDIENTE/TOMADA."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "Contenido minimo")
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Contenido minimo' -- el encabezado real no empata."
    )
    assert "PENDIENTE" in section, "Contenido minimo no menciona 'PENDIENTE'."
    assert "TOMADA" in section, "Contenido minimo no menciona 'TOMADA'."


def test_session_hop_ancla_de_linaje_lleva_head_medido():
    """Test 15: item 3 de Salida promete que Ancla de linaje lleva el HEAD medido."""
    text = SESSION_HOP.read_text(encoding="utf-8")
    section = _extract_section(text, "Salida")
    assert len(section) > 0, (
        "Control positivo del helper: _extract_section devolvio vacio para "
        "'Salida' -- el encabezado real no empata."
    )
    assert "que SI lleva el HEAD medido" in section, (
        "El item 3 de Salida no promete explicitamente que 'Ancla de linaje' "
        "lleve el HEAD medido mas reciente."
    )


# ---------------------------------------------------------------------------
# Tests WOT-2026-136g: DoD de autoridad, supervision, relevo y ventana
# ---------------------------------------------------------------------------


def test_dod_1_seccion_11_cuatro_elementos():
    """Test 16 (DoD 1): seccion 11 tiene los cuatro elementos."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(
        text, "11. Autoridad, supervision y relevo de la coordinadora"
    )
    assert len(section) > 0, (
        "Control positivo: seccion 11 no encontrada -- el encabezado no empata."
    )
    section_ws = " ".join(section.split())
    # (i) Precondicion mecanica: tres piezas por separado
    assert "dictamen del Revisor" in section_ws, (
        "DoD 1 (i): 'dictamen del Revisor' no encontrado en seccion 11."
    )
    assert "gates re-ejecutados" in section_ws, (
        "DoD 1 (i): 'gates re-ejecutados' no encontrado en seccion 11."
    )
    assert "FLT" in section_ws, "DoD 1 (i): 'FLT' no encontrado en seccion 11."
    # (ii) Supervision estructural: "vigila con su latido" y la frase anterior
    assert "vigila con su latido" in section_ws.lower(), (
        "DoD 1 (ii): 'vigila con su latido' no encontrado en seccion 11."
    )
    assert "no tiene autoridad propia" in section_ws.lower(), (
        "DoD 1 (ii): 'no tiene autoridad propia' no encontrado en seccion 11."
    )
    # (iii) Cierre al relevar: "cascada de contexto" y la frase inmediata anterior
    assert "cascada de contexto" in section_ws, (
        "DoD 1 (iii): 'cascada de contexto' no encontrado en seccion 11."
    )
    assert "pasa a ser supervisora" in section_ws, (
        "DoD 1 (iii): 'pasa a ser supervisora' no encontrado en seccion 11."
    )
    # (iv) Lista de traspaso: los cuatro pasos
    assert "supervisor := saliente" in section_ws, (
        "DoD 1 (iv): paso 1 'supervisor := saliente' no encontrado."
    )
    assert "asentar al supervisor anterior" in section_ws.lower(), (
        "DoD 1 (iv): paso 2 'Asentar al supervisor anterior' no encontrado."
    )
    assert (
        "anadir al supervisor anterior a la cascada de contexto" in section_ws.lower()
    ), (
        "DoD 1 (iv): paso 3 'Anadir al supervisor anterior a la cascada de contexto' no encontrado."
    )
    assert "escribir la excepcion explicita si la hay" in section_ws.lower(), (
        "DoD 1 (iv): paso 4 'Escribir la excepcion explicita si la hay' no encontrado."
    )


def test_dod_2_paso5ter_y_salida_cadena():
    """Test 17 (DoD 2): Paso 5-ter y 'cadena de supervision del relevo' en Salida."""
    # Paso 5-ter en session_hop.md
    text_hop = SESSION_HOP.read_text(encoding="utf-8")
    section_p5ter = _extract_section(
        text_hop, "Paso 5-ter: cerrar y asentar al relevar"
    )
    assert len(section_p5ter) > 0, (
        "DoD 2: 'Paso 5-ter' no encontrado en session_hop.md."
    )
    # Puntero a seccion 11 en el cuerpo del paso
    assert "seccion 11" in section_p5ter, (
        "DoD 2: Paso 5-ter no remite a la seccion 11 del prompt de relevo."
    )
    # Frase unica en Salida
    section_salida = _extract_section(text_hop, "Salida")
    assert "cadena de supervision del relevo" in section_salida, (
        "DoD 2: Salida no contiene la frase unica 'cadena de supervision del relevo'."
    )
    # El item 11 lleva la frase como etiqueta Y en su cuerpo: sin anclar la
    # etiqueta, quitar solo el encabezado del item dejaria el aserto verde.
    assert "11. Cadena de supervision del relevo:" in section_salida, (
        "DoD 2: Salida no contiene el item 11 'Cadena de supervision del relevo:'."
    )


def test_dod_4_regex_sesion_names():
    """Test 18 (DoD 4): censar ocurrencias de nombres de sesion en ambos prompts."""
    regex = r"\b(SUPERVISOR|OR|IM|TR)-[0-9]+(\.[0-9]+)?\b"
    relief_text = T3_RELIEF.read_text(encoding="utf-8")
    hop_text = SESSION_HOP.read_text(encoding="utf-8")
    relief_matches = re.findall(regex, relief_text)
    hop_matches = re.findall(regex, hop_text)
    total = len(relief_matches) + len(hop_matches)
    assert total == 0, (
        f"DoD 4: {total} ocurrencias de nombres de sesion detectadas "
        f"(relief={len(relief_matches)}, hop={len(hop_matches)}). "
        "Denominador: 2 ficheros. El censo DESPUES del VERDE debe ser 0."
    )


def test_dod_5_ausencia_tokens_hop():
    """Test 19 (DoD 5, INVARIante): tokens nuevos de relevo NO estan en session_hop.md.

    El test nace VERDE: los tokens de este plan son unicos del prompt de relevo.
    Insertar cualquiera de estos tokens en session_hop.md cae en ROJO.
    """
    text_hop = SESSION_HOP.read_text(encoding="utf-8")
    for token in TOKENS_AUSENCIA_HOP:
        assert token not in text_hop, (
            f"DoD 5: '{token}' aparece en session_hop.md. "
            "Estos tokens son unicos del prompt de relevo."
        )


def test_dod_6_operacion_en_curso():
    """Test 20 (DoD 6): OPERACION_EN_CURSO con 7 subcampos en Contenido minimo."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "Contenido minimo")
    assert len(section) > 0, (
        "Control positivo: seccion 'Contenido minimo' no encontrada."
    )
    section_ws = " ".join(section.split())
    # Los 7 subcampos como una cadena ordenada dentro de la seccion
    campo = "OPERACION_EN_CURSO"
    assert campo in section, (
        "DoD 6: 'Contenido minimo' no contiene 'OPERACION_EN_CURSO'."
    )
    # UNA sola cadena ordenada: 'estado' y 'operacion' ya aparecen sueltos en la
    # seccion, asi que un aserto por palabra seria una floor assertion.
    cadena = (
        "`operacion`, `mensaje_id`, `destinatario`, `SHA pedido`, `estado`, "
        "`siguiente accion segura`, `ultima posicion leida`"
    )
    assert cadena in section_ws, (
        "DoD 6: 'Contenido minimo' no contiene los siete subcampos de "
        "OPERACION_EN_CURSO como una cadena ordenada."
    )
    # Marca de autoritativo
    assert "autoritativo" in section, (
        "DoD 6: 'Contenido minimo' no contiene 'autoritativo'."
    )
    # Regla de rehacer tras compactar (collapsando espacios/lineas)
    assert (
        "tras compactar, toda verificacion sin salida en fichero se rehace."
        in section_ws.lower()
    ), (
        "DoD 6: 'Contenido minimo' no contiene la frase exacta "
        "'tras compactar, toda verificacion sin salida en fichero se rehace'."
    )


def test_dod_6_cadencia_multipaso():
    """Test 21 (DoD 6): 'antes de cada operacion multipaso' en Cadencia."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "Cadencia")
    assert len(section) > 0, "Control positivo: seccion 'Cadencia' no encontrada."
    assert "antes de cada operacion multipaso" in section.lower(), (
        "DoD 6: 'Cadencia' no contiene 'antes de cada operacion multipaso'."
    )


def test_dod_7_ventana_no_relevo():
    """Test 22 (DoD 7): ventana de no-relevo en seccion 9."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "9. Self-hop")
    assert len(section) > 0, "Control positivo: seccion '9. Self-hop' no encontrada."
    # Las tres condiciones de la ventana de no-relevo, una asercion cada una
    assert "Builder vivo" in section, (
        "DoD 7: seccion 9 no contiene 'Builder vivo' en ventana de no-relevo."
    )
    assert "CONTRACT_AUDIT" in section, (
        "DoD 7: seccion 9 no contiene 'CONTRACT_AUDIT' en ventana de no-relevo."
    )
    assert "LISTO_PARA_INTEGRAR" in section, (
        "DoD 7: seccion 9 no contiene 'LISTO_PARA_INTEGRAR' en ventana de no-relevo."
    )


def test_dod_8_alarma_contexto():
    """Test 23 (DoD 8): alarma de contexto en seccion 9."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "9. Self-hop")
    assert len(section) > 0, "Control positivo: seccion '9. Self-hop' no encontrada."
    section_ws = " ".join(section.split())
    section_lower = section.lower()
    # Debe contener los umbrales de alarma (case-insensitive)
    assert "350k" in section, "DoD 8: seccion 9 no menciona el aviso a 350k."
    assert "390-400k" in section, (
        "DoD 8: seccion 9 no menciona el aviso fuerte a 390-400k."
    )
    # Regla de la segunda compactacion
    assert "segunda compactacion" in section_lower, (
        "DoD 8: seccion 9 no menciona la regla de la segunda compactacion."
    )
    # Frase de etiqueta: estimacion del vuelo, no medida ni umbral duro
    assert "estimacion del vuelo, no medida ni umbral duro" in section_ws.lower(), (
        "DoD 8: seccion 9 no contiene la frase de etiqueta "
        "'estimacion del vuelo, no medida ni umbral duro'."
    )


def test_dod_9_tabla_funciones():
    """Test 24 (DoD 9): tabla de funciones reestructurada en seccion 11."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(
        text, "11. Autoridad, supervision y relevo de la coordinadora"
    )
    assert len(section) > 0, "Control positivo: seccion 11 no encontrada."
    section_ws = " ".join(section.split()).lower()
    # Una frase unica por fila de la tabla, scopeada a seccion 11
    assert "vigila con su latido" in section_ws, (
        "DoD 9: fila Supervisor no contiene 'Vigila con su latido'."
    )
    assert "solo con la precondicion mecanica" in section_ws, (
        "DoD 9: fila Coordinadora no contiene 'solo con la precondicion mecanica'."
    )
    assert "autoridad fijada en los datos" in section_ws, (
        "DoD 9: fila Usuario no contiene 'Autoridad fijada en los datos'."
    )
    assert "prompts/builder_invocation_contract.md" in section, (
        "DoD 9: fila Manager no contiene 'prompts/builder_invocation_contract.md'."
    )
    assert "seccion 10 (cadena de ancestros) sin redeclararla" in section_ws, (
        "DoD 9: fila Consulta no contiene la frase completa de remision."
    )


def test_dod_10_resolucion_coordinadora():
    """Test 25 (DoD 10): resolucion de la coordinadora por un implantador."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(
        text, "11. Autoridad, supervision y relevo de la coordinadora"
    )
    assert len(section) > 0, "Control positivo: seccion 11 no encontrada."
    section_ws = " ".join(section.split())
    # Asertos separados para cada elemento de la resolucion
    assert "excepcion de identidad" in section_ws.lower(), (
        "DoD 10: seccion 11 no menciona 'excepcion de identidad'."
    )
    assert "orquestador_activo" in section, (
        "DoD 10: seccion 11 no menciona 'orquestador_activo'."
    )
    assert "estado `activa`" in section_ws.lower(), (
        "DoD 10: seccion 11 no menciona el estado `ACTIVA`."
    )
    assert "threadid" in section_ws.lower() and "difiere" in section_ws.lower(), (
        "DoD 10: seccion 11 no menciona que el threadId difiere del del lanzamiento."
    )
    assert (
        "lo declara al" in section_ws.lower() and "presentarse" in section_ws.lower()
    ), "DoD 10: seccion 11 no menciona que el implantador lo declara al presentarse."
    assert "se retire del registro" in section_ws, (
        "DoD 10: seccion 11 no menciona que la excepcion cae cuando orquestador_activo se retira del registro."
    )


def test_dod_11_fuente_cadena():
    """Test 26 (DoD 11): fuente de la cadena = roster, registro solo como consistencia."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(
        text, "11. Autoridad, supervision y relevo de la coordinadora"
    )
    assert len(section) > 0, "Control positivo: seccion 11 no encontrada."
    section_ws = " ".join(section.split())
    section_ws_lower = section_ws.lower()
    assert "la fuente de la cadena de supervision es el roster" in section_ws_lower, (
        "DoD 11: seccion 11 no contiene la frase completa "
        "'la fuente de la cadena de supervision es el roster'."
    )
    assert "el registro solo como consistencia" in section_ws_lower, (
        "DoD 11: seccion 11 no contiene la frase canonica "
        "'el registro solo como consistencia'."
    )


def test_dod_2_paso5ter_no_renumera():
    """Test 27 (DoD 2): Paso 5-ter no crea un Paso 8 (no se renumeran los pasos)."""
    text_hop = SESSION_HOP.read_text(encoding="utf-8")
    # No debe haber "## Paso 8" despues de Paso 5-bis
    section_5bis = _extract_section(text_hop, "Paso 5-bis: coordinacion T3")
    section_5ter = _extract_section(text_hop, "Paso 5-ter: cerrar y asentar al relevar")
    assert len(section_5bis) > 0, "Control positivo: 'Paso 5-bis' no encontrado."
    assert len(section_5ter) > 0, "Control positivo: 'Paso 5-ter' no encontrado."
    # Verificar que no hay Paso 8
    for line in text_hop.splitlines():
        if "## Paso 8" in line or "##Paso 8" in line:
            raise AssertionError(
                "DoD 2: existe 'Paso 8' -- los pasos no se renumeran, "
                "Paso 5-ter va despues de 5-bis sin crear un Paso 8."
            )


def test_dod_5_ausencia_tokens_skill():
    """Test 28 (DoD 5): tokens nuevos NO estan en la skill session-hop.

    INVARIANTE VERDE: los tokens de 136g son unicos del prompt de relevo.
    La skill DEBE existir: ausencia de skill => FALLA, no SKIP.
    """
    skill_path = MOTOR_ROOT / "skills" / "session-hop" / "SKILL.md"
    assert skill_path.exists(), (
        "La skill session-hop debe existir (ausencia de skill => FALLA, no SKIP)."
    )
    text_skill = skill_path.read_text(encoding="utf-8")
    for token in [
        "OPERACION_EN_CURSO",
        "mensaje_id",
        "SHA pedido",
        "siguiente accion segura",
        "autoritativo",
        "350k",
        "390-400k",
    ]:
        assert token not in text_skill, (
            f"DoD 5: '{token}' aparece en la skill session-hop. "
            "Estos tokens son unicos del prompt de relevo."
        )


def test_m_r3_2_no_mover_posicion_leida():
    """Nota m-r3-2: 'ultima posicion leida' y 'autoritativo' NO se mueven de seccion 9."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    section_9 = _extract_section(text, "9. Self-hop")
    assert len(section_9) > 0, "Control positivo: seccion '9. Self-hop' no encontrada."
    # Estos tokens ya existen en seccion 9 y no se deben mover
    assert "ultima posicion leida" in section_9, (
        "m-r3-2: 'ultima posicion leida' deberia seguir en seccion 9."
    )
    assert "autoritativo" in section_9, (
        "m-r3-2: 'autoritativo' deberia seguir en seccion 9."
    )


def test_dod_7c_frase_escape_eliminada():
    """DoD 7c (136g): la frase de escape 'Si el vuelo define otra fuente...' no esta."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    assert "Si el vuelo define otra fuente para alguna condicion" not in text, (
        "La frase de escape 'Si el vuelo define otra fuente...' debe haber sido eliminada."
    )


def test_dod_7b_encabezado_coherente():
    """DoD 7b (136g): el encabezado de la ventana dice 'relevo planificado o self-hop'.

    El cuerpo ya menciona self-hop; el encabezado debe ser coherente.
    """
    text = T3_RELIEF.read_text(encoding="utf-8")
    assert "### Ventana de no-relevo (relevo planificado o self-hop)" in text, (
        "El encabezado debe ser '### Ventana de no-relevo (relevo planificado o self-hop)'."
    )


# ---------------------------------------------------------------------------
# Tests WOT-2026-136h: protocolo de supervision de vuelo (flight_supervision.md)
# ---------------------------------------------------------------------------


# Los ocho nombres de campo de la politica de cuenta se construyen por FRAGMENTOS: este
# fichero no puede repetirlos literales porque es un fichero versionado y el censo del
# DoD 2 lo recorre como a cualquier otro (no se excluye a si mismo).
CAMPOS_POLITICA_CUENTA: tuple[str, ...] = tuple(
    "_".join(partes)
    for partes in (
        ("soft", "freeze", "block", "pct"),
        ("hard", "stop", "block", "pct"),
        ("enter", "when", "block", "pct", "le"),
        ("harbor", "block", "pct", "max"),
        ("leave", "when", "block", "pct", "ge"),
        ("min", "dwell", "min"),
        ("enter", "requires", "consecutive", "valid", "readings"),
        ("max", "moves", "per", "tick"),
    )
)
# Valores a la fecha declarados en la tabla del protocolo; el dato vivo es el roster.
VALORES_VIGENTES_2026_10_30: dict[str, str] = dict(
    zip(
        CAMPOS_POLITICA_CUENTA,
        ("92", "97", "60", "80", "90", "45", "2", "1"),
        strict=True,
    )
)
PROTOCOLO_REL = "docs/protocol/flight_supervision.md"
FIXTURE_136C_REL = "tests/fixtures/wot_2026_136c/pre_or7/flight_roster.json"
HELPER_ENVIOS = MOTOR_ROOT / "scripts" / "flight" / "send_with_ledger.py"
ACCION_SOFT_ROSTER = (
    "FREEZE de tickets nuevos: las sesiones terminan el ticket en curso y paran"
)
ACCION_HARD_ROSTER = (
    "mover PRECEDE a interrumpir: si hay refugio valido (cuenta de refugio con "
    f"block_pct <= account_policy.{CAMPOS_POLITICA_CUENTA[3]} y lectura fresca, "
    "stale=false) se mueve el hilo segun account_policy; t3_thread_interrupt de "
    "implantacion y triaje si NO hay refugio valido o la lectura esta stale o nula; "
    "el ticket queda aparcado con su estado escrito"
)
ACCION_HARD_REGLA_P1 = "interrupt de implantadores, precede a todo"
CLAUSULA_NUMBERS_SOURCE = "si difiere de este bloque manda ese fichero hasta retirarlo"
CADENCIA_ROSTER = "cada latido de la orquestadora y antes de autorizar un ticket nuevo"


# Linea EXACTA de remision de los dos prompts: nombra el documento y las secciones, con
# el titulo de cada una, y nada mas (ni criterio ni prosa paralela).
REMISION_EXACTA = (
    "- `docs/protocol/flight_supervision.md` secciones 5 a 7: regla de cuenta, "
    "envios entre sesiones y ledger."
)


def _normalizar(texto: str) -> str:
    """Before: texto cualquiera. During: colapsa cada racha de espacios y saltos.
    After: devuelve el texto en una sola linea, comparable con una cita literal."""
    return " ".join(texto.split())


# Condiciones LITERALES de la regla de cuenta, UNA por fragmento, tal como las fija la
# fuente (P1-P8 y alcance). Cada fragmento se busca en SU clausula o subseccion, no en la
# seccion 5 entera: en la entera lo veria tambien otra frase y el borrado no caeria. Los
# nombres de sesion y de cuenta de la fuente se transcriben como roles (N5).
ORDEN_PRECEDENCIA = "Las clausulas P1 a P8 se aplican en este orden de precedencia."
CONDICIONES_CLAUSULA: dict[str, tuple[str, ...]] = {
    "1": (
        'roster `quota.reserve_for_orquestadora`: "la orquestadora para sus propios '
        'bucles en soft; conserva margen para cerrar e integrar"',
    ),
    "2": (
        "hilo en preferida",
        "preferida.block_pct >= 90",
        "refugio.block_pct < 90",
        "mover a refugio AHORA",
        "(el dwell NO aplica a salir)",
        "Si ambas >= 90: no mover, FREEZE soft y avisar a la supervisora directa de la "
        "coordinadora (cadena de supervision del roster)",
    ),
    "3": (
        "TODAS a la vez",
        "(maximo de ventanas, venga de la ventana que venga:",
        "si la bloqueante es la semanal vale igual mientras este <= 60",
        "si la semanal supera 60 no se entra, porque un reset de 5h no la alivia",
        ") <= 60 en DOS lecturas consecutivas validas",
        "stale=false, no nulas",
        "2 min entre ellas o la del tick anterior del ledger",
        "refugio.block_pct <= 80",
        "no ambas >= 90",
        "hilo no running (hueco natural)",
        "ningun movimiento de ese hilo en los ultimos 45 min",
        "no haber hecho VOLVER desde el ultimo reset de la cuenta preferida",
    ),
    "4": (
        "Banda 61..89:** no mover",
        "Sin historial de ritmo: un solo hilo de cebo",
        "esperar 2 ticks antes de mover otro",
        "Maximo 1 movimiento por tick",
        "Orden de movimiento (roster `quota.account_policy.move_order`): "
        "implantacion y despues triaje",
    ),
    "5": (
        "monitor stale, nulo o con error",
        "proveedor no mapeado",
        "hilo fuera de alcance",
        "no mover y anotar",
        "Nunca inventar valores",
    ),
    "6": (
        "Registro y aviso en cada movimiento",
        "ledger, una linea en `roster_changes.jsonl` (by/change/detail/reason)",
        "aviso por `t3_thread_send` (mode=queue, prefijo `mcp:`) al hilo movido",
        "`t3_thread_configure` aplica en el PROXIMO turno",
    ),
    "7": (
        "DOS lecturas",
        "la configuracion del hilo (`t3_thread_configuration`)",
        "el proveedor efectivo del SIGUIENTE run (`recentRuns[0].providerInstanceId`)",
        "sin `parent_not_active`",
        "Si falla: VOLVER y avisar al usuario",
    ),
    "8": (
        "no altera un despacho ya lanzado",
        "se acepta fuera de frontera de ticket SOLO con el hilo no running",
        "nunca durante un turno de verificacion de commit",
    ),
}
CONDICIONES_SUBSECCION: dict[str, tuple[str, ...]] = {
    "Alcance": (
        "implantacion y triaje si hay uno vivo",
        "se comprueba con `t3_thread_list`, NO con el registro de sesiones, "
        "que esta desfasado",
        "P2 VOLVER y P3 IR los aplica el latido de la coordinadora vigente",
        "`orquestador_activo` del registro de sesiones",
        "NUNCA sesiones supervisoras ni asentadas",
        "VOLVER lo ejecuta su supervisora directa",
        "`cadena_consulta`, posicion 1",
        "desde su latido",
        "preferida.block_pct >= 90",
        "refugio.block_pct < 90",
        "ambas lecturas con stale=false",
        "la coordinadora no esta running",
        "no existe marca de NO_MOVER",
        "el run de la supervisora tiene cupo",
        "Verificacion P7 con dos lecturas",
        "VOLVER es MANUAL del usuario y se avisa por el buzon de la supervisora",
        "La coordinadora no se mueve a si misma",
        "P3 IR sobre la coordinadora: no se automatiza; la mueve el usuario",
    ),
    "Estado de las fuentes": (
        "No transcrito (sigue en la fuente, por seccion)",
        "el objetivo de la regla",
        "inferencia por comportamiento no verificada por la configuracion oficial",
        "Lo que esta regla NO decide",
        "el latido de reset con su invariante de latidos",
        "Adaptaciones al transcribir (declaradas)",
        'como "la supervisora directa de la coordinadora (cadena de supervision '
        'del roster)"',
        'queda como "un solo hilo de cebo"',
        "se omite el parentesis explicativo de la fuente sobre el canal del despacho",
        # Bloque `quota` del roster (BA02 R3, MAJOR-1/MINOR): cada exclusion declarada.
        'la frase de procedencia de P1 ("Los dos son del roster y no se redefinen '
        'aqui"): no es una condicion',
        "`quota.account_policy.supersedes_cc_watch` (alcance de una regla personal "
        "del usuario",
        "ni los metadatos del bloque `quota` (`source`, que es el comando del monitor "
        "y una ruta de maquina, `version`, `updated_at` y `updated_by`) ni la nota de "
        'esquema "sin claves de rol" de `quota.account_policy.scope`',
        "(4) el Alcance de la fuente y la cola de `numbers_source` nombran sesiones "
        'concretas: el protocolo no las nombra y las sustituye por "NUNCA sesiones '
        'supervisoras ni asentadas"',
        "(5) en P6 la fuente nombra el fichero del ledger: el protocolo no lo "
        "transcribe, porque la ruta del ledger va siempre por argumento",
    ),
    # Punteros a los campos del roster que el documento promete transcribir.
    "5. Regla de cuenta (contrato)": (
        "`quota.account_policy.preferred_account`",
        "`quota.account_policy.harbor_account`",
        "`proveedor de cuenta de refugio` vive en `quota.account_policy.provider_map`",
    ),
    "Cuando se mira cada umbral": (
        "maximo de las ventanas (5h y semanal) de la cuenta donde corre el hilo "
        "(`quota.account_policy.block_pct_definition`)",
    ),
    "6. Envios entre sesiones": (
        "debe tener el prefijo `mcp:`",
        "Un registro previo `enviado` NO es terminal",
        "`check` autoriza UN reintento",
        "rehusando cuando ya hay dos registros fallidos del mismo `mensaje_id`",
        "primero `parent_not_active` (rehuso), despues `enviado` (no terminal, "
        "autoriza), despues otros fallos con tope de 2 de `thread_not_found` y "
        "`error`. Un `resultado` fuera del vocabulario cerrado no cuenta como fallo",
        "Nunca por valor de defecto",
    ),
    "7. Ledger de envios": (
        "lo pone SIEMPRE el reloj del helper, nunca un argumento",
        "rc 0 incluso con legacy; rc 2 solo si el fichero no se puede leer",
        "`check` AUTORIZA (no hay intentos previos) y `record` lo crea. El validador "
        "sale rc 2 (ilegible)",
        "Ante un ledger inexistente o ilegible el helper es ADVISORY: `check` "
        "autoriza y no sale rc 2",
        "`check` autoriza. El validador informa 0 lineas, rc 0",
        "`check` la IGNORA al contar intentos. El validador la cuenta como no-JSON",
        "se lee bien (`splitlines`); `record` la completa con salto antes de anadir",
        "se aplica sobre los registros del mismo id",
        "`ts` lo pone el reloj del helper; `by` es argumento obligatorio no vacio",
    ),
}


def _fragmentos_que_faltan(ambito: str, fragmentos: tuple[str, ...]) -> list[str]:
    """Before: `ambito` es el texto de UNA clausula o subseccion; `fragmentos` son citas.

    During: normaliza el espacio del ambito (el markdown envuelve lineas) y busca cada
    cita literal.
    After: la lista de citas que NO estan; vacia si el ambito las lleva todas.
    """
    texto = _normalizar(ambito)
    return [f for f in fragmentos if f not in texto]


def _clausulas_de_la_regla(texto: str) -> dict[str, str]:
    """Before: `texto` es el protocolo; la subseccion `Clauses de la regla` existe.

    During: extrae esa subseccion y reparte sus items `- **P<n>` por numero.
    After: {numero: cuerpo de la clausula}; vacio si la subseccion no existe.
    """
    seccion = _extract_section(texto, "Clauses de la regla")
    return {
        n: _normalizar(cuerpo)
        for n, cuerpo in re.findall(
            r"^- \*\*P(\d)\b(.*?)(?=^- \*\*P\d|\Z)", seccion, flags=re.M | re.S
        )
    }


def _filas_tabla_valores(seccion: str) -> dict[str, list[str]]:
    """Before: texto de la subseccion con la tabla markdown de valores vigentes.

    During: parsea cada fila `| campo | valor | fuente |` y conserva solo las filas
    cuya primera celda es un campo de la politica (la cabecera y el separador no lo son).
    After: {campo: [celdas]}; una fila duplicada hace fallar el test (no se pisa).
    """
    filas: dict[str, list[str]] = {}
    for linea in seccion.splitlines():
        if not linea.lstrip().startswith("|"):
            continue
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) >= 2 and celdas[0] in CAMPOS_POLITICA_CUENTA:
            assert celdas[0] not in filas, f"fila duplicada en la tabla: {celdas[0]}"
            filas[celdas[0]] = celdas
    return filas


def _cargar_text_extensions() -> frozenset[str]:
    """Before: `scripts/encoding_guard.py` existe en el motor.

    During: lo carga por ruta (registrado en `sys.modules` antes de ejecutarlo, como
    exige un modulo con anotaciones) y lee su `TEXT_EXTENSIONS`.
    After: devuelve la fuente de verdad de sufijos de texto; si no carga, el test FALLA.
    """
    ruta = MOTOR_ROOT / "scripts" / "encoding_guard.py"
    spec = importlib.util.spec_from_file_location("encoding_guard_136h", ruta)
    assert spec is not None and spec.loader is not None, f"no se puede cargar {ruta}"
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["encoding_guard_136h"] = modulo
    try:
        spec.loader.exec_module(modulo)
    except Exception:
        sys.modules.pop("encoding_guard_136h", None)
        raise
    return frozenset(modulo.TEXT_EXTENSIONS)


def _universo_versionado() -> list[str]:
    """Before: el motor es un repositorio git y `git` esta en el PATH.

    During: `git ls-files` y filtro por los sufijos de `TEXT_EXTENSIONS`.
    After: rutas relativas de los ficheros de texto versionados; si git falla el test
    FALLA con la causa (no se salta).
    """
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=str(MOTOR_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AssertionError(f"git ls-files no disponible: {exc}") from exc
    sufijos = _cargar_text_extensions()
    return sorted(f for f in res.stdout.splitlines() if f and Path(f).suffix in sufijos)


def _censo_campos_politica(
    excepciones: set[str], universo: list[str]
) -> tuple[list[str], int, int]:
    """Before: `universo` son rutas relativas a `MOTOR_ROOT`.

    During: lee cada fichero no excluido como UTF-8 y busca los ocho nombres de campo.
    After: (aciertos, leidos, no_leidos); un fichero ilegible cuenta en `no_leidos`, no
    desaparece del denominador.
    """
    aciertos: list[str] = []
    leidos = 0
    no_leidos = 0
    for rel in universo:
        if rel in excepciones:
            continue
        try:
            texto = (MOTOR_ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            no_leidos += 1
            continue
        leidos += 1
        if any(campo in texto for campo in CAMPOS_POLITICA_CUENTA):
            aciertos.append(rel)
    return aciertos, leidos, no_leidos


def _constante_del_helper(nombre: str) -> frozenset[str]:
    """Before: `scripts/flight/send_with_ledger.py` define `nombre = frozenset({...})`.

    During: parsea el fichero con `ast` (no lo importa) y evalua el literal del conjunto.
    After: el conjunto de cadenas; si la constante no existe el test FALLA.
    """
    arbol = ast.parse(HELPER_ENVIOS.read_text(encoding="utf-8"))
    for nodo in arbol.body:
        if (
            isinstance(nodo, ast.AnnAssign)
            and isinstance(nodo.target, ast.Name)
            and nodo.target.id == nombre
            and isinstance(nodo.value, ast.Call)
        ):
            return frozenset(ast.literal_eval(nodo.value.args[0]))
    raise AssertionError(f"el helper no define la constante {nombre}")


def test_dod_136h_protocolo_siete_secciones():
    """DoD 136h: el protocolo tiene las siete secciones con encabezados fijos."""
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    secciones_esperadas = [
        "1. Alcance y fuentes",
        "2. Autoridad",
        "3. Supervision estructural",
        "4. Relevo",
        "5. Regla de cuenta (contrato)",
        "6. Envios entre sesiones",
        "7. Ledger de envios",
    ]
    for sec in secciones_esperadas:
        assert "## " + sec in text, f"Falta seccion: '## {sec}'."


def test_dod_136h_protocolo_punteros_a_campos():
    """DoD 136h: secciones 2-4 son INDICES (punteros a datos del roster/registro).

    Secciones 2-4 remiten al hogar normativo y listan campos de datos:
    - Seccion 2: active_roles (orquestador, supervisor)
    - Seccion 3: supervisor, cadena_contexto, excepcion_supervisor
    - Seccion 4: estado, predecessor_threadId
    """
    text = PROTOCOL_PATH.read_text(encoding="utf-8")

    # Seccion 2: debe mencionar active_roles y campos del roster
    section_2 = _extract_section(text, "2. Autoridad")
    assert len(section_2) > 0, "Control positivo: seccion 2 no encontrada."
    assert "active_roles" in section_2, "Seccion 2 no menciona campos del roster."

    # Seccion 3: debe mencionar supervisor y cadena_contexto
    section_3 = _extract_section(text, "3. Supervision estructural")
    assert len(section_3) > 0, "Control positivo: seccion 3 no encontrada."
    assert "supervisor" in section_3 or "supervisora" in section_3, (
        "Seccion 3 no menciona supervisor/supervisora."
    )
    assert "cadena_contexto" in section_3, (
        "Seccion 3 no menciona el campo de datos 'cadena_contexto' del roster."
    )
    assert "excepcion_supervisor" in section_3, (
        "Seccion 3 no menciona el campo de datos 'excepcion_supervisor' del roster."
    )

    # Seccion 4: debe mencionar campos de estado y predecessor_threadId
    section_4 = _extract_section(text, "4. Relevo")
    assert len(section_4) > 0, "Control positivo: seccion 4 no encontrada."
    assert "estado" in section_4, "Seccion 4 no menciona campo estado."
    assert "predecessor_threadId" in section_4, (
        "Seccion 4 no menciona 'predecessor_threadId'."
    )


def test_dod_136h_protocolo_punteros_a_hogar_normativo():
    """DoD 136h: cada seccion 2-4 remite a SU ancla en prompts/t3_role_session_relief.md.

    Cada seccion debe nombrar el hogar normativo (X-09) Y su propia referencia: las
    secciones 2 y 3 indexan la seccion 11 del prompt de relevo; la 4, las secciones 2-9.
    No basta el nombre del fichero: quitar la ancla de una seccion debe hacer fallar.
    """
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    referencias = {
        "2. Autoridad": "`prompts/t3_role_session_relief.md` seccion 11",
        "3. Supervision estructural": "`prompts/t3_role_session_relief.md` seccion 11",
        "4. Relevo": "`prompts/t3_role_session_relief.md` (secciones 2-9)",
    }
    for encabezado, referencia in referencias.items():
        seccion = _normalizar(_extract_section(text, encabezado))
        assert seccion, f"Control positivo: seccion '{encabezado}' no encontrada."
        assert referencia in seccion, (
            f"Seccion '{encabezado}' no cita su ancla propia: {referencia!r}."
        )


def test_dod_136h_protocolo_tabla_valores_vigentes():
    """DoD 2: la tabla `Valores vigentes a 2026-10-30 en el roster` fija cada PAR.

    Before: el protocolo existe. During: parsea las filas de la tabla (nunca busca el
    valor suelto en la seccion, que lo encontraria en otra frase) y compara el mapa
    campo-valor entero; comprueba tambien la columna de fuente de cada fila.
    After: falla si cambia un valor, falta una fila o la fuente apunta a otro bloque.
    """
    texto = PROTOCOL_PATH.read_text(encoding="utf-8")
    seccion = _extract_section(texto, "Valores vigentes a 2026-10-30 en el roster")
    assert seccion, "Control positivo: subseccion de valores vigentes no encontrada."
    filas = _filas_tabla_valores(seccion)
    assert {c: f[1] for c, f in filas.items()} == VALORES_VIGENTES_2026_10_30

    # La fuente de cada fila nombra el campo REAL del roster: los dos umbrales viven
    # en `quota`; los otros seis, en `quota.account_policy`.
    for campo, celdas in filas.items():
        prefijo = (
            "quota" if campo in CAMPOS_POLITICA_CUENTA[:2] else "quota.account_policy"
        )
        assert len(celdas) >= 3 and celdas[2].startswith(
            f"roster `{prefijo}.{campo}`"
        ), f"fuente de {campo} incorrecta: {celdas[2:]}"

    # Control positivo del parser: cambiar el valor de UNA fila (aunque el numero siga
    # apareciendo en otra frase de la seccion) hace caer la igualdad.
    fila_soft = f"| {CAMPOS_POLITICA_CUENTA[0]} | 92 |"
    assert fila_soft in seccion
    mutada = seccion.replace(fila_soft, f"| {CAMPOS_POLITICA_CUENTA[0]} | 93 |")
    assert {c: f[1] for c, f in _filas_tabla_valores(mutada).items()} != (
        VALORES_VIGENTES_2026_10_30
    )

    seccion_5 = _normalizar(_extract_section(texto, "5. Regla de cuenta (contrato)"))
    assert "ningun codigo ni prompt los lee de aqui" in seccion_5
    assert "dato vivo" in seccion_5


def test_dod_136h_protocolo_seccion_5_efecto_de_umbrales_y_discrepancia():
    """DoD 2: la seccion 5 cita el efecto de cada umbral de CADA fuente y declara el hueco.

    Before: el protocolo existe. During: busca cada cita literal (roster y regla de
    cuenta) en la seccion 5 normalizada y lee la subseccion de huecos. After: falla si
    falta una cita, si queda la deuda ya resuelta, si reaparece la cifra copiada del
    interrupt o si la contradiccion roster/regla deja de figurar como ABIERTA.
    """
    texto = PROTOCOL_PATH.read_text(encoding="utf-8")
    seccion_5 = _normalizar(_extract_section(texto, "5. Regla de cuenta (contrato)"))
    assert seccion_5, "Control positivo: seccion 5 no encontrada."
    # Cada cita se busca en la SUBSECCION que debe llevarla: la seccion 5 entera la
    # veria tambien en otra frase (p. ej. la de huecos) y no discriminaria.
    clausulas = _normalizar(_extract_section(texto, "Clauses de la regla"))
    cadencia = _normalizar(_extract_section(texto, "Cuando se mira cada umbral"))
    precedencia = _normalizar(_extract_section(texto, "Precedencia ante discrepancia"))
    for etiqueta, cita, donde in (
        ("accion soft del roster (P1)", ACCION_SOFT_ROSTER, clausulas),
        ("accion hard del roster (P1)", ACCION_HARD_ROSTER, clausulas),
        ("clausula P1 de la regla de cuenta", ACCION_HARD_REGLA_P1, clausulas),
        ("cadencia del roster", CADENCIA_ROSTER, cadencia),
        (
            "clausula de precedencia numbers_source",
            CLAUSULA_NUMBERS_SOURCE,
            precedencia,
        ),
    ):
        assert cita in donde, f"falta la cita literal: {etiqueta}."
    assert "numbers_source" in precedencia and "manda ese fichero" in precedencia

    huecos = _normalizar(_extract_section(texto, "Huecos detectados"))
    assert huecos, "Control positivo: subseccion de huecos no encontrada."
    assert "ABIERTO: efecto del umbral hard" in huecos
    # Segundo hueco: la regla (P5: stale o nulo => no mover) y el roster (stale o nulo
    # => interrumpir si no hay refugio valido) tambien difieren.
    assert "ABIERTO: lectura stale o nula" in huecos
    # Tercer hueco: el limite de concurrencia del ledger tambien figura como ABIERTO.
    assert "ABIERTO: escrituras concurrentes del ledger" in huecos
    assert "no mover y anotar" in huecos

    # Lo que NO debe quedar: la deuda ya resuelta y la cifra copiada como efecto.
    assert "Se implantaran como dato" not in texto
    assert "interrupt de implantadores 97" not in seccion_5
    assert "Ninguna ambiguedad" not in texto
    assert "Deuda declarada" not in texto


def test_dod_136h_censo_ocho_campos_de_la_politica():
    """DoD 2: ningun otro fichero versionado repite los ocho nombres de campo.

    Before: el motor es un repositorio git; el protocolo puede estar aun sin versionar.
    During: recorre `git ls-files` filtrado por `TEXT_EXTENSIONS` (mas el protocolo, para
    que el censo lo vea tambien antes del commit) y busca los ocho nombres.
    After: falla si un fichero fuera de las excepciones los repite, si el censo es
    ciego (sin excepciones no ve el protocolo ni el fixture) o si el denominador, los
    ficheros LEIDOS, no cuadra o hay ficheros ilegibles.

    EXCEPCIONES (cada una con su motivo): el protocolo (el DoD le manda declararlos) y
    el fixture congelado de 136c bajo `tests/fixtures/` (intocable por el plan). Este
    fichero NO se excluye: sus nombres estan construidos por fragmentos.
    """
    universo = sorted(set(_universo_versionado()) | {PROTOCOLO_REL})
    excepciones = {PROTOCOLO_REL, FIXTURE_136C_REL}
    assert FIXTURE_136C_REL in universo, "el fixture de 136c no esta versionado"

    # Control positivo: SIN excepciones el censo ve el protocolo y el fixture.
    sin_excepciones, _, _ = _censo_campos_politica(set(), universo)
    assert PROTOCOLO_REL in sin_excepciones and FIXTURE_136C_REL in sin_excepciones, (
        f"censo ciego: sin excepciones debia ver el protocolo y el fixture: {sin_excepciones}"
    )

    aciertos, leidos, no_leidos = _censo_campos_politica(excepciones, universo)
    excluidos = len(excepciones & set(universo))
    assert leidos > 0 and leidos + no_leidos == len(universo) - excluidos, (
        f"denominador incoherente: universo={len(universo)} excluidos={excluidos} "
        f"leidos={leidos} no_leidos={no_leidos}"
    )
    assert no_leidos == 0, f"ficheros de texto versionados ilegibles: {no_leidos}"
    assert aciertos == [], (
        f"ficheros versionados que repiten campos de la politica: {aciertos} "
        f"(universo={len(universo)} leidos={leidos})"
    )


def test_dod_136h_censo_ocho_campos_muerde_en_un_arbol_aislado(tmp_path, monkeypatch):
    """Control positivo del censo sobre un arbol que SI repite un campo.

    Before: un directorio temporal con un fichero limpio y otro con un nombre de campo.
    During: apunta `MOTOR_ROOT` al directorio y corre el mismo censo de produccion.
    After: el censo acierta SOLO el fichero con el campo y lo deja de acertar al
    excluirlo; con un fichero ilegible cuenta en `no_leidos` (no desaparece).
    """
    monkeypatch.setitem(globals(), "MOTOR_ROOT", tmp_path)
    (tmp_path / "limpio.md").write_text("sin campos de politica\n", encoding="utf-8")
    (tmp_path / "sucio.md").write_text(
        f"copia: {CAMPOS_POLITICA_CUENTA[5]} = 45\n", encoding="utf-8"
    )
    (tmp_path / "roto.md").write_bytes(b"\xff\xfe\x00 no es utf-8")
    universo = ["limpio.md", "sucio.md", "roto.md"]
    assert _censo_campos_politica(set(), universo) == (["sucio.md"], 2, 1)
    assert _censo_campos_politica({"sucio.md"}, universo) == ([], 1, 1)


def test_dod_136h_protocolo_cero_nombres_sesion():
    """DoD 136h: cero nombres de sesion en el protocolo."""
    regex = r"\b(SUPERVISOR|OR|CO|IM|TR)-[0-9]+(\.[0-9]+)?\b"
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    matches = re.findall(regex, text)
    total = len(matches)
    assert total == 0, (
        f"DoD 136h: {total} ocurrencias de nombres de sesion en el protocolo. "
        "Denominador: 1 fichero (flight_supervision.md). El censo DESPUES debe ser 0."
    )


def test_dod_136h_protocolo_cero_rutas_maquina():
    """DoD 136h: cero rutas absolutas de maquina en el protocolo."""
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    path_tokens = ["C:\\Users\\", "tmp_or8", "C:\\tmp", "/home/", "/Users/"]
    for token in path_tokens:
        assert token not in text, (
            f"DoD 136h: '{token}' aparece en el protocolo. "
            "El protocolo no debe contener rutas absolutas de maquina."
        )


def test_dod_136h_protocolo_regla_de_cuenta_en_roles():
    """DoD 136h: la regla de cuenta se transcribe en roles, no con nombres de sesion.

    El protocolo debe nombrar `cuenta preferida` y `cuenta de refugio` y
    `proveedor de cuenta de refugio`, pero NUNCA los nombres reales de cuentas
    `alvarovans`, `brabander` ni `claudeAgent`.
    """
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    seccion = _extract_section(text, "Clauses de la regla")
    assert seccion, "Control positivo: subseccion de clausulas no encontrada."
    # Las ocho clausulas son los items `- **P<n> ...` de la subseccion (una mencion
    # suelta como "ver P1" no cuenta como clausula).
    etiquetas = re.findall(r"^- \*\*P(\d)\b", seccion, flags=re.MULTILINE)
    assert etiquetas == [str(n) for n in range(1, 9)], etiquetas

    # La transcripcion perdia elementos de la regla de cuenta (P3, P5 en el simulacro y
    # P3 otra vez en BA05 R2): se fija CADA condicion literal de CADA clausula, en su
    # clausula, no solo su etiqueta ni dos frases.
    por_clausula = _clausulas_de_la_regla(text)
    assert sorted(por_clausula) == sorted(etiquetas), sorted(por_clausula)
    faltan = {
        n: _fragmentos_que_faltan(por_clausula[n], fragmentos)
        for n, fragmentos in CONDICIONES_CLAUSULA.items()
    }
    ausentes = {n: f for n, f in faltan.items() if f}
    assert ausentes == {}, (
        f"condiciones literales de la regla de cuenta ausentes de su clausula: {ausentes}"
    )
    assert ORDEN_PRECEDENCIA in _normalizar(seccion), "falta el orden de precedencia."

    # Los nombres de cuenta reales NO aparecen (solo roles).
    for nombre in ["alvarovans", "brabander", "claudeAgent"]:
        assert nombre not in text, (
            f"DoD 136h: '{nombre}' aparece en el protocolo. "
            "El protocolo debe usar roles, no nombres de cuenta reales."
        )

    # Los tres roles de cuenta SI figuran.
    texto_min = text.lower()
    for rol in (
        "cuenta preferida",
        "cuenta de refugio",
        "proveedor de cuenta de refugio",
    ):
        assert rol in texto_min, f"El protocolo no menciona el rol '{rol}'."


def test_dod_136h_protocolo_condiciones_literales_por_subseccion():
    """DoD 2/3/4: cada condicion literal del alcance, las fuentes y las secciones 6-7.

    Before: el protocolo existe. During: para cada subseccion de
    `CONDICIONES_SUBSECCION` extrae SU texto y busca sus citas literales (la cita se
    busca en su subseccion, no en el documento: en el entero la veria otra frase).
    After: falla nombrando la subseccion y la cita ausente; una subseccion vacia falla.
    """
    texto = PROTOCOL_PATH.read_text(encoding="utf-8")
    ausentes: dict[str, list[str]] = {}
    for encabezado, fragmentos in CONDICIONES_SUBSECCION.items():
        seccion = _extract_section(texto, encabezado)
        assert seccion, f"Control positivo: subseccion '{encabezado}' no encontrada."
        faltan = _fragmentos_que_faltan(seccion, fragmentos)
        if faltan:
            ausentes[encabezado] = faltan
    assert ausentes == {}, (
        f"condiciones literales ausentes de su subseccion: {ausentes}"
    )


def test_dod_136h_protocolo_condiciones_el_comprobador_muerde():
    """Control positivo de las dos tablas de condiciones: el comprobador NO es ciego.

    Before: el protocolo existe. During: quita de la clausula P3 la condicion que BA05
    R2 vio omitida y busca esa misma cita en una clausula ajena (P2). After: el
    comprobador la reporta ausente en los dos casos y, sobre el texto real, no reporta
    nada (el borrado es lo que cambia el resultado, no el comprobador).
    """
    texto = PROTOCOL_PATH.read_text(encoding="utf-8")
    por_clausula = _clausulas_de_la_regla(texto)
    cita = "2 min entre ellas o la del tick anterior del ledger"
    assert _fragmentos_que_faltan(por_clausula["3"], (cita,)) == []
    assert cita in por_clausula["3"]
    quitada = por_clausula["3"].replace(cita, "")
    assert _fragmentos_que_faltan(quitada, (cita,)) == [cita]
    # Ambito ajeno: la misma cita en la clausula P2 no cuenta.
    assert _fragmentos_que_faltan(por_clausula["2"], (cita,)) == [cita]
    # Todas las tablas apuntan a ambitos que existen (una clausula inexistente fallaria).
    assert set(CONDICIONES_CLAUSULA) <= set(por_clausula)


def test_dod_136h_protocolo_envios_entre_sesiones():
    """DoD 136h: seccion 6 fija mcp:, modos, un intento, codigos de salida."""
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    section_6 = _extract_section(text, "6. Envios entre sesiones")
    assert len(section_6) > 0, "Control positivo: seccion 6 no encontrada."
    assert "`mcp:`" in section_6, "Seccion 6 no menciona el prefijo `mcp:`."

    # El conjunto de modos es CERRADO y coincide con el que valida el helper: se parsea
    # la lista de la subseccion y se compara con la constante del codigo.
    modos = _normalizar(_extract_section(text, "Modos"))
    lista = re.search(r"admite[^:]*:\s*(?P<lista>[^.]+)\.", modos)
    assert lista is not None, "la subseccion Modos no lista el conjunto de modos."
    assert frozenset(re.findall(r"`([^`]+)`", lista.group("lista"))) == (
        _constante_del_helper("VALID_MODES")
    )

    # La regla de un intento y los codigos de salida, como frases completas.
    intento = _normalizar(
        _extract_section(text, "Un unico intento ante `parent_not_active`")
    )
    assert "`check` rehusa cualquier reintento (cero reintentos)" in intento
    assert '`resultado = "parent_not_active"`' in intento
    codigos = _normalizar(_extract_section(text, "Codigos de salida del helper"))
    assert "`0` = autorizado / escrito; `1` = rehusado" in codigos
    assert "`2` = uso o argumentos invalidos o error de entorno" in codigos
    assert "Nunca `3`" in codigos


def test_dod_136h_protocolo_declara_el_limite_de_concurrencia():
    """DoD 136h: el protocolo declara que el helper NO serializa las escrituras.

    Before: el protocolo existe. During: lee la subseccion `Limite: sin serializacion de
    escrituras` de la seccion 6. After: falla si falta alguna de las cinco afirmaciones
    (sin lock, intercalado de `record`, no atomicidad de `check`/`record`, helper
    ADVISORY, mitigacion = otro ticket); el contenido del ledger lo fija el plan
    ("append de una sola linea terminada en salto", helper "advisory").
    """
    texto = PROTOCOL_PATH.read_text(encoding="utf-8")
    limite = _normalizar(
        _extract_section(texto, "Limite: sin serializacion de escrituras")
    )
    assert limite, (
        "Control positivo: subseccion del limite de concurrencia no encontrada."
    )
    for afirmacion in (
        "no toma ningun lock",
        "pueden intercalar sus escrituras",
        "no son atomicos entre si",
        "El helper es ADVISORY",
        "seria otro ticket",
    ):
        assert afirmacion in limite, f"el limite no afirma: {afirmacion!r}."


def test_dod_136h_protocolo_ledger_esquema():
    """DoD 136h: seccion 7 fija las nueve claves, el vocabulario y la politica legacy.

    Before: el protocolo y el helper existen. During: lee el bloque de claves de la
    seccion 7 y el vocabulario de `resultado`, y los compara con las constantes del
    helper. After: falla si el protocolo y el codigo discrepan en una clave o en un valor.
    """
    texto = PROTOCOL_PATH.read_text(encoding="utf-8")
    seccion = _extract_section(texto, "7. Ledger de envios")
    assert seccion, "Control positivo: seccion 7 no encontrada."
    bloque = re.search(r"```\n(?P<claves>[^`]+?)\n```", seccion)
    assert bloque is not None, "la seccion 7 no contiene el bloque con el esquema fijo."
    claves = frozenset(c.strip() for c in bloque.group("claves").split(","))
    assert claves == _constante_del_helper("FIXED_KEYS")

    resultado = re.search(
        r"^- `resultado`: (?P<lista>.+)$", seccion, flags=re.MULTILINE
    )
    assert resultado is not None, "la seccion 7 no describe la clave `resultado`."
    assert frozenset(re.findall(r"`([^`]+)`", resultado.group("lista"))) == (
        _constante_del_helper("VALID_RESULTADOS")
    )

    seccion_ws = _normalizar(seccion)
    assert "se mide por CONJUNTO DE CLAVES, nunca por conteo" in seccion_ws
    assert "una linea es legacy si su conjunto de claves difiere del fijo" in seccion_ws


def test_dod_136h_protocolo_remision_en_relevo():
    """DoD 136h: t3_role_session_relief.md seccion 'Referencias cruzadas' remite al protocolo.

    La remision debe nombrar SOLO documento y seccion, sin criterio ni prosa paralela.
    Debe estar en una sola linea (o un unico item de lista) dentro de la seccion citada.
    """
    text = T3_RELIEF.read_text(encoding="utf-8")
    section = _extract_section(text, "Referencias cruzadas")
    assert len(section) > 0, (
        "Control positivo: seccion 'Referencias cruzadas' no encontrada."
    )
    lineas = _lineas_con_remision(section)
    assert len(lineas) == 1, (
        f"la remision debe estar en UNA linea de 'Referencias cruzadas', hay {len(lineas)}."
    )
    assert lineas[0] == REMISION_EXACTA, (
        f"la remision no tiene el formato exacto (solo documento y secciones): {lineas[0]!r}"
    )


def test_dod_136h_protocolo_remision_en_hop():
    """DoD 136h (D6): session_hop.md Paso 5-ter remite al protocolo en una sola linea.

    La remision debe nombrar SOLO documento y seccion, sin ninguno de los nueve
    tokens de `test_dod_5_ausencia_tokens_hop` ni los tokens de criterio como
    "valores a la fecha", "sin copia ejecutable".
    Debe estar en UNA sola linea (o en un unico item de lista) dentro de la seccion citada.
    """
    text = SESSION_HOP.read_text(encoding="utf-8")
    section = _extract_section(text, "Paso 5-ter: cerrar y asentar al relevar")
    assert len(section) > 0, "Control positivo: 'Paso 5-ter' no encontrado."
    lineas = _lineas_con_remision(section)
    assert len(lineas) == 1, (
        f"la remision debe estar en UNA linea del Paso 5-ter, hay {len(lineas)}."
    )
    assert lineas[0] == REMISION_EXACTA, (
        f"la remision no tiene el formato exacto (solo documento y secciones): {lineas[0]!r}"
    )

    # Los Nueve tokens de test_dod_5_ausencia_tokens_hop (definidos en el modulo).
    for token in TOKENS_AUSENCIA_HOP:
        assert token not in section, (
            f"Paso 5-ter contiene el token '{token}', prohibido en remisiones."
        )

    # Los tokens adicionales de criterio que no deben aparecer en la remision.
    for token in TOKENS_AUSENCIA_REMISION_HOP:
        assert token not in section, (
            f"Paso 5-ter contiene el token '{token}', que es criterio, "
            "no una remision de documento/seccion."
        )


def _lineas_con_remision(texto_seccion: str) -> list[str]:
    """Before: texto de una seccion de un prompt. During: filtra las lineas que citan el
    protocolo. After: esas lineas (una remision correcta es UNA linea)."""
    return [ln for ln in texto_seccion.splitlines() if "flight_supervision.md" in ln]


def _ejecutar_helper(*args: str) -> subprocess.CompletedProcess[str]:
    """Before: `scripts/flight/send_with_ledger.py` existe y `sys.executable` corre Python.

    During: lo ejecuta como proceso aparte (el camino de produccion) con los argumentos
    dados. After: devuelve el proceso terminado; no lanza por un rc distinto de 0.
    """
    return subprocess.run(
        [sys.executable, str(HELPER_ENVIOS), *args],
        capture_output=True,
        text=True,
        cwd=str(MOTOR_ROOT),
        check=False,
    )


def test_dod_136h_protocolo_declara_los_subcomandos_y_sus_argumentos():
    """DoD 136h: la seccion 6 nombra, como encabezados propios, los contratos del helper.

    Los contratos se EJECUTAN en `test_dod_136h_protocolo_codigos_del_helper_real`;
    aqui se fija que el protocolo los declara con el mismo texto.
    """
    texto = PROTOCOL_PATH.read_text(encoding="utf-8")
    seccion = _extract_section(texto, "6. Envios entre sesiones")
    assert seccion, "Control positivo: seccion 6 no encontrada."
    for encabezado in (
        "`check` exige `--a` y `--modo`",
        "`record` rehusa rc 1",
        "`rc 2` = error de entorno",
        "Ruta del ledger siempre por argumento",
    ):
        assert f"### {encabezado}" in seccion, f"falta el encabezado: {encabezado}."
    rehuso = _normalizar(_extract_section(seccion, "`record` rehusa rc 1"))
    assert "falta `by` o `mensaje_id`" in rehuso
    entorno = _normalizar(_extract_section(seccion, "`rc 2` = error de entorno"))
    assert "`thread_id.py` no cargable" in entorno
    assert "no se puede abrir para anexar" in entorno


def test_dod_136h_protocolo_codigos_del_helper_real(tmp_path):
    """DoD 136h: lo que el protocolo dice de los codigos de salida es lo que hace el helper.

    Before: un ledger temporal inexistente. During: ejecuta el helper real con
    argumentos que fallan por una causa cada vez (falta `--a`, falta `--modo`, destino
    sin prefijo, modo desconocido, `by` vacio) y con el camino autorizado.
    After: rc 2 sin `--a`/`--modo`/`--ledger`; rc 1 con la razon por stdout en cada
    rehuso; rc 0 autorizado/escrito; tras `parent_not_active` el mismo id se rehusa
    (rc 1) y otro id se autoriza; jamas rc 3.
    """
    ledger = tmp_path / "ledger.jsonl"
    base = ["--ledger", str(ledger), "--by", "t", "--mensaje-id", "m1"]
    destino = ["--a", "mcp:destino"]
    rcs: list[int] = []

    def correr(*args: str, esperado: int) -> subprocess.CompletedProcess[str]:
        res = _ejecutar_helper(*args)
        rcs.append(res.returncode)
        assert res.returncode == esperado, (
            args,
            res.returncode,
            res.stdout,
            res.stderr,
        )
        return res

    # `check` exige --a y --modo (y --ledger): su ausencia es rc 2.
    correr("check", *base, "--modo", "queue", esperado=2)
    correr("check", *base, *destino, esperado=2)
    correr(
        "check",
        "--by",
        "t",
        "--mensaje-id",
        "m1",
        *destino,
        "--modo",
        "queue",
        esperado=2,
    )
    # Control positivo: la misma llamada completa autoriza (ledger inexistente).
    autorizado = correr("check", *base, *destino, "--modo", "queue", esperado=0)
    assert autorizado.stdout.startswith("autorizado")
    assert not ledger.exists(), "check no debe crear el ledger"

    # Rehusos rc 1 con la razon por stdout.
    sin_prefijo = correr(
        "check", *base, "--a", "destino", "--modo", "queue", esperado=1
    )
    assert "prefijo" in sin_prefijo.stdout
    modo_raro = correr("check", *base, *destino, "--modo", "inexistente", esperado=1)
    assert "modo" in modo_raro.stdout
    registro = [
        "record",
        *destino,
        "--modo",
        "queue",
        "--resultado",
        "parent_not_active",
    ]
    by_vacio = correr(
        registro[0],
        "--ledger",
        str(ledger),
        "--by",
        "",
        "--mensaje-id",
        "m1",
        *registro[1:],
        esperado=1,
    )
    assert "--by" in by_vacio.stdout
    assert not ledger.exists(), "un rehuso no escribe nada"

    # record escribe UNA linea y la regla de un intento se verifica LEYENDOLA.
    correr(*registro[:1], *base, *registro[1:], esperado=0)
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1
    rehusado = correr("check", *base, *destino, "--modo", "queue", esperado=1)
    assert "cero reintentos" in rehusado.stdout
    correr(
        "check",
        "--ledger",
        str(ledger),
        "--by",
        "t",
        "--mensaje-id",
        "m2",
        *destino,
        "--modo",
        "queue",
        esperado=0,
    )

    assert 3 not in rcs and set(rcs) == {0, 1, 2}, rcs
