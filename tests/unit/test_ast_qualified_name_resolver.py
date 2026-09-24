"""Tests para scripts.ast_qualified_name_resolver."""

from scripts.ast_qualified_name_resolver import (
    resolve_qualified_span,
    resolve_qualified_span_from_file,
)


class TestResolveQualifiedSpan:
    """Caso (a): funcion top-level simple."""

    def test_funcion_top_level_simple(self):
        source = """\
def hello():
    pass

def world():
    pass
"""
        result = resolve_qualified_span(source, "hello")
        assert result == (1, 2)

        result = resolve_qualified_span(source, "world")
        assert result == (4, 5)

    def test_funcion_con_cuerpo_multilinea(self):
        source = """\
def compute(a, b):
    result = a + b
    return result
"""
        result = resolve_qualified_span(source, "compute")
        assert result == (1, 3)


class TestClassMethod:
    """Caso (b): metodo de clase distinto de funcion top-level homonima."""

    def test_metodo_de_clase(self):
        source = """\
def process():
    pass

class Processor:
    def process(self):
        return 42
"""
        # Nombre sin punto -> funcion top-level
        result = resolve_qualified_span(source, "process")
        assert result == (1, 2)

        # Nombre calificado -> metodo de clase
        result = resolve_qualified_span(source, "Processor.process")
        assert result is not None
        assert result[0] > 3  # dentro de la clase, no la funcion top-level

        # Deben ser distintos
        top_result = resolve_qualified_span(source, "process")
        method_result = resolve_qualified_span(source, "Processor.process")
        assert top_result != method_result


class TestNestedCollision:
    """Caso (c): colision de ambito top-level/anidado.

    La funcion anidada dentro de otra funcion CON EL MISMO NOMBRE que una
    funcion top-level: el nombre sin calificar por clase debe resolver la
    top-level, nunca la anidada.

    Mutation-verify: revertir el descenso a ast.walk sin poda debe hacer
    FALLAR este test (si sigue verde, el test no cubre el defecto real).
    """

    def test_nombre_sin_punto_resuelve_top_level_no_anidada(self):
        source = """\
def handler():
    pass

def outer():
    def handler():
        return "nested"
    return handler()
"""
        # Debe resolver la funcion top-level (lineno=1), NO la anidada
        result = resolve_qualified_span(source, "handler")
        assert result == (1, 2), (
            "handler sin calificar debe resolver la top-level, no la anidada"
        )

    def test_mutacion_ast_walk_sin_poda_falla(self):
        """Mutation-verify: reemplazar iter_child_nodes por ast.walk en la
        funcion REAL (_find_top_level_function) SI colisiona scopes cuando
        el nombre buscado solo existe ANIDADO (sin homonimo top-level).

        El source del test anterior (top-level Y anidada con el mismo
        nombre) no sirve para forzar la divergencia: ast.walk visita el
        modulo antes que el cuerpo de ``outer``, asi que el primer match
        de ambos iteradores es igual (la top-level). La divergencia real
        aparece cuando NO hay top-level homonima: iter_child_nodes (poda a
        hijos directos del modulo) debe devolver None, mientras que
        ast.walk (recorre TODO el arbol) encuentra la anidada igualmente.

        Evidencia de mutacion (comando + exit_code):
        - Produccion (iter_child_nodes): resolve_qualified_span("solo_anidada") -> None
        - Mutante (ast.walk, mismo cuerpo de busqueda): -> (2, 3) (la anidada)
        - Resultado: DISTINTO -> el mutante FALLA el assert de produccion.
        """
        import ast

        import scripts.ast_qualified_name_resolver as mod

        source = """\
def outer():
    def solo_anidada():
        return "nested"
    return solo_anidada()
"""
        # Produccion: sin homonimo top-level, debe devolver None.
        result = resolve_qualified_span(source, "solo_anidada")
        assert result is None, (
            "solo_anidada no tiene homonimo top-level: debe resolver None, "
            "nunca la anidada"
        )

        # Guardar la implementacion original
        original_find = mod._find_top_level_function

        def _mutated_find(tree, name):
            """ast.walk sin poda: visita TODO el arbol, no solo hijos directos."""
            for n in ast.walk(tree):
                if (
                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == name
                ):
                    return n
            return None

        # Aplicar mutacion: solo cambia el iterador de busqueda
        mod._find_top_level_function = _mutated_find

        try:
            mutated_result = resolve_qualified_span(source, "solo_anidada")
            # Con ast.walk, la anidada SI se encuentra: colisiona con el
            # contrato de "solo hijos directos del modulo".
            assert mutated_result != result, (
                f"Mutante (ast.walk) devolvio {mutated_result}, igual que "
                f"produccion ({result}). El mutation-verify NO detecto la "
                "diferencia: el test no cubre el defecto real."
            )
            assert mutated_result == (2, 3), (
                f"Mutante debia resolver la anidada (2, 3), obtuvo {mutated_result}"
            )
        finally:
            # Restaurar implementacion original
            mod._find_top_level_function = original_find


class TestNonExistent:
    """Caso (d): nombre inexistente devuelve None, no lanza excepcion."""

    def test_nombre_no_existe(self):
        source = """\
def real():
    pass
"""
        result = resolve_qualified_span(source, "fake")
        assert result is None

    def test_metodo_no_existe_en_clase(self):
        source = """\
class Foo:
    def bar(self):
        pass
"""
        result = resolve_qualified_span(source, "Foo.nonexistent")
        assert result is None

    def test_clase_no_existe(self):
        source = """\
def foo():
    pass
"""
        result = resolve_qualified_span(source, "MissingClass.foo")
        assert result is None


class TestResolveQualifiedSpanFromFile:
    """Tests del wrapper de fichero."""

    def test_from_file(self, tmp_path):
        src = tmp_path / "mod.py"
        src.write_text("def target():\n    return 42\n", encoding="utf-8")
        result = resolve_qualified_span_from_file(src, "target")
        assert result == (1, 2)

    def test_from_file_no_existe(self, tmp_path):
        src = tmp_path / "mod.py"
        src.write_text("def existing():\n    pass\n", encoding="utf-8")
        result = resolve_qualified_span_from_file(src, "missing")
        assert result is None
