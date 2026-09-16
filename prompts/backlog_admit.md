# Prompt de alta de backlog con recibo

contract_id: cid-backlog-admit-v1
Skill canonica: skills/backlog-admit/SKILL.md
source_of_truth: este prompt. La skill `skills/backlog-admit/SKILL.md` es wrapper
operativo; si divergen, prevalece este prompt.

Este prompt documenta el flujo de ALTA de un ticket nuevo al backlog del repo
del alta, incluyendo el recibo que satisface el guard `check_backlog_admission.py`.

**Alcance:** este prompt cubre UNICAMENTE el ALTA de backlog. Los otros dos
flujos del PASO 0 del `finding_triage_protocol.md` (promocion de memoria y
`preexisting_gate_unblock`) tienen sus propios caminos y NO estan aqui.

## Flujo

1. **Barrido previo** (PASO 0 del protocolo): barre memoria (`archive/observations.*.jsonl`
   de ambos repos), backlog vivo y `_archive/backlog_done.md` con
   `find_similar_signals.py`. Esta herramienta es **generador de senal, nunca
   veredicto**: su salida NO es el recibo de admision. Sirve para identificar
   vecinos potenciales antes de decidir.

2. **Decision de triaje:** clasifica el hallazgo segun la tabla del protocolo.

3. **Si el resultado es ALTA** (fila nueva en `backlog.md`):
   a. Genera el recibo con `backlog_db_compare.py --emit-recibo` (el recibo
      mecanico lo emite ESTE generador, no `find_similar_signals`).
   b. Incluye el recibo en el mensaje del commit del alta, como linea
      `BACKLOG-ADMISSION-RECIBO: <json>`.

4. **El guard contrasta** (fail-closed): si el recibo falta o es incoherente,
   `check_backlog_admission.py` rechaza con `SIN_RECIBO` o
   `RECIBO_INCOHERENTE`.

## Schema del recibo (v1)

Una linea JSON tras el marcador `BACKLOG-ADMISSION-RECIBO:`:

```json
{
  "recibo_version": 1,
  "candidato_id": "WOT-2026-XXXXx",
  "candidato_contenido_sha": "<sha256 de la fila anadida>",
  "corpus": [
    {"path": ".agent/collaboration/backlog.md", "tipo": "backlog", "repo": "alta", "entradas": N},
    {"path": ".agent/collaboration/_archive/backlog_done.md", "tipo": "archive", "repo": "alta", "entradas": M}
  ],
  "corpus_sha": "<sha256 canonico>",
  "entradas_censadas": N,
  "algoritmo": "backlog_db_compare",
  "umbral": 0.12,
  "veredicto_propuesta": {"tipo": "NUEVA", "ids": []},
  "vecinos": [{"id": "WOT-2026-YYYYy", "score": 0.14}],
  "vecinos_barrido": []
}
```

### Campos de vecinos (cambio semantico, WOT-2026-070b)

- **`vecinos`**: candidatos con score >= umbral (0.12). Son los "aceptados" por
  el filtro determinista. Si la lista esta vacia, el alta tiene 0 vecinos
  significativos.
- **`vecinos_barrido`**: top-N candidatos (N=3) cuando `vecinos` esta vacio y
  existen candidatos con score > 0. DISTINGUE "barrido sin coincidencias"
  (vecinos=[] + vecinos_barrido=[...]) de "vecinos aceptados"
  (vecinos=[...] + vecinos_barrido=[]). Si no hay ningun candidato con score > 0,
  ambos estan vacios.

El guard `check_backlog_admission.py` exige `vecinos` NO vacio si
`entradas_censadas >= 2`. El generador satisface esto automaticamente:
cuando el filtro por umbral deja la lista vacia pero existen candidatos con
score > 0, emite los top-N en `vecinos` (con `vecinos_barrido` marcando el
fallback). El guard acepta cualquier score numerico, sin minimo. Solo si NO
existe ningun candidato con score > 0 (corpus totalmente disjunto), ambas
listas quedan vacias y el guard rechaza -- ese es el unico caso residual
donde el autor debe decidir.

## Generacion del recibo

```bash
python scripts/backlog_db_compare.py --emit-recibo \
    --candidato-id WOT-2026-XXXXx \
    --veredicto NUEVA \
    --row-text "| Media | WOT-2026-XXXXx | titulo | ..." \
    --backlog .agent/collaboration/backlog.md \
    --archive .agent/collaboration/_archive/backlog_done.md \
    --git-root <repo_del_alta>
```

El generador importa `derive_corpus_sha` y las constantes del guard
(`DEFAULT_BACKLOG`, `DEFAULT_ARCHIVES`, `ALGORITMO_REQUERIDO`,
`UMBRAL_REQUERIDO`, `RECIBO_MARKER`, `RECIBO_VERSION`) directamente de
`scripts/check_backlog_admission.py`. **Nunca las copia.**

### Contrato de universo del generador

- Universo por defecto = `DEFAULT_BACKLOG` + `DEFAULT_ARCHIVES` (importados del guard).
- Superficies adicionales se anaden.
- Universo RECORTADO: el generador falla explicito y NO emite recibo.
- El recibo emitido declara el universo usado y de donde salio.

## Ejemplo completo

```bash
# 1. Barrido previo
python scripts/find_similar_signals.py --text-file candidato.txt \
    --archive archive/observations.2026-09.jsonl \
    --backlog .agent/collaboration/backlog.md \
    --backlog .agent/collaboration/_archive/backlog_done.md

# 2. Generar recibo
RECIBO=$(python scripts/backlog_db_compare.py --emit-recibo \
    --backlog .agent/collaboration/backlog.md \
    --git-root .)

# 3. Commit con recibo
git add .agent/collaboration/backlog.md
git commit -m "WOT-2026-XXXXx: alta de ficha

BACKLOG-ADMISSION-RECIBO: $RECIBO"
```

## Generador: como funciona

El flag `--emit-recibo` en `backlog_db_compare.py`:

1. Carga las universos declarados (backlog, archives).
2. Importa `derive_corpus_sha` del guard para calcular la huella canonica.
3. Valida que el universo declarado cubre al menos `DEFAULT_BACKLOG` +
   `DEFAULT_ARCHIVES`. Si falta alguna superficie obligatoria -> falla y NO
   emite recibo.
4. Emite el JSON del recibo a stdout.

El schema del recibo es EL MISMO que `check_backlog_admission.py` contrasta:
mismos campos, mismas constantes, misma version. El generador y el guard
comparten la fuente (import), no una copia.
