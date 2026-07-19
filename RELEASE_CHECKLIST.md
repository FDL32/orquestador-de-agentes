# Release Checklist — Publicación limpia de `orquestador_de_agentes`

Checklist manual para publicar el motor en un git nuevo y limpio. **No es flujo
operativo diario ni un WP** — se ejecuta una sola vez, cuando el motor esté
consolidado y listo para su repo definitivo.

## Contexto

El repo privado actual (`FDL32/orquestacion-agentes`) tiene el historial
contaminado: `.codex/auth.json` con tokens OAuth reales de OpenAI quedó en
commits antiguos (gitignorado después, pero presente en la historia, ~249
commits). Estrategia acordada: NO reescribir ese historial — empezar un git
nuevo desde cero. El árbol de trabajo en HEAD está limpio; solo el historial
está contaminado, y un git nuevo no lo arrastra.

## Checklist

### 0. Definir namespace del destino
- [ ] En el `PROJECT.md` del proyecto destino, declarar `Ticket prefix: XXX`.
- [ ] Opcional: usar el instalador con `--install --prefix XXX` para escribirlo automaticamente.
- [ ] Confirmar que el destino usara `XXX-YYYY-NNN` para sus tickets y no el namespace `WP-YYYY-NNN` del motor.

### 1. Git nuevo desde cero
- [ ] Crear el repo nuevo con `git init` sobre el árbol de trabajo limpio.
- [ ] **NUNCA** `git clone` del repo viejo ni copiar la carpeta `.git/` — eso
      arrastraría el historial con los tokens. Primer commit = historia nueva.

### 2. Verificar `.gitignore` antes del primer commit
- [ ] `.gitignore` excluye `.codex/`, `*.log`, `.venv/`, caches y runtime
      (`.agent/runtime/...`, `__pycache__/`, etc.).
- [ ] `git status` antes del primer commit no muestra ningún archivo sensible.

### 3. gitleaks sobre el árbol
- [ ] Ejecutar `gitleaks` sobre el árbol de trabajo. Confirmar 0 hallazgos
      antes de publicar.

### 4. Revocar sesiones OpenAI
- [ ] En `chatgpt.com` → ajustes → cerrar todas las sesiones. Invalida el
      `refresh_token` que quedó en el `auth.json` del repo viejo.
- [ ] Hacerlo cuanto antes, sin esperar al resto del checklist.

### 5. Archivar el repo viejo
- [ ] Cuando el git nuevo esté publicado y verificado, borrar o archivar
      `FDL32/orquestacion-agentes` — no dejar vivo un repo con los secretos.

### 6. Proteger `main` en origin (ruleset) — WOT-2026-024i

`main` es la fuente canónica de 12+ destinos. Sin protección, un `push --force` o
un `delete` de `main` desde cualquier sesión o agente reescribiría el producto sin
fricción. Propuesta mínima que NO rompe el flujo actual (push directo desde `_dev`
al cierre): un **ruleset de GitHub sobre `main` que bloquee force-push y deletion,
SIN requerir PRs**.

- [ ] **[ACCIÓN HUMANA]** Activar el ruleset en GitHub
      (`Settings → Rules → Rulesets → New branch ruleset`), target `main`, con
      `Block force pushes` + `Restrict deletions` activados. NO activar
      `Require a pull request` (mantener el push directo del cierre).
- [ ] **Verificación re-ejecutable (no destructiva)** — el endpoint debe dejar de
      estar vacío:

      ```sh
      gh api repos/FDL32/orquestador-de-agentes/rulesets \
        --jq '[.[] | select(.target=="branch")] | length'
      ```

      Antes de activar: `0` (sin protección). Después: `>= 1`. Alternativa por la
      API clásica de branch-protection (devuelve `404 Branch not protected` hasta
      que exista un ruleset/protección):

      ```sh
      gh api repos/FDL32/orquestador-de-agentes/branches/main/protection \
        >/dev/null 2>&1 && echo PROTECTED || echo "NOT PROTECTED (404)"
      ```

- [ ] **Prueba de rechazo (no destructiva, sobre rama ficticia):** crear una rama
      `test-protection-probe`, incluirla en el scope del ruleset, e intentar un
      `git push --force` de prueba: debe ser **RECHAZADO**. Borrar la rama y su
      regla al terminar. Nunca probar sobre `main`.

> Estado 2026-07-19 (WOT-2026-024i): probe en vivo = `NOT PROTECTED (404)` /
> `rulesets == []`. La parte AUTÓNOMA de 024i (esta verificación re-ejecutable +
> la nota de seguridad en AGENTS.md) está entregada; la ACTIVACIÓN del ruleset es
> una decisión humana pendiente (el DoD "el endpoint deja de dar 404" solo se
> cumple tras la acción humana). Ticket BLOCKED_ON_HUMAN, no cerrado.

## Orden

- Paso 4 (revocar sesiones OpenAI): hacer YA, no esperar.
- Pasos 1-3 y 5: cuando el motor esté consolidado y listo para su repo
  definitivo.
