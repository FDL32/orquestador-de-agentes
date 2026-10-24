# WOT-2026-010e -- Evidencia forense (caso completo): line endings mixtos

> Modulo de referencia (`referencia-bajo-demanda`). Caso forense COMPLETO y VERBATIM de la
> regla de `AGENTS.md` seccion "No MEZCLES vias de escritura en el mismo fichero" que lo cita
> con `[E1]`. La cuspide en `AGENTS.md` retiene solo la regla operativa y la comprobacion
> correcta; este fichero conserva la narrativa completa del incidente (sintoma, causa medida,
> creencias falsas). Citado desde `docs/registry/reference_keys.md` (letra `E`). Validado por
> `scripts/check_reference_keys.py`.

<a id="e1"></a>
**E1.** **El sintoma:** `git commit` ABORTA con `mixed line ending ... Failed` y el hook deja el
fichero "arreglado" pero SIN commitear. El commit **no existe**; hay que re-`git add` y repetir.
Paso TRES veces en una sola sesion, y las tres por lo mismo.

**La causa, medida (no la que parece):** en Windows, las dos vias de escritura del agente dejan
finales de linea DISTINTOS en el mismo repo.

| Via | Deja |
|---|---|
| `Write`/`Edit` (y `Path.write_text()` en modo texto) | **CRLF** -- Windows traduce `\n` al escribir |
| `cat >> f <<'EOF'`, `printf`, `Path.write_bytes()`, `write_text(..., newline="")` | **LF** |

Escribir un fichero con una via y AMPLIARLO con la otra lo deja MIXTO, que es lo que el hook caza.
Reproducido: `write_text()` (CRLF) + `cat >>` heredoc -> `CRLF=2 LF_total=3 bare_LF=1` -> MIXTO.

**Dos creencias FALSAS que conviene no heredar** (ambas se sostuvieron una sesion entera antes de
medirse):
1. *"La mezcla la introduce `git add` al aplicar `.gitattributes`"*. **NO.** Probado: `git add` no
   toca el working tree (`CRLF=0 LF=2` antes y despues; la normalizacion ocurre solo en el INDICE).
2. *"Verificar los line endings antes de stagear no sirve"*. **SI sirve** -- y es la barrera. Lo que
   no servia era mi comprobacion, porque medi el fichero ENTERO (`crlf == lf` -> "homogeneo") en vez
   de buscar LF SOLITARIOS. Un fichero con 2248 CRLF y 1 bare LF pasa el primer test y falla el hook.
