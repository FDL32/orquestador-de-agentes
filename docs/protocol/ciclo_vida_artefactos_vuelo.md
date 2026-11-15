# Ciclo de vida de los artefactos del vuelo

- Estado: RATIFICADO para el ciclo y sus limites por el usuario (messageId 6c621921-6e49-4b77-b685-e7599e5ab0e6, principio; messageId c253b945-642b-4eb4-8380-a5ae14137093, limites y raiz), web, 2026-11-09. Este estado rige frente a las anclas de rotacion que aun dicen propuesta o pendiente: las anclas son una interface comprobable que no se edita sin autorizacion nueva.
- Canon de entrada: fila P37 de `.agent/rules/common/vuelo_pilares.md`. La fila P37 apunta a este documento, a `docs/protocol/rotacion_disco_vuelo.md` y a `scripts/flight/p7_retire.py`.
- Esta documentacion describe el estado ratificado del ciclo. La formula antigua que condicionaba la norma a que faltase una herramienta P7 ya no rige: `p7_retire.py` existe. Sigue abierto el comprobador L-6 y su cableado.

## 1. Raices vigentes y como buscar

Una raiz vigente es una carpeta que contiene zips y al menos un indice maquina de primer nivel. Los estados y cantidades de esta seccion son snapshots medidos el 2026-11-15 10:51:17 CET; las sondas de cierre deben volver a medirlos.

| raiz | indice maquina | familias observadas | estado |
|---|---|---|---|
| `D:/flight_archive` [externa] | `index.jsonl` | `reconcile`, `reports` y lotes del tercer escritor | RAIZ |
| `D:/flight_archive_kilo` [externa] | `index.jsonl` y `index_kilo.jsonl` | `kilo_mut_f_*`, `kilo_ba_f_*`, `kilo_mut_pilot3` | RAIZ |
| `D:/flight_archive_tools` [externa] | ninguno | herramientas, sin zips | NO-RAIZ |

El `INDEX.md` es un indice humano cuando existe. El indice maquina no es unico en la raiz de clones: `index_kilo.jsonl` cubre las filas del archivador y `index.jsonl` cubre la fila P7 de `kilo_mut_pilot3`; no se afirma que ninguno cubra todos los lotes. Cada carpeta de familia lleva el zip y el manifiesto hermano. Para encontrar una entrada, localizar primero su familia y fecha en el indice de su raiz, resolver la ruta del zip relativa a esa raiz y verificar `zip_sha256` antes de extraer.

Cobertura medida por raiz: en `D:/flight_archive_kilo` [externa] hay 14 filas de `index_kilo.jsonl` y 1 fila `ARCHIVADO` de `index.jsonl`; en `D:/flight_archive` [externa] hay 66 filas `RETIRADO_LOCAL` y 2 `ARCHIVADO` en su `index.jsonl`. La cobertura `RETIRADO_LOCAL` no satisface al reconciliador P7: `p7_common.reconcile_index` solo cuenta filas `ARCHIVADO` (lineas 271-310 de `scripts/flight/p7_common.py`; filtro en linea 286), y el cierre medido encontro 78 hallazgos en `reconcile` y 54 en `reports`. Migrar esas filas sin ensanchar el reconciliador es deuda WOT-2026-175d. Cualquier zip sin fila se declara `sin fila: motivo` y bloquea la afirmacion de cobertura completa; la sonda reproducible es leer cada indice y comparar sus rutas con los zips de cada familia.

## 2. Ciclo, herramienta y estado de los limites

Las familias pasan por USO, ARCHIVADO y ELIMINACION. El archivado conserva zip, manifiesto y fila; la eliminacion es una transicion P7 con lista aprobada. La interface completa vive en `docs/protocol/rotacion_disco_vuelo.md`; este documento no copia su contrato. La herramienta versionada que ejecuta el contrato es `scripts/flight/p7_retire.py`, con primitivas en `scripts/flight/p7_common.py`; sus 23 funciones `test_` estan en `tests/unit/test_p7_retire.py`.

