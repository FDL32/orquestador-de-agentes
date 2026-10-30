"""Tests para los campos nuevos de handoff de relevo de sesion-rol (WOT-2026-136a).

Cada test lee su fuente por pathlib y verifica la presencia/ausencia de
cadenas literales requeridas por el work_plan WOT-2026-136a.
Los tests estan disenados para pasar en ROJO (10 fallan) y tras el VERDE
todos deben pasar (11 passed).

Test 2 es un INVARIANTE (ya pasa HOY, debe seguir pasando tras el VERDE).
Tests 1, 3, 4, 5, 6, 7, 8, 9, 10, 11 son discriminadores ROJO (fallan hoy).
"""

from __future__ import annotations

import re
from pathlib import Path


# Rutas absolutas del motor (se resuelven al importar el modulo, no al correr tests).
MOTOR_ROOT = Path(__file__).resolve().parents[2]
SESSION_HOP = MOTOR_ROOT / "prompts" / "session_hop.md"
T3_RELIEF = MOTOR_ROOT / "prompts" / "t3_role_session_relief.md"


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
    regex = r"\b(SUPERVISOR|OR|CO|IM|TR)-[0-9]+(\.[0-9]+)?\b"
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
    tokens = [
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
    for token in tokens:
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
    """
    skill_path = MOTOR_ROOT / "skills" / "session-hop" / "SKILL.md"
    if skill_path.exists():
        text_skill = skill_path.read_text(encoding="utf-8")
        tokens = [
            "OPERACION_EN_CURSO",
            "mensaje_id",
            "SHA pedido",
            "siguiente accion segura",
            "autoritativo",
            "350k",
            "390-400k",
        ]
        for token in tokens:
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
