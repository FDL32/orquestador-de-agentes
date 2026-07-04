# Work Plan - WOT-2026-016x

## Metadata
- **ID:** WOT-2026-016x
- **Estado:** APPROVED
- **deliverable_type:** code
- **Titulo:** run_quality_gates no imprime el WARN de "veredicto no concluyente" de pytest;
  el operador queda ciego a esa senal aunque el gate siga pasando por diseno.
- **Asignado a:** Builder
- **delivery_authority:** repo_motor

## Objetivo

Cuando run_quality_gates (.agent/agent_controller.py) detecta que el stamp de
run_pytest_safe es inconclusive (stale o ausente) y anade un WARN a
results["warnings"], ese WARN debe llegar al operador como salida VISIBLE
(stdout) en el mismo lugar donde ya se imprime el header y el status final del
gate. Hoy el WARN se acumula en el dict de retorno pero nunca se imprime, y como
passed sigue True (correcto: inconclusive no es un fallo), el operador nunca
lo ve ni por consola ni por el veredicto [PASSED]/[FAILED].

Verificacion del objetivo (comando literal): un nuevo test en
tests/test_agent_controller.py que mockea _read_pytest_safe_verdict para
devolver un dict con verdict inconclusive, llama run_quality_gates() bajo
capsys de pytest, y afirma que el texto del WARN aparece en
capsys.readouterr().out. El test falla sin el fix (WARN tragado, no aparece en
stdout) y pasa con el fix.

## Contexto (diagnostico de Fase 0, confirmado en codigo por el Manager)

- .agent/agent_controller.py:2089-2154 -- run_quality_gates(plan_type):
  - L.2091: imprime el header de Quality Gates.
  - L.2092: construye results = {"passed": True, "errors": [], "summary": [], "warnings": []}.
  - L.2142-2146: cuando _read_pytest_safe_verdict() devuelve
    verdict == "inconclusive" (stamp stale/absent), hace
    results["warnings"].append(...) con el mensaje "[WARN] Pytest: veredicto no
    concluyente (...); corre scripts/run_pytest_safe.py --level all sobre HEAD".
    NO toca results["passed"] (queda True -- by design, ver comentario
    L.2124-2135: no fingir pass/fail cuando el stamp no es concluyente).
  - L.2152-2153: status = "[PASSED]" if results["passed"] else "[FAILED]";
    print de status. Los items de results["summary"] y results["warnings"]
    NO se imprimen individualmente en ningun punto de la funcion -- solo se
    acumulan en el dict de retorno.
- .agent/agent_controller.py:2227-2255 -- _check_quality_gates(plan_id,
  plan_type, plan_status, skip_gates): L.2239 llama
  gate_result = run_quality_gates(plan_type=plan_type); L.2240 evalua
  UNICAMENTE gate_result["passed"]. Si es True (caso inconclusive incluido),
  retorna None en L.2255 sin inspeccionar ni imprimir summary/warnings.
- .agent/agent_controller.py:2497 -- unico caller de _check_quality_gates,
  dentro de determine_next_action, en la rama con plan_status APPROVED,
  log_status READY_FOR_REVIEW y skip_gates False. Cuando _check_quality_gates
  retorna None, el flujo continua sin ninguna traza del WARN.
- Severidad (confirmada, no re-litigar en este ticket): redundante-seguro. El
  gate de --pre-handoff (pre_handoff_guard.assert_canonical_suite_green) exige
  stamp verde por separado antes de cerrar, asi que este gap NO permite un
  falso-verde de cierre. El gap es exclusivamente de VISIBILIDAD diagnostica
  durante determine_next_action / _check_quality_gates.
- Test existente relevante ya cubre el dict de retorno pero NO la impresion:
  tests/test_agent_controller.py:408-429
  test_run_quality_gates_inconclusive_stamp_does_not_fake_pass ya verifica que
  el WARN aparece en result["warnings"] (el dict), y que NO aparece "Pytest" en
  result["summary"]. Ese test seguira pasando sin cambios: no verifica stdout,
  solo el dict. Es complementario al test nuevo de este ticket, no redundante.

## Enfoque elegido (decision del humano)