El limite verificable es concreto: lineas 180-182 de `scripts/flight/p7_retire.py` exigen ficheros regulares, por lo que no recorre un clon como arbol; lineas 433-445 de `scripts/flight/p7_common.py` revalidan cada entrada de fichero. Ademas, lineas 301-308 de `scripts/flight/p7_retire.py` saltan ficheros versionados como `SALTADA_VERSIONADA`, y lineas 224-225 de `scripts/flight/p7_common.py` revalidan mtime. Por eso no es la herramienta que retira clones de Kilo. La deuda de una herramienta propia versionada del archivador es WOT-2026-175b. El comprobador L-6 y su cableado quedan sin ticket: motivo: el STOP de degeneracion exige una herramienta propia.

La implementacion P7 si ofrece lista aprobada y hash (lineas 411-430 de `scripts/flight/p7_common.py`), comprobacion de manifiesto (lineas 205-227 de `scripts/flight/p7_common.py`), aborto antes de retirar (lineas 403-408 de `scripts/flight/p7_retire.py`), lock y cwd (lineas 346-386 de `scripts/flight/p7_common.py`), registro fuera del origen (lineas 90-96 y 311-319 de `scripts/flight/p7_retire.py`) y dry-run por defecto (lineas 343-345 y 384-399 de `scripts/flight/p7_retire.py`). Para clones no cumple la clausula de retirada por la razon anterior (lineas 180-182 y 301-308 de `scripts/flight/p7_retire.py`).

Enumeracion m-01 para `p7_retire.py` y su modulo comun:

(1) CUMPLE: lista aprobada con hash de la lista (lineas 411-430 de `scripts/flight/p7_common.py`; el hash se compara en 416-418) y hash por entrada (lineas 433-445 de `scripts/flight/p7_common.py`), mas manifiesto por fichero (lineas 180-202 de `scripts/flight/p7_common.py`).
(2) CUMPLE: re-comprueba tamano, mtime y hash al aplicar (lineas 205-227 de `scripts/flight/p7_common.py`; tamano 222-223, mtime 224-225, hash 226-227), invocada en la linea 299 de `scripts/flight/p7_retire.py`.
(3) CUMPLE: aborta si algo difiere y devuelve rc 1 (lineas 403-408 de `scripts/flight/p7_retire.py`).
(4) PARCIAL: lock con pid y cwd de sesion (lineas 346-386 de `scripts/flight/p7_common.py`; el cwd se valida en lineas 352-353) y liberacion (lineas 388-396 de `scripts/flight/p7_common.py`); no hay guarda de proceso vivo sobre el origen.
(5) CUMPLE: registro en el indice de la raiz de archivo (lineas 90-96 de `scripts/flight/p7_retire.py`) mas guarda de no solape archive-root/origin (lineas 49-65 y 357-362 de `scripts/flight/p7_retire.py`).
(6) CUMPLE: dry-run por defecto (lineas 343-345 y 384-399 de `scripts/flight/p7_retire.py`).
(7) CUMPLE: es el dueno declarado del contrato y reutiliza el modulo comun `scripts/flight/p7_common.py` (importacion en la linea 27 de `scripts/flight/p7_retire.py`; uso de sus primitivas en las lineas 371-374), con 23 funciones `test_` en `tests/unit/test_p7_retire.py`.
(8) NO CUMPLE para clones: la lista aprobada es de FICHEROS (lineas 180-182 de `scripts/flight/p7_retire.py`) y salta los versionados por git (lineas 301-308 de `scripts/flight/p7_retire.py`). Por eso la retirada de clones es la excepcion de la seccion 4.

### Limites unicos L-1 a L-8

