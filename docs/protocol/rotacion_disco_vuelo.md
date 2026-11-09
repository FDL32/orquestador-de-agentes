# Rotacion de disco del vuelo: contrato P7 y reglas de rotacion

## Proposito

Este documento fija un diseno comprobable para conservar, archivar y rotar superficies del vuelo.
No ejecuta operaciones ni autoriza borrados: describe contratos, candidatas, evidencias y limites.
La interface primaria es el bloque de 56 anclas que sigue; cada linea debe conservarse literalmente.

## ANCLAS (interface comprobable)

P7.lista_aprobada=hash_lista_y_hash_por_entrada
P7.hash_directorio=manifiesto_de_arbol
P7.recomprobacion=tamano_mtime_hash
P7.aborto_si_difiere=obligatorio
P7.guardas=proceso_cwd_lock
P7.registro=fuera_de_lo_retirado
P7.dry_run=por_defecto
P7.dueno=herramienta_p7
P7.reutiliza=archive_arranques_py
P7.ttl=genera_candidatas
P2.clon_ligero=worktree_o_shared
P2.archivo=obligatorio
P2.veredicto=fuera_del_clon
P2.manifiesto=rama_commit_push
P2.lock=obligatorio
P2.re_ejecucion=lentes_fallidas_antes_de_retirar
P2.ttl=solo_clones_futuros_tras_archivo
P2.clones_actuales=solo_adjudicados_y_archivados
P2.origen_clones=scripts/flight/start_ticket.py
ENTREGABLE.ruta=docs/protocol/rotacion_disco_vuelo.md
P3.compresion_ntfs=diferida_por_u_r2
P6.statev2=no_poda_manual
P6.t3_activo=fuera_de_alcance
P6.export_mensajes=local_no_versionado
P6.kilo_db=propuesta_pendiente_usuario
P4.worktrees=solo_al_cerrar_ticket
P5.excluidas=terna_vivas_coordinadora_go
P5.export_previo=obligatorio
P5.go_no_registrada=se_comprueba_contra_el_registro
P5.cleanupperioddays=no_tocar
P5.resume_prueba=hilo_desechable_una_vez
ARCHIVO.raiz=sin_valor_por_defecto
ARCHIVO.d_fallo_cerrado=nunca_caer_a_c
ARCHIVO.replica_nube=opcional_solo_zip_y_manifiesto
ARCHIVO.nube_jsonl=prohibido_sin_escaneo_y_autorizacion
ARCHIVO.subida_confirmada=no_verificable_por_script
ROTACION.sin_listas=no_lleva_listas_de_retirada
SUPERFICIES.solo_nombrar=como_evidencia_o_candidata
REGISTRO.espacio_libre=disk_free_log_csv
CICLO.tabla=ocho_familias_tres_fases
CICLO.familia_sin_sistema=no_se_archiva
CICLO.transiciones=dry_run_lista_hash_rc_indice
CICLO.reutilizacion=primero_lo_existente
L1.topes=propuesta_internxt_20gb_d_100gb_por_vuelo_5gb
L2.indice=index_md_y_json_con_caducidad
L2.huerfano=rojo
L3.caducado=propuesta_p7_con_hash
L4.solo_comprimido=con_manifiesto_y_hash
L5.categorias=autorizacion_expresa_con_escaneo
L6.comprobador=solo_lectura_con_rc
L6.cableado=flight_stall_check_o_latido
L7.fallo_cerrado=sin_caida_a_c
L8.subida=distinta_de_copia
DOC.ciclo=docs/protocol/ciclo_vida_artefactos_vuelo.md
DOC.pilar=fila_en_vuelo_pilares_md
DOC.index=index_md_en_cada_raiz

## Clausulas

### m-01 P7, contrato de aplicacion y dueno unico

P7 es el unico contrato de aplicacion. El diseno exige lista aprobada por el usuario, hash de
la lista, hash de cada entrada y manifiesto de arbol para directorios. Antes de aplicar se
recomprueba tamano, mtime y hash; cualquier diferencia aborta. Las guardas cubren proceso vivo,
cwd de sesion activa y lock; el registro queda fuera de la superficie considerada. El modo
normal es dry-run. P7 reutiliza el contrato comun de archive_arranques.py y el TTL solo genera
candidatas: no hay autorizacion implicita.

