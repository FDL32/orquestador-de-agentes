Prepara el arranque de una sesion nueva heredando el METODO de la anterior y
RE-MIDIENDO el estado.

El contrato completo vive en `prompts/session_hop.md` (skill: `skills/session-hop/`).
Leelo entero antes de producir el arranque; esta pagina solo enruta.

1. Recolecta el estado MEDIDO:

   ```
   python scripts/collect_session_state.py --project-root <repo_destino>
   ```

   El script recolecta hechos con su `command:` y su `exit_code:`. **No emite
   veredictos**: el juicio lo pones tu leyendo la evidencia.

2. Sigue los Pasos 2-7 de `prompts/session_hop.md`: topologia resuelta, contratos que
   gobiernan (ruta + lineas), slugs de memoria verificados, avisos medidos, lo que NO
   hacer, y el sello si la sesion siguiente es un vuelo.

3. Entrega un unico bloque pegable como primer mensaje de la sesion nueva.

Regla que gobierna todo lo demas: el METODO se hereda, el ESTADO se re-mide. Un dato de
estado copiado de una sesion anterior es una premisa falsa esperando a que alguien la
crea. Etiqueta cada cifra como `[snapshot <fecha>]` y acompanala del comando que la
re-mide.

No cierra la sesion (`session-close-full-audit`), no resume el estado de un ticket
(`/pause-work`, `/resume-work`, `/session-report`) y no define el rol de la sesion nueva
(`orchestrator_session_bootstrap.md`).
