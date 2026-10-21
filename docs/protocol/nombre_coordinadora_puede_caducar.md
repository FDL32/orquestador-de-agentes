### El nombre de la sesion coordinadora puede caducar tras dárselo a una hija

**Contexto:** `AGENTS.md` ya exige dar el nombre EXACTO de la sesion lanzadora a su hija
(2026-10-18, caso `autonomo-b-20261018`). Esa regla cubre que la hija RECIBA el nombre exacto; no
cubre que ese nombre siga resolviendo cuando la hija lo USA.

**Medido (bucle de gobierno UNI-7, 2026-10-21, sesion de auditoria `repo_audit_multiagent` v2.4):**
el nombre propio de la sesion coordinadora cambio 2 veces en la misma sesion
(`t3-1b767245-5c` -> `-c8`) tras una compactacion, y el de un par vivo cambio 2 veces mas
(`fdl32-...-c2` -> `-dc`; `suite-optimizacion-...-27` -> `-44`) tras sus propios reinicios/
compactaciones. Un `PROMPT_ARRANQUE_*.md` ya escrito con el nombre viejo de la coordinadora tuvo
que corregirse a mano antes de lanzar la sesion hija que lo iba a usar; si no se hubiera revisado,
el primer `SendMessage` de informe final de esa hija habria apuntado a un nombre que ya no
resuelve a nadie.

**Norma adoptada (documental, sin barrera cableada -- bucle UNI-7, 4 lentes independientes
`codex`/`opencode-glm`/`mistral`/`cohere`, refinamiento de `challenger_opencode_glm_flash`):** la
sesion hija verifica el nombre de su coordinadora con `ListAgents` ANTES de su primer `SendMessage`
de informe, en vez de asumir que el nombre del prompt sigue vivo; y su informe final declara el
RECIBO de esa verificacion (nombre resuelto + que el prompt se emitio en un momento anterior), no
solo el resultado. Si el nombre ya no resuelve, reporta por el canal que tenga disponible (otro par
vivo, o deja el informe en disco) en vez de asumir que silencio == entregado.

**Fuera de alcance declarado:** no se propone mecanismo automatico de deteccion de nombre-caducado
(seria diseno de sistema); la norma es solo documental mas el habito de verificar con `ListAgents`.

---

> Procedencia: bloque anadido a `AGENTS.md`, seccion "Nomenclatura obligatoria del PAR de
> worktrees" (WOT-2026-104f/g), tras el bucle de gobierno DESIGN_REVIEW `UNI-7` (2026-10-21).
> Movido aqui por el gate `check-cuspide-growth-gate` (la version inline crecia demasiado la
> cuspide siempre-cargada de AGENTS.md/CLAUDE.md).
