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

## Orden

- Paso 4 (revocar sesiones OpenAI): hacer YA, no esperar.
- Pasos 1-3 y 5: cuando el motor esté consolidado y listo para su repo
  definitivo.