Propagar el WARN al operador imprimiendolo, SIN cambiar el veredicto. Punto
exacto: dentro de run_quality_gates, inmediatamente antes de la linea
status = "[PASSED]" if results["passed"] else "[FAILED]" (L.2152 actual),
anadir un bucle que imprima cada item de results["warnings"]:

    for warning in results["warnings"]:
        print(f"   {warning}")

Por que este punto y no otro:

- run_quality_gates es la unica funcion que ya posee logica de impresion para
  esta gate (el header L.2091 y el status final L.2153); mantener toda la
  impresion de esta gate en un solo lugar evita duplicar logica de output en
  cada caller.
- _check_quality_gates (el caller relevante) debe seguir siendo responsable
  SOLO de decidir el flujo de control (AUTO-REJECT vs None), no de imprimir;
  mezclar ambas responsabilidades ahi haria mas fragil el path de AUTO-REJECT
  que WT-2026-204 ya endurecio con tests propios.
  Ver tests/test_agent_controller.py:2344-2409 (TestAutoRejectQualityGates):
  esos tests no deben requerir cambios. Confirmado en Fase 0 mockeando
  run_quality_gates directamente (no llaman a la funcion real), por lo que un
  print nuevo dentro de run_quality_gates no los afecta.
  El caller en determine_next_action (L.2497) tampoco cambia: sigue
  invocando _check_quality_gates sin inspeccionar summary/warnings
  directamente, porque la visibilidad ya queda resuelta dentro de
  run_quality_gates antes de que el resultado se propague.
- Imprimir ANTES del status final (no despues) mantiene el orden de lectura
  natural para un operador en consola: primero ve los detalles/warnings de la
  corrida, despues el veredicto agregado [PASSED]/[FAILED] como ultima linea.
- Alcance minimo: NO se anade impresion de results["summary"] (ya cubierto
  como texto interno del dict pero no impreso hoy tampoco) porque el ticket es
  estrictamente sobre el WARN de pytest inconclusive descrito en el
  diagnostico; ampliar a imprimir tambien summary es un cambio de
  comportamiento mas amplio no pedido por el humano y queda fuera de alcance
  (ver Non-goals).

## Non-goals

- NO convertir el veredicto inconclusive en fail ni en AUTO-REJECT. passed
  sigue siendo True con stamp inconclusive; este ticket NO reintroduce el
  falso-rojo que WOT-2026-016c elimino deliberadamente.
- NO tocar --pre-handoff ni pre_handoff_guard.assert_canonical_suite_green:
  ese gate de cierre ya exige stamp verde por separado y esta fuera de alcance.
- NO cambiar la logica que calcula results["passed"] en ningun branch de
  run_quality_gates (ruff, estado, pytest verde/rojo/inconclusive,
  finalization checks).
- NO imprimir results["summary"] en este ticket (ver Enfoque elegido, alcance
  minimo): solo results["warnings"].
- NO modificar _check_quality_gates ni su firma, ni el caller en
  determine_next_action (L.2497): el fix vive enteramente dentro de
  run_quality_gates.
- NO tocar tests/test_agent_controller.py:408-429
  (test_run_quality_gates_inconclusive_stamp_does_not_fake_pass) ni la clase
  TestAutoRejectQualityGates (L.2344-2409): deben seguir pasando sin
  modificacion.

## Files Likely Touched

### repo_motor

- .agent/agent_controller.py
- tests/test_agent_controller.py

## Tests Esperados

1. Nuevo test en tests/test_agent_controller.py, dentro de
   class TestRunQualityGates (junto a
   test_run_quality_gates_inconclusive_stamp_does_not_fake_pass, L.408-429):

   test_run_quality_gates_inconclusive_stamp_prints_warning_to_operator:
   - Usa el fixture nativo capsys de pytest (parametro de la funcion de test,
     sin import adicional -- ya disponible, pytest esta en las dependencias del
     repo).
   - Mockea agent_controller.read_file (return_value=""),
     agent_controller.subprocess.run (MagicMock con returncode=0), y
     agent_controller._read_pytest_safe_verdict para devolver un dict con
     verdict inconclusive y detail sin last-run.json (mismo patron que el
     test existente L.408-423).
   - Llama result = run_quality_gates().
   - Captura captured = capsys.readouterr().
   - Afirma result["passed"] is True (el veredicto NO cambia -- criterio de
     aceptacion 2).
   - Afirma que el texto exacto del WARN aparece en captured.out: usa el
     mismo item que ya esta en result["warnings"][0] (reutilizar el string
     real devuelto por la funcion, no una copia literal hardcodeada, para que
     el test no diverja si el mensaje cambia de redaccion en el futuro).
   - Afirma tambien, como red adicional del criterio 1 (visibilidad
     inequivoca), que la subcadena "no concluyente" aparece en captured.out
     en minusculas.
