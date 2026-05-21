---
name: graphify
version: 1.0.0
description: Construir grafo de conocimiento persistente del codebase para exploraciÃ³n eficiente con mÃ­nimo consumo de tokens
triggers: [/graphify, graph, map]
author: agent
tags: [core, system]
---

# graphify

Transforma un codebase en un grafo de conocimiento persistente. Permite explorar arquitectura y relaciones entre mÃ³dulos sin leer archivos crudos en cada sesiÃ³n. ReducciÃ³n tÃ­pica: **70x menos tokens** por consulta en corpus > 30 archivos.

## CuÃ¡ndo activar

El Builder DEBE activar esta skill antes de explorar el codebase cuando:
- El proyecto tiene **> 30 archivos** fuente, o
- El corpus total supera **5.000 palabras**, o
- Es la **segunda sesiÃ³n** sobre el mismo proyecto

Si el grafo ya existe (`graphify-out/graph.json`), usar `--update` en vez de reconstruirlo.

## Workflow

### Paso 1: Comprobar si existe grafo previo

```bash
ls graphify-out/graph.json 2>/dev/null && echo "EXISTE" || echo "NUEVO"
```

- Si **EXISTE** â†’ ir a Paso 3 (update)
- Si **NUEVO** â†’ continuar con Paso 2

### Paso 2: Construir grafo inicial

Escanear el directorio objetivo y estimar el corpus:

```bash
find src/ -type f \( -name "*.py" -o -name "*.md" \) | wc -l
find src/ -type f -name "*.py" -exec wc -w {} + | tail -1
```

Luego lanzar extracciÃ³n en paralelo. Dividir los archivos en lotes de 20-25 y despachar todos los subagentes en **un solo mensaje** (mÃ¡xima paralelizaciÃ³n):

**InstrucciÃ³n para cada subagente:**
```
Extrae entidades y relaciones del siguiente lote de archivos.
Para cada archivo:
1. Identifica: clases, funciones, mÃ³dulos, conceptos clave
2. Identifica relaciones: imports, llamadas, herencias, dependencias
3. Marca cada relaciÃ³n con confianza:
   - EXTRACTED (1.0): explÃ­cita en cÃ³digo (import, class X(Y))
   - INFERRED (0.4-0.9): implÃ­cita pero probable (mismo mÃ³dulo, patrÃ³n similar)
   - AMBIGUOUS (0.1-0.3): posible pero incierta
4. Preserva: autor, source_url si hay YAML frontmatter

Formato de salida JSON:
{
  "nodes": [{"id": "nombre", "type": "class|function|module|concept", "file": "ruta"}],
  "edges": [{"from": "A", "to": "B", "type": "imports|calls|extends|uses", "confidence": 1.0, "tag": "EXTRACTED"}]
}
```

Para archivos de cÃ³digo (.py, .js, etc.) usar anÃ¡lisis AST determinÃ­stico:
```bash
python -c "
import ast, json, sys
tree = ast.parse(open(sys.argv[1]).read())
# Extraer imports, clases, funciones sin usar LLM
"
```

### Paso 3: Actualizar grafo existente

```bash
# Solo procesar archivos modificados desde Ãºltima actualizaciÃ³n
find src/ -newer graphify-out/graph.json -type f
```

Procesar Ãºnicamente los archivos nuevos/modificados y hacer merge con el grafo existente.

### Paso 4: Persistir resultado

Guardar en `graphify-out/graph.json`:
```json
{
  "generated": "ISO-8601 timestamp",
  "corpus": {"files": 0, "words": 0},
  "nodes": [],
  "edges": [],
  "communities": {}
}
```

Guardar tambiÃ©n `graphify-out/GRAPH_REPORT.md` con:
- Nodos de alto grado (god nodes / mÃ³dulos centrales)
- Conexiones sorprendentes entre mÃ³dulos
- Comunidades detectadas (clusters de funcionalidad)
- Coste de construcciÃ³n (tokens usados)

### Paso 5: Consultar el grafo

En vez de leer archivos, usar consultas sobre el grafo:

```
query "Â¿dÃ³nde se valida X?"        â†’ BFS desde nodo X, profundidad 2
path "A" â†’ "B"                     â†’ camino mÃ¡s corto entre dos mÃ³dulos
explain "NombreClase"              â†’ todos los nodos conectados a NombreClase
community "autenticaciÃ³n"          â†’ cluster completo de mÃ³dulos relacionados
```

TraducciÃ³n a operaciones sobre graph.json:
```python
import json, networkx as nx
G = nx.node_link_graph(json.load(open("graphify-out/graph.json")))

# BFS query
neighbors = list(nx.bfs_tree(G, "NodoObjetivo", depth_limit=2).nodes())

# Shortest path
path = nx.shortest_path(G, "ModuloA", "ModuloB")
```

## Output

```
graphify-out/
â”œâ”€â”€ graph.json          # Grafo persistente (fuente de verdad)
â”œâ”€â”€ GRAPH_REPORT.md     # Informe: god nodes, conexiones, comunidades
â””â”€â”€ cache/              # SHA256 por archivo (detecciÃ³n de cambios)
```

## IntegraciÃ³n con el flujo Manager â†’ Builder

El Builder ejecuta graphify al inicio de la fase IMPLEMENT cuando el corpus es grande:

```markdown
## Inicio de sesiÃ³n Builder (proyecto grande)

1. Leer PROJECT.md
2. Comprobar graphify-out/graph.json
   - Si existe y < 7 dÃ­as: usar directamente
   - Si no existe o > 7 dÃ­as: ejecutar `/graphify src/ --update`
3. Consultar grafo para entender arquitectura antes de tocar cÃ³digo
4. Implementar segÃºn work_plan.md
```

## Constraints

- **NUNCA** inventar edges â€” relaciones inciertas se marcan AMBIGUOUS, no se omiten ni inventan
- **SIEMPRE** reportar coste de tokens de construcciÃ³n en GRAPH_REPORT.md
- **NO** reconstruir si `graph.json` existe y el corpus no ha cambiado (usar `--update`)
- Para corpus > 200 archivos o > 2M palabras, advertir y sugerir limitar el scope (`src/` en vez de raÃ­z)
- **NO** activar en proyectos pequeÃ±os (< 30 archivos): el overhead de construcciÃ³n supera el beneficio

## References

- `references/graph-query-patterns.md` - Patrones de consulta sobre NetworkX
- `references/ast-extraction.md` - ExtracciÃ³n AST sin LLM para cÃ³digo Python
