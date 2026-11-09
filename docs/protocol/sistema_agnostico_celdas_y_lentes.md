# Estado y decisiones

- Estado: APROBADO EN PRINCIPIO por el usuario (2026-11-09). Canon: filas P30 a P33 de `.agent/rules/common/vuelo_pilares.md`; este fichero es su fuente larga versionada.
- Decision del usuario (messageId fe7a644c-0f51-491f-b7ec-e021109b0682, web): se aprueba el sistema agnostico y, por el momento, la celda del IM es: BUILDER = codex (hijo de cada IM, lanzado con `delegate_task`); IM#1 con REVISOR deepseek (nan); IM#2 con REVISOR glm 5.3 flash (nan). Un IM nunca se lanza como sesion unica.
- Orden anterior del usuario (messageId 85feaef0-d2ba-449b-a434-3f4417e08fe8, web): terminar IM-106 e IM-107 como estaban y aplicar la celda completa a los siguientes tickets.
- Pendiente del usuario: U2 (criterio de cierre del piloto de la celda) y U3 (politica de familias de lentes). Pendiente de implantar: ficha de diseno y resolvedor.
- Origen: el 2026-11-09 la coordinadora lanzo IM-106 e IM-107 como sesiones unicas; la orden permanente (revisor nan mas builder codex hijo) se habia degradado en la regeneracion manual de la seccion de ordenes del ARRANQUE de cada relevo. Un bucle de 8 lentes (todas CHANGES sobre la primera propuesta) corrigio la causa: sin canon versionado, sin regla de precedencia y sin comprobacion de conformidad.
# Sistema agnostico de celdas y lentes del vuelo (cambiar de lente o de modelo editando UNA declaracion)
## 1. Lo que YA existe en el motor (medido en .agent/config/agents.json)
- ensemble_registry.backend_keys (53 claves BAnn): cada una con backend, model, lab, family, tier, generation, status. Ej.: BA07 kilo nan/deepseek-v4-flash lab DeepSeek family deepseek; BA03 glm; BA02 qwen; BA253 claude opus; BA254 codex gpt-6.1-sol; BA06 opencode glm.
- ensemble_profiles (45): como se lanza cada una (backend, channel agent o api, modelo, write, backend_key).
- role_mapping (orchestrator, manager, revisor, builder, auditor, challenger) con backend/model y ensemble_profiles_ref; ensemble_registry.loop_shapes (UNI-n, DBL-n).
- Lo que NO existe: (a) la CELDA del IM como rol declarado (revisor + builder hijo); (b) el PANEL de lentes de una ronda como declaracion: vive hardcodeado en los scripts de lanzamiento que escribe cada coordinadora a mano (profiles, claves, entorno de cuenta, que bundle recibe cada una); (c) la INDEPENDENCIA por familia como regla ejecutable aunque el dato family ya esta en el registro; (d) un solo sitio donde cambiar un proveedor.
## 2. Diseno (3 declaraciones + 1 resolvedor; sin tocar el despachador)
D1 CELDAS (im_cells en la config): cada celda = lista de SLOTS con selector, no con modelos. Ejemplo: celda IM_BILENTE = slot reviewer (backend opencode, family no claude, cuenta X) + slot builder_child (backend codex, cuenta Y, via delegate_task). Cambiar de modelo = editar el selector o su lista de preferencia con fallback; ARRANQUE, latido y briefs citan solo el NOMBRE de la celda.
D2 PANELES (lens_panels): cada panel = lista de slots con selector por atributos del registro (channel agent o api, fs si/no, family, lab, tier, cuenta) y cantidad. Ejemplo: PANEL_TICKET = 1 lente fs de familia distinta a la del builder + 1 lente solo texto de otra familia + 1 lente de otro lab. Cambiar de lentes = editar el panel o pasar --panel otro.
D3 POLITICA DE INDEPENDENCIA (una regla): ninguna lente comparte family con el builder del ticket; al menos una comparte lab distinto; cambiar de cuenta, backend o version no cuenta. Si no hay candidata, la ronda se marca no independiente en el veredicto.
R lens_panel.py (resolvedor, scripts/flight): lee panel + registro + el modelo REAL del builder (de un snapshot de t3_thread_configuration o del argumento) y emite el plan: lista de (profile, backend_key, variables de entorno de cuenta, tipo de bundle) y el script de lanzamiento. Los scripts de lanzamiento de rondas dejan de escribirse a mano: se generan. Los bundles (agent con ficheros, agent con material copiado, solo texto) los decide el atributo channel/fs de la clave.
## 3. Que cambia en el dia a dia
- Cambiar una lente: editar una linea del panel (o su selector). Cambiar la cuenta de un proveedor: una linea en la tabla de cuentas. Cambiar la celda del IM: editar la celda. Nada de eso toca prompts, ARRANQUE ni scripts.
- ARRANQUE y briefs: una frase con el nombre de la celda y del panel; el contenido sale del canon (render, como render_latido).
## 4. Cableado
rotate_coordinator rechaza un relevo cuyo ARRANQUE no cita la celda y el panel vigentes; registry_ops alta de un IM guarda celda y slots resueltos; la supervisora compara hilos reales (t3_thread_configuration) con la celda (script sobre snapshot).
## 5. Riesgos y limites
- Un selector demasiado flexible esconde cambios: el plan resuelto se imprime y se guarda en el ledger del vuelo con su hash.
- family y lab estan en el registro pero hay que revisarlos (BA253 claude y BA254 codex tienen family igual al backend, no al modelo).
- Alcance minimo propuesto: D3 + R + D2 para lentes primero (el dolor de hoy); D1 despues de que el usuario decida U1.
## 6. Pendiente
Ratificar este diseno, decidir U1/U3, abrir ficha (DISENO_PRIMERO) y despues implantacion con IM segun la celda decidida.
