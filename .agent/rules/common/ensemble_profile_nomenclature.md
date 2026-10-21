# Nomenclatura de perfiles ensemble (regla completa -- capa 2 de la piramide)

> **Procedencia:** seccion origen `AGENTS.md:524-558` (HEAD `81f5ecf762bd5850b7db6c9a99d33ca5dbdb18c2`, previo
> al commit del Builder), protocolo `prompts/agents_md_optimization_4layer_loop.md`, pasada piramide 1,
> despacho `.agent/planning/agents_md_optimization/dispatch_manager_piramide_pasada1.md`, fecha 2026-10-18.

**Ownership:** Este modulo es el texto normativo completo. La cupide de `AGENTS.md` conserva la
directiva y el puntero; en caso de divergencia de CONTENIDO manda este modulo; la cupide sigue
siendo el disparador de lectura obligatorio. Toda modificacion de uno exige revisar el otro en el
mismo commit.

Norma establecida 2026-09-28 tras censar los 20 perfiles vivos de
`.agent/config/agents.json`: NO existia una norma escrita, solo un patron
implicito que 19/20 perfiles ya seguian. Se fija por escrito porque el
dashboard de ensembles necesita poder derivar backend+familia del NOMBRE del
perfil sin tener que resolver `agents.json` en cada lectura.

**Forma:** `<rol>_<backend>_<familia>[_<caracteristica>]`

- `rol`: `proposer` o `challenger`.
- `backend`: nombre corto SIN el sufijo `_api` (`nan`, `nvidia`, `groq`,
  `openrouter`, `aihubmix`, `tokenharbor` para `channel=api`; el nombre del
  agente para `channel=agent`: `claude`, `codex`, `opencode`).
- `familia`: UNA palabra que identifica el modelo, SIN version ni tamano
  (`qwen`, `mimo`, `glm`, `gemma`, `kimi`, `nemotron`, `deepseek`, `gptoss`,
  `northcode`, `codingglm`). El campo `model` del perfil ya lleva la version
  exacta -- el nombre del perfil no la duplica.
- `caracteristica` (opcional): SOLO cuando distingue dos variantes del MISMO
  backend+familia dentro del pool (ej. `challenger_nan_qwen` vs
  `challenger_nan_qwen_flash`, ambos en `nan_api`). No se anade si no hay
  ambiguedad que resolver.

**Ejemplos correctos:** `challenger_groq_qwen`, `challenger_groq_gptoss`,
`challenger_nvidia_glm_flash`, `challenger_tokenharbor_qwen_flash`.

**Ejemplos INCORRECTOS (version/tamano colados en el nombre):**
`challenger_groq_qwen38`, `challenger_groq_gptoss120b`,
`challenger_aihubmix_codingglm51`, `challenger_tokenharbor_qwen38flash` --
corregidos en la misma sesion que fijo esta norma.

**No renombrar `challenger_opencode_glm_5_2` sin revisar primero** `grep -rn
"challenger_opencode_glm_5_2" tests/`. Caso completo de esta excepcion
legacy (por que, estado exacto, consecuencia para rutas de seleccion
nuevas) en `docs/protocol/ensemble_profile_naming_legacy_case.md`.