| limite | regla vigente del ciclo | sonda de solo lectura |
|---|---|---|
| L-1 | Raiz principal y raices vigentes declaradas por su contenido; la raiz es parametro explicito y D: falla cerrado. | listar carpetas, zips e indices de primer nivel |
| L-2 | Presupuesto por vuelo de 5 GB, ademas de los topes por raiz; no es autorizacion para superar ninguno. | sumar zips por vuelo y comparar con el indice |
| L-3 | Indice humano y maquina obligatorios, huerfano rojo y caducidad solo como propuesta P7 con hash; no autoriza retirada. | comparar zips, `INDEX.md`, indices JSONL y fechas |
| L-4 | Solo comprimido con manifiesto y hash. Para lotes ZIP_STORED se enmienda el adjetivo operativo de comprimido: siguen siendo lotes zip verificables y su sobrecoste queda medido. | `zipfile` y sha256 del zip, manifiesto y origen |
| L-5 | Categorias sensibles requieren escaneo y autorizacion expresa antes de replica. | revisar categoria, autorizacion y registro |
| L-6 | Comprobador de solo lectura con rc, aun no cableado. | ejecutar el comprobador cuando exista y registrar rc |
| L-7 | Fallo cerrado: si la raiz D: no existe o no es carpeta, parar y no buscar sustituto en C:. | `p7_retire.py` devuelve rc 4 (lineas 366-367) |
| L-8 | Copia local verificada y subida confirmada son estados distintos. | comparar hash local y evidencia del cliente |

La correspondencia con las anclas de `docs/protocol/rotacion_disco_vuelo.md` es: `L1.topes` -> L-2, `L2.indice` y `L2.huerfano` -> L-3, `L3.caducado` -> L-3, `L4.solo_comprimido` -> L-4, `L5.categorias` -> L-5, `L6.comprobador` y `L6.cableado` -> L-6, `L7.fallo_cerrado` -> L-7 y `L8.subida` -> L-8. La raiz que no tiene ancla propia queda en L-1. La prosa de ese documento remite aqui por nombre y numero; las anclas no se han editado. El estado RATIFICADO de este ciclo rige sobre las etiquetas propuesta o pendiente de las anclas porque es el estado canonico ratificado, sin ampliar el alcance de los messageId.

## 3. L-2, volumen y L-4

Snapshot fechado medido el 2026-11-15 10:51:17 CET: 83 zips, 37.661.340.108 bytes, 37,66 GB decimales. `D:/flight_archive_kilo` [externa] suma 36.883.848.591 bytes y `D:/flight_archive` [externa] 777.491.517 bytes. Este dato es evidencia fechada, no criterio. Frente al tope L-2 de 5 GB por vuelo, la excepcion para el volumen archivado queda **pendiente de aprobacion expresa del usuario**. Los messageId `47d968d6-cd95-4f46-b563-f15ba49d7edd` y `8ffd3f81-6d76-4aed-a1d2-7459be0a8df1` se citan solo como aprobacion operativa del volumen archivado y de la excepcion no-P7 de los clones; ninguno se presenta como ratificacion del tope L-2.

Snapshot fechado del sobrecoste de los 14 lotes ZIP_STORED: 36.600.681.652 bytes de zip frente a 36.044.189.876 bytes de origen, 1,544 por ciento. Conviven lotes DEFLATED y STORED; L-4 exige zip, manifiesto y hash, no una falsa uniformidad de metodo de compresion. La cifra es medicion, no criterio.

## 4. Excepcion de los clones de Kilo

