"""Tests para los campos nuevos de handoff de relevo de sesion-rol (WOT-2026-136a).

Cada test lee su fuente por pathlib y verifica la presencia/ausencia de
cadenas literales requeridas por el work_plan WOT-2026-136a.
Los tests estan disenados para pasar en ROJO (10 fallan) y tras el VERDE
todos deben pasar (11 passed).

Test 2 es un INVARIANTE (ya pasa HOY, debe seguir pasando tras el VERDE).
Tests 1, 3, 4, 5, 6, 7, 8, 9, 10, 11 son discriminadores ROJO (fallan hoy).
"""

from __future__ import annotations

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
# Test 7: excepcion relevo planificado declara estados y SUPERVISOR-2
# ---------------------------------------------------------------------------


def test_relief_excepcion_relevo_planificado_declara_estados():
    """Test 7: Seccion de excepcion declara campos y transiciones."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    # Verificar cadenas requeridas (pueden estar en la seccion 6 o subseccion nueva)
    assert "active_roles.<rol>.estado" in text, (
        "No se encontro 'active_roles.<rol>.estado'."
    )
    assert "PENDIENTE_ACK" in text, "No se encontro 'PENDIENTE_ACK'."
    assert "SALIENTE_MUERTO" in text, "No se encontro 'SALIENTE_MUERTO'."
    assert "SUPERVISOR-2" in text, "No se encontro 'SUPERVISOR-2'."
    assert "15 minutos" in text, "No se encontro '15 minutos'."


# ---------------------------------------------------------------------------
# Test 8: decision SUPERVISOR-2 exige 2 senales de progreso
# ---------------------------------------------------------------------------


def test_relief_decision_supervisor2_exige_dos_senales():
    """Test 8: La decision de completar desde SALIENTE_MUERTO exige 2 senales."""
    text = T3_RELIEF.read_text(encoding="utf-8")
    assert "exigiendo al menos 2 senales de progreso" in text, (
        "No se encontro la cadena literal: 'exigiendo al menos 2 senales de progreso'"
    )
    # La frase debe acompanar a la decision de SUPERVISOR-2, no aparecer suelta
    # en cualquier otra parte del fichero (O5 de BA07, ronda 1 de revision).
    lines_with_frase = [
        ln
        for ln in text.splitlines()
        if "exigiendo al menos 2 senales de progreso" in ln
    ]
    assert any("SUPERVISOR-2" in ln for ln in lines_with_frase), (
        "La frase 'exigiendo al menos 2 senales de progreso' no coocurre, en la "
        "misma linea, con 'SUPERVISOR-2'."
    )


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
# Ronda extra (simulacro de sucesor frio de OR-8): item 10 de Salida,
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
