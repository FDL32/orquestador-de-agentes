PROHIBIDO git commit --no-verify, --no-gpg-sign y cualquier forma de saltar hooks; si un hook falla, arreglas la causa y lo cuentas.

<!-- Marcadores declarados: {{TICKET_ID}} {{FICHA_REF}} {{RAMA}} {{FLT}} {{DOD_LITERAL}} {{MATRIZ_DOD}} -->

# Spec de Builder: {{TICKET_ID}}

Ficha: {{FICHA_REF}}
Rama: {{RAMA}}
FLT (Files Likely Touched, rutas desnudas, una por linea, SOLO las de esta caja):
{{FLT}}

## DoD LITERAL y Matriz DoD

Pega aqui el DoD LITERAL completo de la fila (sin resumir ni parafrasear):

{{DOD_LITERAL}}

Matriz DoD (clausula, test citado POR NOMBRE, conteo esperado, conteo medido, control positivo):

{{MATRIZ_DOD}}

## Reglas duras de esta spec

- pre-commit se verifica SIEMPRE sobre la lista EXACTA del diff real (`git diff --name-only`), nunca una lista mas amplia: una lista mas amplia puede mutar ficheros ajenos al ticket.
- Si el cambio toca AGENTS.md, el FLT de arriba incluye tambien sus derivados llms-full.txt y llms.txt (el hook check-llms-full-sync los regenera y los exige sincronizados).
- No pidas encoding-guard explicito (`scripts/check_encoding_guard.py` con ficheros como argumento) sobre ficheros .txt generados: GLOB_PATTERNS no los cubre y el modo explicito da una falsa alarma.
- No copies cifras de cupo ni otras cifras de estado de la fuente al entregable: remite siempre a la fuente unica, nunca las transcribas.
- Antes de invocar `scripts/tools/run_and_exit.py`, fija `PYTHONIOENCODING=utf-8` en la consola: sin eso falla con UnicodeEncodeError en consola cp1252 y el rc reportado deja de ser el real.
- Cada commit lleva el trailer EXACTO `Co-Authored-By: Claude <noreply@anthropic.com>`, SIN version de modelo (un trailer con version de modelo lo rechaza el hook).

## Informe UNICO por hito

Un solo informe por hito, con estos campos fijos, en este orden exacto:
1. Hash
2. Gates (comando exacto, rc literal, hora)
3. Mutantes (precheck de fragmento unico, matados/total, ejecutados DENTRO de la suite)
4. Conteos de grep (patron, universo barrido, conteo medido, control positivo)
5. Decisiones por confirmar
6. Autoria (por fichero: quien escribio que, IM o builder)
7. Matriz DoD (clausula, test citado por nombre, conteo esperado, conteo medido, control positivo)