2. No-regresion: test_run_quality_gates_inconclusive_stamp_does_not_fake_pass
   (L.408-429), test_run_quality_gates_pytest_green_from_stamp (L.368-383),
   test_run_quality_gates_real_failure_is_not_masked (L.385-406),
   test_run_quality_gates_does_not_rerun_pytest_with_timeout (L.340-366), y
   toda la clase TestAutoRejectQualityGates (L.2344-2409) siguen verdes sin
   modificacion.
3. MUTATION (documentado en execution_log.md, no como test pytest nuevo
   separado): revertir temporalmente el bucle de impresion anadido (dejar
   run_quality_gates como esta hoy en HEAD, sin el bucle for/print sobre
   results["warnings"]) y confirmar que
   test_run_quality_gates_inconclusive_stamp_prints_warning_to_operator
   FALLA (el WARN no aparece en captured.out aunque result["passed"] siga
   True). Restaurar el fix y confirmar que el mismo test PASA. Documentar
   ambos exit codes literales en execution_log.md (mismo patron ya usado en
   WOT-2026-015m: backup temporal, revertir, correr, capturar exit code,
   restaurar, re-correr, capturar exit code, git diff --stat limpio al final).

## Criterios de Aceptacion (binarios)

1. Con un stamp inconclusive (mockeado via _read_pytest_safe_verdict), el
   WARN completo (el string real que ya construye la L.2144-2146 actual)
   aparece en la salida estandar capturada por capsys durante la ejecucion de
   run_quality_gates(). Verificado por
   test_run_quality_gates_inconclusive_stamp_prints_warning_to_operator.
2. result["passed"] sigue siendo True en el mismo escenario (el veredicto
   NO cambia a AUTO-REJECT): verificado en el mismo test nuevo, y por
   no-regresion en test_run_quality_gates_inconclusive_stamp_does_not_fake_pass
   (existente, sin modificar).
3. MUTATION: revertir el bucle de impresion anadido hace fallar
   test_run_quality_gates_inconclusive_stamp_prints_warning_to_operator
   (WARN ausente de stdout); con el fix restaurado, el mismo test PASA. Ambos
   resultados (FAIL-sin-fix con exit code, PASS-con-fix con exit code) quedan
   registrados literalmente en execution_log.md.
4. Suite canonica: .venv/Scripts/python.exe scripts/run_pytest_safe.py
   --level all con last-run.json en status=finished, exit_code=0,
   level=all, args_mode=default_discovery y tested_commit_sha == HEAD del
   commit que se entrega.
5. ruff check .agent/agent_controller.py tests/test_agent_controller.py ->
   exit code 0.
6. validate (Manager gate, ver abajo) en 0 errors / 0 warnings.

## Quality Gates

- Builder ejecuta:
  - .venv/Scripts/python.exe -m pytest tests/test_agent_controller.py -v
  - .venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider
  - ruff check .agent/agent_controller.py tests/test_agent_controller.py
  - .venv/Scripts/python.exe scripts/run_pytest_safe.py --level all
- Manager gate (Builder NO lo ejecuta salvo diagnostico local):
  - .venv/Scripts/python.exe .agent/agent_controller.py --validate --json
    --project-root .

## STOP conditions

- Si imprimir results["warnings"] cambia el resultado de algun test existente
  que capture stdout con una asercion de igualdad estricta sobre la
  salida completa de run_quality_gates: DETENTE, no relajes ese test para
  forzar verde, documenta el hallazgo y escala al Manager. Verificado en Fase
  0: ningun test existente hace capsys sobre run_quality_gates hoy, por lo
  que no deberia haber colision -- si el Builder encuentra uno al implementar,
  es una desviacion del diagnostico y debe pararse.