- Alcance: el archivador propio de clones de Kilo, no futuras herramientas ni otras familias.
- Herramienta: `D:/flight_archive_tools/run_fast.py` [externa], apoyada por `D:/flight_archive_tools/run_tramo1.py` [externa]; no esta versionada.
- Autoridad: messageId 47d968d6-cd95-4f46-b563-f15ba49d7edd (pasada 1) y messageId 8ffd3f81-6d76-4aed-a1d2-7459be0a8df1 (pasada 2), citados solo en su parte operativa y sin texto privado.
- Condicion de fin: una herramienta versionada, deuda WOT-2026-175b, o la revocacion del usuario.
- Por que no p7_retire para clones: la lista aprobada es de FICHEROS regulares (lineas 180-182 de `scripts/flight/p7_retire.py`), salta los ficheros versionados por git como `SALTADA_VERSIONADA` (lineas 301-308), incrusta todas las entradas en la fila del indice (lineas 233-244) y re-comprueba mtime (lineas 224-225 de `scripts/flight/p7_common.py`).
- Efecto de P7 en la raiz principal `D:/flight_archive` [externa]: `p7_common.reconcile_index` solo cuenta filas `ARCHIVADO` (lineas 271-310 de `scripts/flight/p7_common.py`, filtro en la linea 286), asi que `scripts/flight/p7_retire.py` falla cerrado con rc 1 por las 66 filas `RETIRADO_LOCAL`; migrarlas sin ensanchar `reconcile_index` es deuda WOT-2026-175d.

Enumeracion m-01 para el archivador, medida en los ficheros externos con estas lineas: (1) exenta: no conserva una lista aprobada con hash de la lista; deriva la lista y hashea fichero a fichero (lineas 12-16 y 24-30 de `D:/flight_archive_tools/run_fast.py` [externa]); (2) exigible de forma parcial: guarda tamano, sha256 y nombres y comprueba extras, pero no mtime (lineas 65-68 de `D:/flight_archive_tools/run_fast.py` [externa]); (3) exigible: aborta sin borrar ante discrepancia (lineas 59-68 de `D:/flight_archive_tools/run_fast.py` [externa]); (4) exigible de forma parcial: guarda de proceso vivo con exclusion de shells y `claude.exe`, sin guarda de cwd ni lock (linea 37 de `D:/flight_archive_tools/run_tramo1.py` [externa]); (5) exigible de forma parcial: el registro queda fuera del arbol retirado, pero es temporal (linea 79 de `D:/flight_archive_tools/run_fast.py` [externa]); (6) exenta: no ofrece dry-run; (7) exenta: no es el dueno P7; (8) exenta por esta excepcion: no toda retirada pasa por P7. Las partes exigibles se limitan a lo que el archivador realmente mide; la deuda restante no se presenta como cubierta.

## 5. Recuperacion reproducible

La receta corregida es: detectar la raiz y leer su indice; localizar zip, manifiesto y `zip_sha256`; crear una carpeta nueva y vacia fuera de cualquier repo; ejecutar `python -I -m zipfile -e ZIP CARPETA` con el interprete del motor; y ejecutar el script parametrizado siguiente. El nombre depende del escritor: `kilo_mut_pilot3-20261115T000628Z.zip` fue escrito por P7 y `kilo_mut_f_t108.zip` por el archivador.

El lote mas pequeno citado por escritor es `kilo_mut_pilot3-20261115T000628Z.zip`, 283.166.939 bytes, 25.398 ficheros, DEFLATED, con manifiesto hermano; el lote menor del archivador es `kilo_mut_f_t108.zip`, 660.388.511 bytes, 43.185 ficheros, STORED. Los dos recibos siguientes se reprodujeron en carpetas nuevas y vacias bajo una ruta temporal que se borra despues, con el script de comparacion del bloque anterior copiado sin modificarlo; D: no se toco. Los reprodujo el revisor del ticket, no el autor: el verificador independiente V1 no entrego transcripcion y se declara NO VERIFICABLE por tercero.

RECIBO 2026-11-15 11:23 (lote escrito por p7_retire): interprete `C:/Users/fdl/.t3/worktrees/orquestador_de_agentes/orquestadora-3-vuelo-20261026b/.venv/Scripts/python.exe` [externa]; cwd `C:/Users/fdl/.t3/worktrees/orquestador_de_agentes/implantador-175a-20261115`; `python -I -m zipfile -e ZIP CARPETA` rc 0 en 23,2 s con 25.398 ficheros restaurados; comparador rc 0 en 210,0 s con `{"bad": [], "extra": [], "index_ok": true, "zip_sha256": "79a0f1b75beb7d5b680cb6b6fa9daba6e89553ccb39928bf0aa83a53dc2c47d9"}`; el zip conserva tamano (283.166.939 bytes) y mtime antes y despues.

