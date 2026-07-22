BUNDLE DE GOBERNANZA -- auditoria del contrato de un ticket.

<!-- FIXTURE ANTI-FALSO-POSITIVO (WOT-2026-027n), DoD (c). Fragmento de un
     bundle REAL de gobernanza de este mismo vuelo. Es el caso que mas importa:
     un gate por substring bloquearia el bundle que audita al PROPIO ticket
     027n, y el vuelo se auto-bloquearia en su MANAGER_REVIEW. Ese es el
     anti-patron "aplicate tu propia vara" de AGENTS.md.
     DEBE **PASAR** el gate. -->

FICHA A AUDITAR: WOT-2026-027n -- privacy_preflight filtra por RUTA, no por
CONTENIDO.

ROJO REPRODUCIDO (2026-07-22, dos ramas):
1. `privacy_preflight` bloquea INCONDICIONALMENTE si `sensitivity != public`,
   incluso con `ensemble_private_roots` VACIA. La lista solo se consulta en la
   rama `public`.
2. En esa rama el filtro es por RUTA NOMBRADA en el payload, NO por CONTENIDO:
   con la lista poblada `['privada/','.env']` y un payload que asigna un valor
   de api_key el preflight devuelve allowed=True.

Un valor sensible hardcodeado en un fichero PERMITIDO sale a la API externa
aunque la lista este completa. Hoy es inocuo porque el AGENTE elige que va en
el bundle; deja de serlo en cuanto una ruta lea ficheros por eleccion del
modelo (WOT-2026-027m) o por grep.

DECISION DE PRODUCTO CERRADA: `ensemble_private_roots` va VACIA. Poblarla
bloquea bundles reales por MENCION EN PROSA de la ruta (el matching es
substring sobre el payload) y NO cierra el vector: el filtro busca RUTAS, no
valores. Lo que SI protege hoy es la rama de `sensitivity`.

PREGUNTA AL AUDITOR: el DoD (b) esta acotado a asignacion con valor de alta
entropia. Es suficiente, o deja un vector que el ticket declara cerrado?
