# Ciclo de vida de los artefactos del vuelo (uso, archivado, eliminacion) y limites del archivo

- Estado: RATIFICADO por el usuario (messageId 6c621921-6e49-4b77-b685-e7599e5ab0e6, principio; messageId c253b945-642b-4eb4-8380-a5ae14137093, limites y raiz de archivo), web, 2026-11-09. Canon: fila P37 de `.agent/rules/common/vuelo_pilares.md`.
- Norma sin cablear: falta la ficha de la herramienta de aplicacion (contrato P7) y el comprobador de limites. Mientras tanto toda retirada la hace la coordinadora a mano con lista, hash y verificacion, y se anota en `OPERACION_EN_CURSO`.
- Para un agente frio: este fichero es el punto de entrada. Si buscas algo que ya no esta en local, mira el indice del archivo (seccion 5) antes de pensar que se perdio.

## 1. Principios
1. Cada familia de artefacto tiene dueno y tres fases: USO (local, caliente), ARCHIVADO (comprimido, con manifiesto sha256, en el archivo) y ELIMINACION (con caducidad y compuerta). Una familia sin las tres fases y sin herramienta que las ejecute no se archiva a ningun sitio.
2. Cada transicion la ejecuta un script con dry-run por defecto, lista con hash y codigo de retorno por modo. Nada entra en el archivo sin fila de indice y nada sale sin lista aprobada por el usuario con su hash (contrato P7).
3. El archivo NO es un basurero: tiene tope de tamano, indice obligatorio, caducidad por entrada y un comprobador de solo lectura cableado a un camino que corre solo.
4. Se reutiliza lo que existe; solo se escribe codigo nuevo para las familias que no tienen sistema.

## 2. Sistemas de rotacion ya existentes (leidos el 2026-11-09)
- `scripts/archive_arranques.py` y `scripts/purge_arranques_archive.py`: uso a archivo por CITACION (se mueve, no se borra) y archivo a eliminacion por `TTL_DAYS = 90`; la fila del indice se edita (`PURGADO <fecha>`), no se borra.
- `scripts/rotate_kilo_logs.py`: logs de Kilo; comprime a los 7 dias inactivos y borra lo comprimido a los 30, con locks y excepcion de vuelo activo. Es el modelo de tres fases mas cercano.
- `scripts/prune_runtime_retention.py`: retencion por conteo en superficies gitignored, dry-run por defecto.
- `scripts/prune_git_recoverable.py`: clasifica SAFE (los bytes actuales estan en git) o RISKY; poda solo SAFE.
- `scripts/prune_session_scratch.py`: scratch del harness por antiguedad (14 dias), manual.
- `scripts/memory_consolidate.py` y `scripts/archive_collaboration_artifacts.py`: memoria y colaboracion.
- `scripts/flight/measure_retention_inventory.py` (WOT-2026-158b, cerrada): medidor de solo lectura con fotos y `--compare`. WOT-2026-158c (pendiente): manifiesto y zip por vuelo fuera del arbol ignorado, sin borrar; su fase 2 (borrar zips) es otra ficha.

## 3. Flujo por familia
| Familia | USO (local) | ARCHIVADO | ELIMINACION |
|---|---|---|---|
| Documentacion del vuelo (`diseno/`) | mientras la coordinadora este en la terna o el fichero sea citado | al asentarse: zip y manifiesto a D: (replica en Internxt solo de documentacion) | caducidad 90 dias tras cerrar el vuelo, sin re-cita |
| Salidas crudas de reconcile y triaje (`raw/grep_hits.txt`) | 14 dias | comprimir y archivar con manifiesto | local tras verificar la copia; archivo a los 90 dias |
| Clones y sandboxes de lente o mutacion | la ronda viva | veredicto, ficheros citados y manifiesto (P2) | 7 dias tras cerrar la ronda, via P7 |
| Sesiones de Claude y `.codex/sessions` | 14 dias (`cleanupPeriodDays` NO se toca) | zip en D:; a la nube solo con escaneo de secretos y autorizacion expresa por categoria | via P7 tras el archivo, el export de mensajes y la prueba de resume |
| Logs de Kilo | 7 dias | comprimido | 30 dias (`rotate_kilo_logs`) |
| Reviews, packets, backups de observaciones, notificaciones | los 20 o 10 ultimos | no aplica | el resto (`prune_runtime_retention`) |
| Bases vivas (`statev2.sqlite`, `kilo.db`, `opencode.db`) | siempre | no aplica | no se podan a mano; `VACUUM INTO` solo con decision del usuario y espacio libre de al menos el doble |

## 4. Limites del archivo (ratificados)
- L-1 Raiz principal: `D:/flight_archive` (disco USB distinto de C:). Replica opcional en la carpeta sincronizada de Internxt (`C:/Users/fdl/InternxtDrive/vuelo_24h/`), solo documentacion, reportes y crudos comprimidos, y solo con la copia de D: verificada. Internxt NO sustituye a D:.
- L-2 Topes: Internxt 20 GB; D: 100 GB; 5 GB por vuelo. Superar el tope bloquea nuevas entradas hasta eliminar o fijar una excepcion aprobada por el usuario.
- L-3 Indice obligatorio: un `INDEX.md` y un indice maquina (JSON) por raiz, con una fila por entrada: ruta, familia, origen, fecha, sha256, tamano, dueno y fecha de caducidad (90 dias tras archivar; "fijada" solo para evidencia canonica, con motivo). Un fichero sin fila es un huerfano y cuenta como rojo.
- L-4 Solo comprimido y con manifiesto: un zip por familia y fecha, verificado por hash tras escribir; los zips no siguen junctions ni enlaces (`InternxtDrive` y `.claude-alvarovans/projects` lo son).
- L-5 Categorias con autorizacion: mensajes del usuario, transcripciones de sesiones y bases (`statev2`, `co24_pna`) no suben a la nube sin escaneo previo de secretos y autorizacion expresa por categoria. Todo lo que sube se escanea.
- L-6 Comprobador de solo lectura: mide cada raiz y falla ante tope superado, huerfano, entrada sin hash, entrada caducada sin propuesta o copia local ausente. Debe cablearse a `flight_stall_check` o al latido para que corra solo.
- L-7 Fallo cerrado: si D: no esta montado o Internxt no esta disponible, se aborta; nunca se cae a C:.
- L-8 Copiar no es subir: se distingue copia local verificada por hash de subida confirmada. La copia local solo se retira tras restaurar desde el archivo en otra ruta y comparar sha256.

## 5. Como encontrar y recuperar algo (agente frio)
1. Lee el `INDEX.md` de la raiz de archivo (`D:/flight_archive/INDEX.md`, y el de Internxt si existe) y busca la familia y la fecha.
2. El indice maquina da la ruta del zip, su sha256 y su caducidad; restaura en una carpeta nueva y vacia, nunca encima del original, y compara el hash.
3. Si la entrada ya caduco, mira la fila: se edita con `PURGADO <fecha>` y el motivo; no se borra.
4. Duda: pregunta a la coordinadora activa (`flight_roster.json`, `active_roles.orquestador`).

## 6. Pendiente de implantar
Herramienta de aplicacion (contrato P7: lista aprobada con hash, re-comprobacion por entrada de tamano, mtime y hash, aborto si difiere, guardas de proceso, cwd y lock, registro fuera de lo que se retira), comprobador de limites (L-6) y su cableado, y la ficha de rotacion WOT-2026-161j con sus hijas.