Frase literal de la clausula: El diseno declara el contrato P7 completo: (1) lista aprobada por el usuario con hash DE LA LISTA y hash DE CADA entrada; para un directorio, un manifiesto de arbol (ruta relativa, tamano, mtime, sha256 por fichero); (2) re-comprobacion por entrada (tamano, mtime, hash) en el momento de aplicar; (3) aborto obligatorio si algo difiere; (4) guardas de proceso vivo, cwd de sesion activa y lock; (5) registro de operaciones escrito FUERA de lo que se retira; (6) dry-run por defecto; (7) dueno unico del contrato: la herramienta P7 (hija H1), que REUTILIZA el contrato ya escrito de 158c/archive_arranques.py (re-stat, abort, lock, dry-run por defecto; N5/D6) extrayendo el codigo comun a un modulo compartido en vez de duplicarlo; archive_arranques.py deja de ser la referencia del contrato de retirada y queda como el archivador que ya existe. Justificacion del dueno: P7 cubre TODA retirada futura (zips, sesiones, bases, worktrees, clones) mientras archive_arranques.py solo archiva arranques; un solo dueno evita dos contratos que divergen (N5). (8) Toda retirada, incluida la del TTL de 7 dias, solo via P7; el TTL solo GENERA candidatas (N2): sin autorizacion implicita de borrado en el propio TTL.

- scripts/archive_arranques.py L16-17: SE MUEVE, JAMAS SE BORRA; L50 mueve solo ARCHIVABLE, salvo --dry-run.

### m-02 El diseno no lleva listas de retirada; solo nombra superficies

El texto nombra clones C:/Temp/kilo, co24_pna, statev2.sqlite, kilo.db y jsonl unicamente como
evidencia o candidatas. co24_pna queda como candidata sin calificar riesgo: antes de proponerla
se debe verificar si es el unico respaldo existente. El control reproducible se ejecuta sobre
el documento completo y debe devolver cero.

Frase literal de la clausula: El diseno no lleva listas de retirada; solo nombra superficies. Distincion reproducible: se PROHIBE toda linea del diseno que abra con un verbo de retirada seguido de una ruta concreta (borrar/retirar/comprimir/eliminar/mover + letra de unidad, con barra o contrabarra); se PERMITE nombrar la superficie en prosa como evidencia o candidata. Regex de la parte prohibida (PowerShell): `(?m)^\s*(?:[-*+]|\d+\.)?\s*(?:borrar|retirar|comprimir|eliminar|mover)\s+[A-Za-z]:[\\/]` -- el comando cuenta coincidencias y el conteo esperado es **0**. El control positivo es el MUTANTE m-02, EJECUTADO por TR-29 sobre una copia de prueba con la salida literal en LEEME_v3.md (regex v2 con solo contrabarra NO mataba el mutante de ruta con barra normal: defecto de la v2 corregido aqui). La copia co24_pna queda nombrada como candidata sin calificacion de riesgo y el diseno exige verificar si es respaldo unico antes de proponerla.

- scripts/archive_arranques.py L16-17: SE MUEVE, JAMAS SE BORRA.

### m-03 P2, clones de lente

Cada ronda usa clon ligero, archivo obligatorio fuera del clon y un marcador de actividad. El
veredicto conserva ficheros citados, rama, commit y push. Las lentes fallidas se reejecutan antes
de cualquier candidata; el TTL solo afecta a clones futuros despues de archivo verificado y
siempre entrega candidatas a P7. Los clones actuales requieren adjudicacion y archivo.

Frase literal de la clausula: El diseno especifica: clon ligero (git worktree o clone --shared, uv con enlaces); archivo OBLIGATORIO al cerrar la ronda (veredicto + ficheros citados + manifiesto con rama, commit y push) con el veredicto persistido FUERA del clon; marcador de actividad (lock); re-ejecucion de lentes fallidas antes de retirar; el TTL de 7 dias (U-R1) aplica SOLO a clones futuros y SOLO tras archivo verificado, y no retira nada por si mismo: genera candidatas para P7 (N2); los clones actuales solo se retiran si estan adjudicados y archivados, y SIEMPRE via P7. Cada frase tiene su ancla y su mutante (m-03a y m-03b).

