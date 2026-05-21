"""
Tests unitarios de ejemplo.

Este archivo demuestra cÃ³mo usar la infraestructura de tests:
- fixtures de conftest.py (tmp_path, restore_cwd)
- helpers de _temp_runtime.py
"""



def test_ejemplo_basico(tmp_path):
    """
    Ejemplo de test que usa tmp_path controlado.

    El fixture tmp_path viene de conftest.py y usa
    .runtime/test_runtime/ en lugar del temp del sistema.
    """
    archivo = tmp_path / "ejemplo.txt"
    archivo.write_text("contenido de prueba")

    assert archivo.exists()
    assert archivo.read_text() == "contenido de prueba"


def test_con_path_relativo(tmp_path):
    """Ejemplo que crea estructura de directorios."""
    base = tmp_path / "datos"
    base.mkdir()

    archivo = base / "archivo.txt"
    archivo.write_text("datos")

    assert archivo.exists()
    assert "datos" in archivo.read_text()
