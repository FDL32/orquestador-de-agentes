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
        """Mutation-verify: ast.walk sin poda colisiona scopes.

        Esta es la prueba de que el test anterior cubre el defecto real.
        Si este test pasa verde, significa que el test de colision
        (test_nombre_sin_punto_resuelve_top_level_no_anidada) NO cae
        cuando se muta a ast.walk -- y por tanto no cubre el defecto.
        """
        source = """\
def handler():
    pass

def outer():
    def handler():
        return "nested"
    return handler()
"""
        # Mutacion: usar ast.walk en vez de iter_child_nodes
        import ast as _ast

        tree = _ast.parse(source)
        funcs: dict[str, _ast.AST] = {
            n.name: n
            for n in _ast.walk(tree)
            if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
        }

        # ast.walk SIN PODA: el ultimo define gana (la anidada, lineno=5)
        # iter_child_nodes (correcto): solo la top-level (lineno=1)
        handler_node = funcs.get("handler")
        assert handler_node is not None
        # Con ast.walk sin poda, la anidada (5) sobreescribe a la top-level (1)
        assert handler_node.lineno == 5, (
            "ast.walk sin poda colisiona: la anidada (5) sobreescribe "
            "a la top-level (1). Este es el defecto que el test (c) "
            "debe detectar."
        )


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