- Mutantes: m-03a en copia borra la ancla P2.archivo=obligatorio, el conteo cae a 0 y la comprobacion FALLA; m-03b en copia cambia el valor de la ancla P2.ttl a aplica_a_todos_los_clones, el valor no coincide y FALLA.

- scripts/flight/start_ticket.py: `_clone_at_tip` L63-83; `git clone --no-hardlinks` L74.

### m-08 Superficie de origen y entregable

Los clones de lente nacen en el origen de arranque del ticket. run_ticket_lenses es un nombre
conceptual de dossiers, no un fichero. ensemble_dispatch.py solo resuelve el cwd del lens repo.
Este documento es el entregable fijo del motor.

Frase literal de la clausula: El diseno declara que los clones de lente nacen en scripts/flight/start_ticket.py (`_clone_at_tip`, lineas 63-83; `git clone --no-hardlinks` en la linea 74; el nombre run_ticket_lenses de los dossiers es conceptual y NO existe como fichero) y que ensemble_dispatch.py solo resuelve el cwd (resolve_lens_repo_root) (N4). El entregable es docs/protocol/rotacion_disco_vuelo.md (ruta fija de esta ficha).

- scripts/flight/start_ticket.py: `_clone_at_tip` L63-83; `git clone --no-hardlinks` L74.
- scripts/ensemble_dispatch.py: resolve_lens_repo_root L2211 (def), L2334 (uso).
- run_ticket_lenses: NO existe como fichero (nombre conceptual de los dossiers).

### m-04 P3, compresion NTFS: DIFERIDA

La compresion NTFS no es una clausula viva. Queda diferida por U-R2 y solo puede reabrirse si
el usuario reabre U-R2; no se infiere autorizacion de este documento.

Frase literal de la clausula: P3, compresion NTFS: DIFERIDA. No es clausula viva: el diseno la documenta como diferida por U-R2; se reabre SOLO si el usuario reabre U-R2 (D4/E5). Sin ancla de autorizacion, solo el ancla de diferimiento.

### m-05 P6, statev2 y kilo.db

statev2.sqlite no se poda a mano. El export de mensajes va a un registro local no versionado
con identificadores, marcas de tiempo, hilos, hashes y conteos validados; mientras T3 corra,
el WAL no vacio deja la superficie fuera de alcance. kilo.db es propuesta pendiente del usuario.
VACUUM INTO solo podria estudiarse sobre copia, con integrity_check antes y despues, medicion de
freelist_count por page_size y espacio reclamado, y con espacio libre minimo de 2x 14,66 GB =
>= 29,32 GB.

Frase literal de la clausula: P6, statev2 y kilo.db. El diseno especifica: statev2.sqlite NO se poda a mano; export de los mensajes del usuario a un registro LOCAL no versionado (el repo del motor es publico) con identificadores, marcas de tiempo, hilos, hashes y validacion de conteos; fuera de alcance mientras T3 corra (WAL no vacio); kilo.db queda como PROPUESTA pendiente de decision del usuario (D4): su experimento VACUUM INTO sobre copia (freelist_count por page_size, integrity_check antes y despues, espacio reclamado) tiene la PRECONDICION de espacio libre >= 2x el tamano de la base (14,66 GB x 2 = >= 29,32 GB) (N6).

### m-06 P4, worktrees

La candidata de worktree solo aparece al cerrar el ticket, despues de integracion ff-only,
fila cerrada, push cuando corresponda, comprobacion de git status --ignored y ausencia de gc o
prune pendiente. La operacion no es masiva y siempre queda bajo P7.

Frase literal de la clausula: P4, worktrees. El diseno especifica retirada SOLO al cerrar el ticket, con integracion verificada (ff-only), fila cerrada, push si hay clase B, git status --ignored sin ignorados notables (o archivados), sin gc/prune pendiente, nunca masivo, y SIEMPRE via P7.