RECIBO 2026-11-15 11:26 (lote escrito por el archivador): mismo interprete y cwd; extraccion rc 0 en 31,9 s con 43.185 ficheros; comparador rc 0 en 334,8 s con `{"bad": [], "extra": [], "index_ok": true, "zip_sha256": "c367c80b93ea95184c04e216e6e54f0e2ca837bc3469c406714b9be857659fb9"}`; el zip conserva tamano (660.388.511 bytes) y mtime antes y despues.

CONTROL POSITIVO de ese mismo script (2026-11-15 11:29): sobre una copia restaurada con un byte alterado y un fichero extra, devuelve rc 1 con `bad=[["sha256", "152s_mut_4/.agent/.version_manifest.json"]]` y `extra=["FICHERO_EXTRA_DE_CONTROL.txt"]`: la comparacion muerde. El tercer escritor, los 68 zips DEFLATED de `D:/flight_archive` [externa], queda no probado: fuera de la clausula.

```python
import argparse
import hashlib
import json
from pathlib import Path

def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("zip")
    parser.add_argument("manifest")
    parser.add_argument("restored")
    parser.add_argument("index")
    args = parser.parse_args()
    zip_path = Path(args.zip)
    restored = Path(args.restored)
    rows = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    bad = []
    expected = set()
    for row in rows:
        rel = str(row["rel"])
        expected.add(rel.replace("\\", "/"))
        path = restored / rel
        if not path.is_file():
            bad.append(("missing", rel))
            continue
        if path.stat().st_size != int(row["size"]):
            bad.append(("size", rel))
        if sha256(path) != row["sha256"]:
            bad.append(("sha256", rel))
    actual = {p.relative_to(restored).as_posix() for p in restored.rglob("*") if p.is_file()}
    extra = sorted(actual - expected)
    index_rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    indexed = [row for row in index_rows if row.get("zip") == str(zip_path) or Path(str(row.get("zip", ""))).name == zip_path.name]
    zip_hash = sha256(zip_path)
    index_ok = bool(indexed) and any(row.get("zip_sha256") == zip_hash for row in indexed)
    print(json.dumps({"bad": bad, "extra": extra, "zip_sha256": zip_hash, "index_ok": index_ok}, sort_keys=True))
    return 1 if bad or extra or not index_ok else 0

if __name__ == "__main__":
    raise SystemExit(main())
```

El script compara existencia, tamano, sha256, conjunto restaurado y conjunto del manifiesto, y el sha256 del zip con `zip_sha256` del indice. No compara mtime: `zipfile -e` no restaura mtime. Si `D:/flight_archive_kilo` o `D:/flight_archive` [externa] no existe o no es carpeta, se detecta antes de leer el indice, se para y se informa a `flight_roster.json` [externa] -> `active_roles.orquestador`; nunca se cae a C:.

## 6. Deudas y contacto

- Archivador propio versionado: WOT-2026-175b.
- Comprobador L-6 y su cableado: sin ticket: motivo: el STOP de degeneracion exige una herramienta propia.
- Migracion de filas `RETIRADO_LOCAL` sin ensanchar `reconcile_index`: WOT-2026-175d.
- Purga por caducidad: WOT-2026-175c.
- Herramienta de sesiones, `.venv` y `co24_pna`: sin ticket, porque el STOP de degeneracion exige herramienta propia y no forman parte de este deliverable.

Para una duda de estado se pregunta a la coordinadora activa, resuelta desde `flight_roster.json` [externa] y su campo `active_roles.orquestador`. Para una discrepancia de indice se conserva el rc y la salida de la sonda de solo lectura; no se corrige el archivo manualmente.
