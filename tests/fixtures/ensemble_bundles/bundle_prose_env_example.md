REVISION DE DOCUMENTACION DE SEGURIDAD -- politica de variables de entorno.

<!-- FIXTURE ANTI-FALSO-POSITIVO (WOT-2026-027n), DoD (c). Prosa didactica que
     ENSENA la politica del repo citando la FORMA de las claves. Es el patron de
     `agent_system/docs/reference/anti-patterns.md` y de `.env.example`.
     DEBE **PASAR** el gate: son nombres de variable y placeholders redactados,
     no asignaciones con valor de alta entropia. -->

POLITICA VIGENTE (AGENTS.md, seccion "Secretos y seguridad"):

- En `.env.example` (versionado, SIN valores reales) las claves van vacias o
  redactadas:

      API_KEY=***REDACTED***
      DB_PASSWORD=***REDACTED***
      GITHUB_TOKEN=***REDACTED***

- En `privada/.env` (NUNCA en el repo) viven los valores reales. El hook
  `guard_paths` bloquea lectura y escritura de esa ruta.

- El codigo jamas hardcodea el valor: se carga por nombre de variable de
  entorno (`api_key_env` en `agents.json`), y `agents_config` FALLA la
  validacion si aparece una clave literal en la config.

FORMAS QUE EL SCANNER DEBE RECONOCER como credencial real (y que esta prosa
menciona pero NO instancia): las de prefijo `sk-` de OpenAI, las de prefijo
`ghp_` de GitHub, y los bloques PEM de clave privada.

PREGUNTA AL REVISOR: falta alguna forma en esa enumeracion?
