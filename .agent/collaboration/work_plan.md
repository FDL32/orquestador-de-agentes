# Work Plan - WOT-2026-016o

## Metadata
- **ID:** WOT-2026-016o
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** classify_publication: aplicar REDACTION_PATTERNS tambien a la historia (H1 history-blind a PII)
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

H1 (auditoria externa 2026-07-03, CONFIRMADO EN CODIGO): `_scan_history_secrets` itera todos
los blobs de `rev-list --all` pero solo aplica SECRET_PATTERNS; REDACTION_PATTERNS (emails,
`C:\Users\...`, `/home/...`, `.local`) SOLO escanea el working tree (L315/327). Un email o
ruta personal en blobs de commits antiguos pasa el gate con falso verde. En la tanda backup
esto obligo a scans manuales paralelos (patron laxo) para cada repo.

## Decision Arquitectonica

- El scan de PII de historia se integra en el MISMO recorrido de blobs de
  `_scan_history_secrets` (cero coste extra de iteracion): la funcion pasa a devolver
  `(secret_findings, pii_findings)`.
- PII en historia NO es "secreto" (exit 1) ni redactable en working tree: exige decision
  humana (rewrite o aceptar) -> nuevo blocked_reason `HISTORY_PII_PENDING` y el verdict cae a
  `DECIDE_PENDING` (exit 3, intervencion humana). Precedencia: tras BLOQUEADO_POR_SECRETO.
- ALLOWLIST de placeholders sobre el TEXTO del match (leccion de la tanda: las redacciones
  legitimas `C:\Users\<user>`, `<redacted-email>`, `*@example.com`, `/home/user`, noreply,
  `[TU_USUARIO]`, `tu-*@`, `usuario@` NO deben bloquear el gate); un blob solo se reporta si
  tiene >=1 match NO-placeholder.
- Fixtures de seguridad y HISTORY_ACCEPTED_PATHS conservan sus exenciones actuales.
- Manifest: nueva clave `history_pii_scan: {enabled, ok, findings}` simetrica a
  history_secret_scan; findings con muestras de match ENMASCARADAS (no reproducir PII entera).

## Fases

### Fase 0 - Diagnostico (COMPLETADO)
- Codigo confirmado: patterns L141-147; history scan L436-487 (solo SECRET); verdict L565-595;
  blocked_reasons L489-562; manifest L676-697. Ningun test toca los internals (rg 0).

### Fase 1 - Implementacion
- `HISTORY_PII_PLACEHOLDER_PATTERNS` (allowlist compilada sobre el texto del match).
- `_scan_history_secrets` devuelve tupla; caller desempaqueta; `_build_blocked_reasons` y
  `_decide_verdict` reciben `history_pii_findings`; manifest emite `history_pii_scan`.

### Fase 2 - Tests (barrera FAIL-sin/PASS-con)
- `tests/test_classify_history_pii.py` (repos git REALES en tmp_path, sin mock de subprocess):
  - historia con email real en blob BORRADO del tree -> HISTORY_PII_PENDING + DECIDE_PENDING +
    history_pii_scan.ok=False.
  - historia solo con placeholders -> ok=True, sin bloqueo.
  - MUTATION: monkeypatch REDACTION_PATTERNS=[] -> el hallazgo desaparece (el scan es la
    barrera, no cosmetico).

## Criterios de aceptacion

1. Repo tmp cuya historia contiene email/ruta real en blob antiguo -> el gate lo DETECTA
   (HISTORY_PII_PENDING; verdict != LISTO_PARA_PUBLICAR).
2. Placeholders legitimos NO bloquean (allowlist verificada con test).
3. MUTATION verificada: sin el scan, vuelve el falso verde.
4. Sin PII reproducida entera en el manifest (matches enmascarados).
5. ruff + format + encoding verdes; suite canonica exit 0 sha==HEAD; validate 0/0.

## Files Likely Touched

### repo_motor
- `scripts/classify_publication.py`
- `tests/test_classify_history_pii.py` (nuevo)

## Non-goals
- NO tocar SECRET_PATTERNS ni la semantica de BLOQUEADO_POR_SECRETO.
- NO tocar el tree-side REDACTION (L315/327) ni los buckets.
- NO anadir rewrite automatico de historia (la decision es humana; esto es el detector).
- NO mezclar con el gate por-fila (016m).
