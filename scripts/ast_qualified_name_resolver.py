"""Resolver de nombre calificado a span de linea via AST podado.

Este modulo proporciona una funcion que resuelve un nombre calificado
(ej. ``mi_modulo.Clase.metodo`` o ``mi_funcion``) a un par de lineas
(lineno, end_lineno) dentro de un modulo Python dado su fuente como string.

El recorrido usa ``ast.iter_child_nodes`` (poda de ambito por diseño)
en vez de ``ast.walk`` sin filtro, para distinguir funciones top-level
de funciones anidadas dentro de otra funcion.
"""

import ast
from pathlib import Path


def resolve_qualified_span(source: str, qualified_name: str) -> tuple[int, int] | None:
    """Resolver ``nombre_calificado`` a (lineno, end_lineno) en ``source``.

    Args:
        source: Texto fuente de un modulo Python.
        qualified_name: Nombre calificado en forma
            ``ClaseOpcional.funcion`` (sin prefijo de fichero).
            Un nombre sin punto solo matchea funciones DIRECTAS del modulo.

    Returns:
        Par ``(lineno, end_lineno)`` de la funcion/metodo exacto,
        o ``None`` si no existe.
    """
    tree = ast.parse(source)

    # Si hay punto, desciende un nivel: Clase.metodo
    if "." in qualified_name:
        class_name, _, method_name = qualified_name.partition(".")
        # Buscar la clase top-level
        class_node = _find_top_level_class(tree, class_name)
        if class_node is None:
            return None
        # Buscar el metodo dentro de la clase
        method_node = _find_top_level_method(class_node, method_name)
        if method_node is None:
            return None
        return (method_node.lineno, method_node.end_lineno)  # type: ignore[no-any-return]

    # Sin punto: solo matchea funciones DIRECTAS del modulo (no anidadas)
    func_node = _find_top_level_function(tree, qualified_name)
    if func_node is None:
        return None
    return (func_node.lineno, func_node.end_lineno)  # type: ignore[no-any-return]


def resolve_qualified_span_from_file(
    path: Path, qualified_name: str
) -> tuple[int, int] | None:
    """Wrapper de conveniencia sobre ``resolve_qualified_span`` para un fichero.

    Args:
        path: Ruta al fichero Python.
        qualified_name: Nombre calificado a resolver.

    Returns:
        Par ``(lineno, end_lineno)`` o ``None``.
    """
    source = path.read_text(encoding="utf-8")
    return resolve_qualified_span(source, qualified_name)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _find_top_level_function(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Buscar una funcion top-level por nombre.

    Usa ``ast.iter_child_nodes`` sobre el modulo: solo los hijos
    directos (no descendentes anidados).
    """
    for child in ast.iter_child_nodes(tree):
        if (
            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child.name == name
        ):
            return child
    return None


def _find_top_level_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    """Buscar una clase top-level por nombre."""
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, ast.ClassDef) and child.name == name:
            return child
    return None


def _find_top_level_method(
    class_node: ast.ClassDef, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Buscar un metodo top-level dentro de una clase.

    Solo los hijos directos de la clase (no metodos anidados dentro de
    otro metodo).
    """
    for child in ast.iter_child_nodes(class_node):
        if (
            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and child.name == name
        ):
            return child
    return None