### m-07 P5, sesiones (TEXTO LITERAL OBLIGATORIO, N3)

Se conserva literalmente el protocolo de cinco puntos:

(1) cleanupPeriodDays NO se toca, porque la junction .claude-alvarovans/projects hace que el ajuste afecte a las DOS cuentas (A1, verificado 4 de 4);
(2) excluidas SIEMPRE de toda retirada: la terna visible de 3 coordinadoras, las sesiones vivas, el jsonl de la coordinadora vigente (lo lee ctx_acumulado.py) y cualquier jsonl que respalde un GO u orden del usuario no registrada;
(3) EXPORT previo de los mensajes del usuario a un registro local OBLIGATORIO antes de tocar cualquier jsonl;
(4) como se detecta un GO u orden no registrada: comprobando cada jsonl candidata contra el registro local de mensajes del usuario (el export del punto 3); un jsonl cuyo contenido respalde un GO u orden que no este en el registro queda excluido;
(5) prueba de resume con un hilo desechable, UNA vez, antes de tocar cualquier jsonl.

cleanupPeriodDays no se toca. Antes de cualquier decision sobre jsonl se exige el export local,
la comprobacion contra ese registro y una prueba de resume desechable una sola vez.

Frase literal de la clausula: P5, sesiones (TEXTO LITERAL OBLIGATORIO, N3). El diseno declara: (1) cleanupPeriodDays NO se toca, porque la junction .claude-alvarovans/projects hace que el ajuste afecte a las DOS cuentas (A1, verificado 4 de 4); (2) excluidas SIEMPRE de toda retirada: la terna visible de 3 coordinadoras, las sesiones vivas, el jsonl de la coordinadora vigente (lo lee ctx_acumulado.py) y cualquier jsonl que respalde un GO u orden del usuario no registrada; (3) EXPORT previo de los mensajes del usuario a un registro local OBLIGATORIO antes de tocar cualquier jsonl; (4) como se detecta un GO u orden no registrada: comprobando cada jsonl candidata contra el registro local de mensajes del usuario (el export del punto 3); un jsonl cuyo contenido respalde un GO u orden que no este en el registro queda excluido; (5) prueba de resume con un hilo desechable, UNA vez, antes de tocar cualquier jsonl.

### m-09 Raiz del archivo

La raiz del archivo es un parametro obligatorio sin valor por defecto y permanece como decision
pendiente del usuario. El destino primario recomendado es D:/flight_archive, con fallo cerrado si
D: no esta montado y hash tras escribir. La replica Internxt es opcional y solo contiene zip y
manifiesto de documentacion; jsonl y mensajes requieren escaneo de secretos y autorizacion por
categoria. Una copia local verificada por hash no equivale a subida confirmada, que no es
verificable por script sin comprobacion reproducible del cliente.

Frase literal de la clausula: Raiz del archivo: parametro obligatorio sin valor por defecto (ADENDA 18:30 del usuario). El diseno declara la raiz donde se guardan los veredictos archivados de P2 (y, en la hija de 158c, el zip) como PARAMETRO OBLIGATORIO SIN VALOR POR DEFECTO, DECISION PENDIENTE DEL USUARIO, con: (1) destino primario recomendado D:/flight_archive (disco USB distinto de C:, con FALLO CERRADO si D: no esta montado -- nunca caer a C:-- y verificacion de hash tras escribir); (2) replica OPCIONAL en la carpeta sincronizada de Internxt (cliente 2.6.12 instalado y en marcha; carpeta sincronizada C:/Users/fdl/InternxtDrive, p. ej. C:/Users/fdl/InternxtDrive/vuelo_24h/<fecha>), SOLO para el zip y el manifiesto de la DOCUMENTACION del vuelo -- es el precedente existente C:/Users/fdl/InternxtDrive/vuelo_24h/20261106-1430 (verificado solo lectura por TR-29: directorio_vuelo.zip 3,1 MB, manifiesto_directorio_vuelo.json 110 KB y dos bundles git de 52,4 y 43,8 MB); (3) lo que contenga mensajes del usuario o transcripciones de sesiones (jsonl) NO sale a la nube sin escaneo previo de secretos Y autorizacion expresa del usuario POR CATEGORIA; (4) escribir en la carpeta sincronizada NO prueba que se haya subido: el diseno distingue COPIA LOCAL VERIFICADA POR HASH (comprobable) de SUBIDA CONFIRMADA, y la confirmacion de subida se declara NO VERIFICABLE por script mientras no exista una comprobacion reproducible del cliente (no se inventa ninguna).

