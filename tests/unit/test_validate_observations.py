#!/usr/bin/env python3
"""
Tests unitarios para scripts/validate_observations.py

Verifica que el validador rechace entradas invalidas y acepte entradas validas
segun el contrato en skills/_shared/ap-schema.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


# Importar el modulo bajo test
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from validate_observations import (
    validate_applies_to,
    validate_confidence,
    validate_domain,
    validate_observation,
    validate_signal,
    validate_source,
    validate_surface,
    validate_timestamp,
    validate_topic,
)


class TestValidateTimestamp:
    """Tests para validacion de timestamp ISO-8601."""

    def test_valid_iso8601_with_z(self):
        """Timestamp valido con Z (UTC)."""
        assert validate_timestamp("2026-05-27T12:00:00Z") is None

    def test_valid_iso8601_with_offset(self):
        """Timestamp valido con offset de zona horaria."""
        assert validate_timestamp("2026-05-27T12:00:00+00:00") is None
        assert validate_timestamp("2026-05-27T07:00:00-05:00") is None

    def test_valid_iso8601_with_millis(self):
        """Timestamp valido con milisegundos."""
        assert validate_timestamp("2026-05-27T12:00:00.123Z") is None

    def test_invalid_not_string(self):
        """Timestamp no es string."""
        assert validate_timestamp(12345) is not None
        assert validate_timestamp(None) is not None

    def test_invalid_format(self):
        """Formato no ISO-8601."""
        assert validate_timestamp("2026-05-27 12:00:00") is not None
        assert validate_timestamp("05/27/2026") is not None

    def test_invalid_date(self):
        """Fecha invalida (no existe)."""
        assert validate_timestamp("2026-13-45T12:00:00Z") is not None


class TestValidateTopic:
    """Tests para validacion de topic (kebab-case)."""

    def test_valid_kebab_case(self):
        """Topic valido en kebab-case."""
        assert validate_topic("mi-patron") is None
        assert validate_topic("protocol-key-assumption") is None
        assert validate_topic("test123") is None

    def test_valid_single_word(self):
        """Topic valido de una palabra."""
        assert validate_topic("testing") is None
        assert validate_topic("a") is None

    def test_invalid_not_string(self):
        """Topic no es string."""
        assert validate_topic(123) is not None
        assert validate_topic(None) is not None

    def test_invalid_empty(self):
        """Topic vacio."""
        assert validate_topic("") is not None
        assert validate_topic("   ") is not None

    def test_invalid_uppercase(self):
        """Topic con mayusculas."""
        assert validate_topic("Mi-Patron") is not None
        assert validate_topic("TEST") is not None

    def test_invalid_underscore(self):
        """Topic con underscore (no kebab-case)."""
        assert validate_topic("mi_patron") is not None
        assert validate_topic("snake_case") is not None

    def test_invalid_starts_with_number(self):
        """Topic que empieza con numero."""
        assert validate_topic("123-test") is not None


class TestValidateSignal:
    """Tests para validacion de signal."""

    def test_valid_signal(self):
        """Signal valido."""
        assert validate_signal("Descripcion clara del problema") is None
        assert validate_signal("Que fallo exactamente y que regla se deriva") is None

    def test_invalid_not_string(self):
        """Signal no es string."""
        assert validate_signal(123) is not None
        assert validate_signal(None) is not None

    def test_invalid_empty(self):
        """Signal vacio."""
        assert validate_signal("") is not None
        assert validate_signal("   ") is not None


class TestValidateSource:
    """Tests para validacion de source."""

    def test_valid_source(self):
        """Source valido."""
        assert validate_source("human_audit_WP-2026-154") is None
        assert validate_source("session-2026-05-27") is None

    def test_invalid_not_string(self):
        """Source no es string."""
        assert validate_source(123) is not None
        assert validate_source(None) is not None

    def test_invalid_empty(self):
        """Source vacio."""
        assert validate_source("") is not None


class TestValidateAppliesTo:
    """Tests para validacion de applies_to (enum)."""

    def test_valid_values(self):
        """Valores validos de applies_to."""
        for value in ["code", "mixed", "docs", "all"]:
            assert validate_applies_to(value) is None, f"{value} deberia ser valido"

    def test_invalid_not_string(self):
        """applies_to no es string."""
        assert validate_applies_to(123) is not None
        assert validate_applies_to(None) is not None

    def test_invalid_value(self):
        """Valor no permitido."""
        assert validate_applies_to("python") is not None
        assert validate_applies_to("documentation") is not None  # debe ser "docs"


class TestValidateConfidence:
    """Tests para validacion de confidence (float 0.0-1.0)."""

    def test_valid_values(self):
        """Valores validos de confidence."""
        assert validate_confidence(0.0) is None
        assert validate_confidence(0.5) is None
        assert validate_confidence(0.95) is None
        assert validate_confidence(1.0) is None

    def test_valid_int(self):
        """Confidence como entero (0 o 1)."""
        assert validate_confidence(0) is None
        assert validate_confidence(1) is None

    def test_invalid_not_number(self):
        """Confidence no es numero."""
        assert validate_confidence("0.5") is not None
        assert validate_confidence(None) is not None

    def test_invalid_range(self):
        """Fuera de rango [0.0, 1.0]."""
        assert validate_confidence(-0.1) is not None
        assert validate_confidence(1.1) is not None
        assert validate_confidence(2.0) is not None


class TestValidateDomain:
    """Tests para validacion de domain (enum)."""

    def test_valid_values(self):
        """Valores validos de domain."""
        valid_domains = {
            "security-gates",
            "integration-tests",
            "protocol-handlers",
            "bus-architecture",
            "review-quality",
            "config-schema",
            "testing",
        }
        for value in valid_domains:
            assert validate_domain(value) is None, f"{value} deberia ser valido"

    def test_invalid_not_string(self):
        """domain no es string."""
        assert validate_domain(123) is not None
        assert validate_domain(None) is not None

    def test_invalid_value(self):
        """Valor no permitido."""
        assert validate_domain("security") is not None  # debe ser "security-gates"
        assert validate_domain("unknown") is not None


class TestValidateSurface:
    """Tests para validacion de surface (opcional, array de strings)."""

    def test_valid_array(self):
        """Surface valido como array de strings."""
        assert validate_surface(["file.py", "test_file.py"]) is None
        assert validate_surface([]) is None  # array vacio es valido

    def test_valid_none(self):
        """Surface None es valido (campo opcional)."""
        assert validate_surface(None) is None

    def test_invalid_not_array(self):
        """Surface no es array."""
        assert validate_surface("file.py") is not None
        assert validate_surface(123) is not None

    def test_invalid_element(self):
        """Elemento no es string."""
        assert validate_surface(["file.py", 123]) is not None


class TestValidateObservation:
    """Tests para validacion de una observacion completa."""

    def create_valid_record(self, **overrides: Any) -> dict[str, Any]:
        """Crear un record valido con overrides opcionales."""
        record = {
            "timestamp": "2026-05-27T12:00:00Z",
            "topic": "mi-patron",
            "signal": "Descripcion del problema",
            "source": "human_audit_WP-2026-154",
            "applies_to": "code",
            "confidence": 0.95,
            "domain": "testing",
        }
        record.update(overrides)
        return record

    def test_valid_minimal_record(self):
        """Record valido con campos minimos requeridos."""
        record = self.create_valid_record()
        errors = validate_observation(record, line_num=1)
        assert len(errors) == 0

    def test_valid_with_optional_fields(self):
        """Record valido con campos opcionales."""
        record = self.create_valid_record(surface=["file.py"], anti_pattern_id="AP-09")
        errors = validate_observation(record, line_num=1)
        assert len(errors) == 0

    def test_ap_style_record_requires_anti_pattern_id(self):
        """Un hallazgo ya marcado como AP debe llevar anti_pattern_id."""
        record = self.create_valid_record(signal="AP-09: fallo de contrato")
        record.pop("anti_pattern_id", None)
        errors = validate_observation(record, line_num=1)
        assert len(errors) == 1
        assert "anti_pattern_id" in errors[0]

    def test_unknown_anti_pattern_id_is_rejected(self):
        """anti_pattern_id debe existir en anti-patterns.md."""
        record = self.create_valid_record(
            signal="AP-09: fallo de contrato",
            anti_pattern_id="AP-99",
        )
        errors = validate_observation(record, line_num=1)
        assert len(errors) == 1
        assert "no existe en skills/_shared/anti-patterns.md" in errors[0]

    def test_missing_required_field(self):
        """Falta un campo obligatorio."""
        for field in [
            "timestamp",
            "topic",
            "signal",
            "source",
            "applies_to",
            "confidence",
            "domain",
        ]:
            record = self.create_valid_record()
            del record[field]
            errors = validate_observation(record, line_num=1)
            assert len(errors) == 1
            assert f"falta campo obligatorio '{field}'" in errors[0]

    def test_invalid_field_value(self):
        """Valor invalido en campo valido."""
        record = self.create_valid_record(confidence=1.5)
        errors = validate_observation(record, line_num=1)
        assert len(errors) == 1
        assert "confidence" in errors[0]

    def test_multiple_errors(self):
        """Multiples errores en un record."""
        record = {
            "timestamp": "invalido",
            "topic": "INVALIDO",
            "signal": "",
            "source": "test",
            "applies_to": "wrong",
            "confidence": 2.0,
            "domain": "unknown",
        }
        errors = validate_observation(record, line_num=5)
        assert len(errors) >= 5  # Al menos 5 campos invalidos


class TestIntegration:
    """Tests de integracion con archivo temporal."""

    def test_validate_valid_jsonl(self, tmp_path: Path):
        """Validar archivo JSONL con entradas validas."""
        observations_path = tmp_path / "observations.jsonl"

        valid_entries = [
            {
                "timestamp": "2026-05-27T12:00:00Z",
                "topic": "test-valid",
                "signal": "Test signal",
                "source": "test",
                "applies_to": "code",
                "confidence": 0.95,
                "domain": "testing",
            },
            {
                "timestamp": "2026-05-27T13:00:00Z",
                "topic": "another-test",
                "signal": "Another signal",
                "source": "test",
                "applies_to": "all",
                "confidence": 1.0,
                "domain": "security-gates",
                "surface": ["file.py"],
                "anti_pattern_id": "AP-01",
            },
        ]

        content = "\n".join(json.dumps(entry) for entry in valid_entries)
        observations_path.write_text(content, encoding="utf-8")

        from validate_observations import validate_file

        success, errors = validate_file(observations_path)

        assert success is True
        assert len(errors) == 0

    def test_validate_invalid_jsonl(self, tmp_path: Path):
        """Validar archivo JSONL con entradas invalidas."""
        observations_path = tmp_path / "observations.jsonl"

        invalid_entries = [
            {"timestamp": "invalido", "topic": "test"},  # Campos faltantes
            "no es un objeto",  # No es dict
        ]

        content = "\n".join(
            entry if isinstance(entry, str) else json.dumps(entry)
            for entry in invalid_entries
        )
        observations_path.write_text(content, encoding="utf-8")

        from validate_observations import validate_file

        success, errors = validate_file(observations_path)

        assert success is False
        assert len(errors) > 0

    def test_validate_empty_file(self, tmp_path: Path):
        """Validar archivo vacio."""
        observations_path = tmp_path / "observations.jsonl"
        observations_path.write_text("", encoding="utf-8")

        from validate_observations import validate_file

        success, errors = validate_file(observations_path)

        assert success is True
        assert len(errors) == 0

    def test_validate_nonexistent_file(self, tmp_path: Path):
        """Validar archivo que no existe."""
        observations_path = tmp_path / "does_not_exist.jsonl"

        from validate_observations import validate_file

        success, errors = validate_file(observations_path)

        assert success is True
        assert len(errors) == 1
        assert "no existe" in errors[0].lower()
