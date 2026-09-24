# Junk Patterns — checklist compartido (autoria + auditoria)

Adaptado de `openclaw/openclaw` (`.agents/skills/test-audit/SKILL.md`, MIT).
Un match no es veredicto automatico: pasa por `value-bar.md` antes de
proponerse como candidato a eliminacion.

Un test candidato debe compararse contra CADA patron de esta lista antes de
pasar a `candidate-evidence.md`. Cita el patron exacto que matchea; "parece
basura" no es una clasificacion valida.

## Lista

1. **Assertion-free coverage probes** — el test se ejecuta y no falla nunca
   porque no hace ninguna aserción real (o solo `assert True` / `assert
   result is not None`).
2. **Self-comparisons e identity copiers** — el test recalcula el mismo valor
   que produce el codigo bajo prueba y lo compara consigo mismo.
3. **Copied fixtures, inventories, manifests, or export lists** — el fixture
   es una copia 1:1 de una lista/manifest que produccion ya mantiene; cambia
   junto con produccion sin que el test detecte nada.
4. **Exact source, import, or string greps** — el test grep-ea texto literal
   del fichero fuente en vez de ejercer comportamiento. Ver la excepcion en
   `value-bar.md` ("source inspection when it is the cheapest independent
   guard").
5. **Private predicate or call-shape tests duplicated at real boundaries** —
   testea una funcion privada que ya esta cubierta indirectamente por su
   caller publico/CLI.
6. **Duplicate invocations of the same contract** — dos o mas tests ejercen
   exactamente el mismo camino con datos triviales distintos, sin anadir un
   caso limite nuevo.
7. **Provider-local replays of shared helpers** — un helper compartido
   (`bus/`, `scripts/_shared`) se re-testea identico en cada modulo que lo
   importa, en vez de una vez en su owner.
8. **Tests cuyo unico proposito es preservar exports/globals/wrappers
   test-only** — el seam de produccion existe solo porque el test lo necesita,
   ningun caller real lo usa.
9. **Dead production code cuyos unicos callers son tests** — sintoma
   relacionado: si se borra el test, `code-audit` deberia marcar ese codigo
   como candidato DEAD/ABANDONED.
10. **Expected values producidos por el mismo helper/renderer bajo prueba** —
    el "expected" se computa llamando a la misma funcion que se esta
    verificando (tautologia). Ver la leccion de memoria
    `WOT-2026-039l` (mutation-verify tautologico) como caso real de este repo.
11. **Mocks que implementan el comportamiento aseverado**, o un mismo mock
    parcheando APIs distintas — el test pasa porque el mock ya decide el
    resultado, no porque el codigo real lo produzca.
12. **Fixtures que ya suministran el receipt/admision/orden de callback que el
    owner deberia producir**, o persistencia verificada contra un store que el
    path real nunca escribe.
13. **Capability tests que solo repiten un flag declarado** en vez de ejercer
    la entrega/confirmacion que ese flag promete.
14. **Negative controls que pasan por razon equivocada** — una denegacion
    viene de un guard distinto al que se queria probar, o de un camino que
    produccion nunca alcanza.
15. **Nombres/fixtures que prometen mas de lo que el input ejercita** — p.ej.
    un test llamado "retires the window" que en realidad solo comprueba que la
    ventana no se limpio, sin ejercer el retiro real.

## Patrones adicionales observados en este repo

Estos no estan en la lista original de openclaw pero son recurrentes aqui,
segun memoria de sesion y AGENTS.md:

16. **Grep-de-texto disfrazado de comportamiento** (memoria
    `grep-text-is-not-behavior`): el test lanza un grep sobre el fichero en
    vez de invocar el wrapper/CLI real. Distinto del patron 4 (grep de
    IMPORT/string) en que aqui el test cree estar probando un flujo end-to-end
    y solo esta leyendo texto.
17. **Mock drift**: el patch apunta a `X` pero produccion llama a `Y` (API
    distinta). Ejemplo documentado en AGENTS.md: parchear `pathlib.Path.open`
    cuando el codigo usa el `open()` builtin. El test pasa sin probar nada
    real — es el caso mas peligroso porque no aparece como "raro" a primera
    lectura.
18. **Floor assertion**: el umbral de una aserción numerica ya lo satisface el
    valor BASE sin la feature bajo prueba (ejemplo real de AGENTS.md:
    `assert score >= 150` cuando el score de recencia ya es `~20_000_000` sin
    la feature). Se detecta mutando la feature a "no aplicada" y viendo si el
    test sigue en verde.
19. **Fixture ad-hoc para el propio barrido** (memoria de AGENTS.md, "un
    umbral en una meseta"): un test que valida un umbral contra fixtures
    escritos a proposito para ese mismo test, en vez de contra la suite/datos
    reales. Mide el fixture, no el sistema.