- scripts/archive_arranques.py L16-17: SE MUEVE, JAMAS SE BORRA; L50 mueve solo ARCHIVABLE, salvo --dry-run.

### m-10 CICLO DE VIDA por familia

La tabla aplica USO -> ARCHIVADO -> ELIMINACION a ocho familias, con herramienta existente o
explicitamente por crear. Una familia sin las tres fases y herramienta no se archiva. Cada
transicion usa dry-run por defecto, lista con hash, rc por modo y fila de indice; nada sale del
archivo fuera de P7. La regla de reutilizacion se refleja en estas herramientas y limites:

| Familia | USO | ARCHIVADO | ELIMINACION | Herramienta |
|---|---|---|---|---|
| Documentacion del vuelo | local mientras es citada | zip + manifiesto a D:; replica Internxt solo si el usuario lo confirma | TTL 90 dias tras cierre sin re-cita | 158c fase 1 (pending) + hija 158c |
| Salidas raw y grep_hits | 14 dias | compresion a 14 dias inactivos | lista P7 tras copia verificada; archivo propuesto 90 dias | por crear o ampliar rotate_kilo_logs |
| Clones y sandboxes | ronda viva | veredicto, ficheros y manifiesto | TTL 7 dias via P7; SAFE via prune_git_recoverable | start_ticket.py + P7 + prune_git_recoverable |
| Sesiones de Claude | 14 dias; cleanupPeriodDays NO se toca | nube solo con escaneo de secretos y autorizacion por categoria | tras archivo y export, via P7 | por crear, hija P5 |
| Logs de Kilo | 7 dias | comprimido | 30 dias | rotate_kilo_logs.py |
| Reviews, packets, backups y notificaciones | ultimos 20, 20, 10 y 20 | n/a de conteo | resto | prune_runtime_retention.py |
| Scratch del harness | 14 dias | n/a | despues | prune_session_scratch.py |
| Bases vivas | siempre | n/a | no poda manual; VACUUM INTO pendiente | fuera de alcance |

Frase literal de la clausula: CICLO DE VIDA por familia (SEGUNDA ADENDA 18:42). El diseno declara la tabla de familias con las tres fases USO -> ARCHIVADO -> ELIMINACION y la herramienta de cada una (seccion 10 de esta ficha): una familia SIN las tres fases y SIN herramienta que las ejecute NO se archiva a ningun sitio; cada transicion la ejecuta un script con dry-run por defecto, lista con hash y rc por modo (patron de la casa) y deja fila de indice; nada sale del archivo sin pasar por el contrato P7; se REUTILIZA lo que existe (archive_arranques.py L16-17, purge_arranques_archive.py L62, rotate_kilo_logs.py L48-49, prune_runtime_retention.py L78-81, prune_git_recoverable.py L4-5, prune_session_scratch.py L44) y solo se escribe codigo nuevo para familias sin sistema.

- scripts/archive_arranques.py L16-17 (SE MUEVE, JAMAS SE BORRA), L50 (mueve solo ARCHIVABLE, salvo --dry-run).
- scripts/purge_arranques_archive.py L15 (PURGADO <fecha>), L62 (TTL_DAYS = 90).
- scripts/rotate_kilo_logs.py L48 (KILO_LOG_COMPRESS_DAYS=7), L49 (KILO_LOG_DELETE_DAYS=30).
- scripts/rotate_kilo_logs.py L10-11: locks y excepcion de vuelo activo.
- scripts/prune_runtime_retention.py L36-40 (exige --dry-run o --apply; nunca borra sin --apply), L78-81 (keep 20/20/10/20).
- scripts/prune_git_recoverable.py L4-5 (SAFE vs RISKY), L19-20 (sin --confirm-risky borra SOLO SAFE).
- scripts/prune_session_scratch.py L19 (--dry-run es el defecto), L44 (DEFAULT_DAYS=14).