- Si test_run_quality_gates_inconclusive_stamp_does_not_fake_pass (L.408-429)
  deja de pasar tras el cambio: DETENTE, el fix esta tocando el dict de retorno
  ademas de la impresion, lo cual esta fuera de alcance.
- Si alguno de los tests de TestAutoRejectQualityGates (L.2344-2409) deja de
  pasar: DETENTE, el cambio se filtro a _check_quality_gates fuera del scope
  aprobado.
- Si run_pytest_safe.py --level all no cierra con tested_commit_sha == HEAD
  del commit final: no reportes cierre canonico; re-corre tras el commit final
  antes de --mark-ready.

## Riesgos

- Bajo: cambio aislado (un bucle print de 2 lineas) dentro de una funcion ya
  cubierta por 5 tests existentes que no capturan stdout hoy, por lo que no hay
  colision esperada. Confirmado por grep: ningun test en
  tests/test_agent_controller.py usa capsys junto a run_quality_gates
  antes de este ticket.
- Bajo: el cambio no toca ninguna rama de calculo de passed, solo anade
  impresion de items ya existentes en el dict; el riesgo de regresion
  funcional es minimo.

## Decision Arquitectonica

Por que imprimir dentro de run_quality_gates (antes del status final) en vez
de: (a) que _check_quality_gates imprima cuando passed=True y hay warnings, o
(b) que el caller en determine_next_action inspeccione summary/warnings
directamente. La opcion (a) dispersaria la logica de impresion de esta gate en
dos funciones (header/status en una, warnings en otra), complicando el
mantenimiento futuro y arriesgando que un cambio en _check_quality_gates (que
WT-2026-204 ya protege con tests especificos del path AUTO-REJECT) se acople a
una responsabilidad de output que no le corresponde. La opcion (b) requeriria
que cualquier caller futuro de run_quality_gates reimplemente la misma logica
de impresion para no perder visibilidad, duplicando codigo. Concentrar el
print en run_quality_gates, ya duena del header y del status final de esta
gate, es el cambio minimo que garantiza que cualquier caller (el actual y
los futuros) vea el WARN sin tener que saber que existe.

## Trade-offs Considerados

| Opcion | Pros | Contras | Decision |
|--------|------|---------|----------|
| print en run_quality_gates, antes del status final | Un solo punto de impresion para toda la gate; visible para cualquier caller presente o futuro; cambio de 2 lineas | Ninguno relevante detectado | Elegida |
| print en _check_quality_gates cuando passed=True y hay warnings | Tambien visible para el caller actual | Dispersa la logica de output de la misma gate en dos funciones; acopla una responsabilidad de impresion a la funcion que WT-2026-204 ya protege como path de decision AUTO-REJECT | Descartada |
| El caller determine_next_action inspecciona summary/warnings y los imprime | Ningun cambio en run_quality_gates | Cualquier caller futuro debe reimplementar la misma logica para no perder visibilidad; hoy solo hay un caller pero no hay garantia de que siga siendo el unico | Descartada |
| Tambien imprimir results["summary"] (no solo warnings) | Visibilidad de summary y warnings en el mismo test de la gate | Cambio de alcance mas amplio que lo pedido por el humano; fuera de los Non-goals de este ticket | Descartada para este ticket (posible follow-up) |

## Criterios de Aceptacion Global
- [ ] El WARN de pytest inconclusive aparece en stdout capturado por capsys
- [ ] result["passed"] sigue True con stamp inconclusive (no AUTO-REJECT)
- [ ] Mutation FAIL-sin-fix / PASS-con-fix documentado en execution_log.md
- [ ] No-regresion: los 4 tests de TestRunQualityGates existentes + los 2 de
      TestAutoRejectQualityGates siguen verdes sin modificacion
- [ ] ruff check en verde sobre los 2 archivos tocados
- [ ] Suite canonica run_pytest_safe.py --level all verde con
      tested_commit_sha == HEAD
- [ ] validate --json 0 errors / 0 warnings (Manager gate)
