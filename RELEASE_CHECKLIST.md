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

- [x] **[ACCIÓN HUMANA]** Activar el ruleset en GitHub  <!-- hecho entre 2026-07-19 y 2026-07-27 -->
      (`Settings → Rules → Rulesets → New branch ruleset`), target `main`, con
      `Block force pushes` + `Restrict deletions` activados. NO activar
      `Require a pull request` (mantener el push directo del cierre).
- [x] **Verificación re-ejecutable (no destructiva)** — el endpoint debe dejar de
      estar vacío:

      ```sh
      gh api repos/FDL32/orquestador-de-agentes/rulesets \
        --jq '[.[] | select(.target=="branch")] | length'
      ```

      Antes de activar: `0` (sin protección). Después: `>= 1`.

      Complemento recomendado -- **reglas EFECTIVAS sobre `main`** (no solo que
      exista un ruleset, sino cuáles se aplican a esta rama):

      ```sh
      gh api repos/FDL32/orquestador-de-agentes/rules/branches/main --jq '[.[].type] | sort'
      ```

      Debe incluir `deletion` y `non_fast_forward`.

      Y comprobar que **nadie puede saltárselo** (un ruleset con `bypass_actors`
      poblado protege menos de lo que aparenta):

      ```sh
      gh api repos/FDL32/orquestador-de-agentes/rulesets/<ID> --jq '{bypass: .bypass_actors, me: .current_user_can_bypass}'
      ```

> [!WARNING]
> **NO uses la API clásica de branch-protection para verificar esto**
> (`/branches/main/protection`). Es un almacén DISTINTO: solo ve la
> branch-protection clásica y **NUNCA ve un ruleset moderno**. Sobre este repo
> devuelve `404 Branch not protected` mientras `main` SÍ está protegido por
> ruleset -- o sea, da el veredicto CONTRARIO a la verdad. Figuró aquí como
> "alternativa equivalente" hasta 2026-07-27, y por eso la nota de estado de
> abajo estuvo caducada 8 días. Es el caso literal de CEM "dos mediciones del
> mismo hecho, y una de las dos no mide producción": el conflicto entre probes
> ES el hallazgo, no un empate a resolver por mayoría.

- [ ] **Prueba de rechazo (no destructiva, sobre rama ficticia):** crear una rama
      `test-protection-probe`, incluirla en el scope del ruleset, e intentar un
      `git push --force` de prueba: debe ser **RECHAZADO**. Borrar la rama y su
      regla al terminar. Nunca probar sobre `main`.

> **Estado 2026-07-27 (WOT-2026-024i): SATISFECHO.** La acción humana se hizo
> entre el 2026-07-19 y hoy; 024i ya NO es `BLOCKED_ON_HUMAN`.
>
> Evidencia FECHADA (snapshot, **no** criterio de aceptación -- re-ejecuta los
> probes de arriba en vez de confiar en estas cifras):
>
> ```text
> rulesets                  -> 1
>   name         : protect-main-motor
>   enforcement  : active          target: branch
>   include      : [refs/heads/main]        exclude: []
>   rules        : [deletion, non_fast_forward]
>   bypass_actors: []    current_user_can_bypass: never
> rules/branches/main       -> [deletion, non_fast_forward]  (ruleset 19547721)
> branches/main/protection  -> 404   (ESPERADO: otra API; ver aviso de arriba)
> ```
>
> `non_fast_forward` bloquea `push --force` (y `--force-with-lease`); `deletion`
> bloquea el borrado. NO hay `pull_request`, así que el push directo del cierre
> sigue funcionando: es exactamente lo que pedía este paso, ni más ni menos.
>
> Nota histórica (por qué esta nota estuvo caducada): decía
> `NOT PROTECTED (404) / rulesets == []` y marcaba el ticket bloqueado. Ese
> `404` venía del probe clásico, que nunca ve rulesets. La fuente durable no se
> enteró de la activación durante 8 días -- mismo patrón de puntero falso
> corregido en WOT-2026-027m y WOT-2026-027s.

## Orden

- Paso 4 (revocar sesiones OpenAI): hacer YA, no esperar.
- Pasos 1-3 y 5: cuando el motor esté consolidado y listo para su repo
  definitivo.