### m-11 LIMITES del archivo (L-1 a L-8)

Los ocho limites son propuestas pendientes, no autorizaciones: L-1 presupuesto de 20 GB en
Internxt, 100 GB en D: y 5 GB por vuelo; L-2 INDEX.md e indice JSON obligatorios, huerfano en
rojo; L-3 caducidad mediante propuesta P7 con hash; L-4 solo comprimido con manifiesto y hash;
L-5 categorias con autorizacion expresa; L-6 comprobador solo lectura con rc cableado a
flight_stall_check o latido; L-7 fallo cerrado sin caida a C:; L-8 subida distinta de copia.

Frase literal de la clausula: LIMITES del archivo (L-1 a L-8). El diseno declara los ocho limites L-1 a L-8 de la seccion 10: presupuesto con topes (PROPUESTA: 20 GB Internxt, 100 GB en D:, 5 GB por vuelo), indice obligatorio con huerfano=rojo, caducidad con propuesta P7 con hash, solo comprimido con manifiesto y hash, categorias con autorizacion expresa, comprobador de solo lectura con rc cableado a flight_stall_check o latido, fallo cerrado sin caida a C:, y subida distinta de copia.

### m-12 Documentacion para un agente frio

La documentacion fria debe enlazar el ciclo de vida, una fila nueva del pilar y un INDEX.md en
cada raiz, explicando estructura, indice maquina, recuperacion y contacto.

Frase literal de la clausula: Documentacion para un agente frio. El diseno ordena escribir docs/protocol/ciclo_vida_artefactos_vuelo.md, una fila nueva en vuelo_pilares.md y un INDEX.md en la raiz de cada destino de archivo (Internxt y D:) con estructura, indice maquina, como recuperar una entrada y a quien preguntar.

- Docs existentes: docs/protocol/ciclo_vida_artefactos_vuelo.md, docs/protocol/sistema_agnostico_celdas_y_lentes.md.
- .agent/rules/common/vuelo_pilares.md filas P30..P37 en L34-41.

### d-01 REGISTRO diario de espacio libre

El registro vivo es C:/Users/fdl/flight_coordination/disk_free_log.csv con columnas ts_local,
free_gb, used_gb, total_gb y by. El dueno de la automatizacion queda pendiente del usuario;
la linea base de 14 registros solo informa tasas de crecimiento y nunca convierte una medicion
en una lista aprobada.

Frase literal de la clausula: REGISTRO diario de espacio libre (medicion viva). El diseno nombra el fichero C:/Users/fdl/flight_coordination/disk_free_log.csv (columnas ts_local, free_gb, used_gb, total_gb, by; iniciado el 2026-11-09 17:25 por CO-62) como registro de linea base; propone como DUENO de la automatizacion diaria (P26) a la coordinadora vigente del vuelo dentro de su latido diario, PENDIENTE de decision del usuario; y aclara que la linea base de 14 registros SOLO condiciona decisiones por tasa de crecimiento, NUNCA las retiradas por lista aprobada (N6/E8/O6).


## Decisiones pendientes del usuario

1. Raiz del archivo y sus condiciones para D:, Internxt, jsonl, mensajes, hash y subida confirmada.
2. Aprobar o aplazar d-03 VACUUM INTO de kilo.db con la precondicion de >= 29,32 GB libres.
3. Reabrir U-R2 para d-02, la compresion NTFS.
4. Dueno de la automatizacion diaria de disk_free_log.csv.
5. Forma exacta de partir la herramienta dentro de 161j o en la hija H1: la decision de partir (161j diseno breve + H1 hija) ya esta tomada por el usuario; se lista por figurar en la seccion 12 de la ficha.
6. Topes del archivo y caducidad propuesta para las raices nuevas.
