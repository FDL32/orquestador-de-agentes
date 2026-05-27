# Inventario Canónico de Anti-Patrones

Este archivo es la fuente compartida de referencia para Builder y Manager.

## AP-01 - Mock drift
- El patch/mocking apunta a un símbolo distinto del que el código realmente llama.
- Efecto: el test puede pasar sin estar verificando el camino real.

## AP-02 - Floor assertion
- El umbral numérico ya queda satisfecho por el baseline sin la feature.
- Efecto: la aserción no prueba nada relevante.

## AP-03 - Zero-logic wrapper
- La función solo delega 1:1 sin aportar lógica propia.
- Efecto: añade indirección sin valor.

## AP-04 - Exclusive resource acquisition without reentrancy guard
- Un método que adquiere un recurso exclusivo puede ser reentrado desde varios call sites sin guarda de instancia.
- Efecto: segundo intento falla con el propio proceso vivo y aborta el flujo.

## AP-05 - Return contract drift (None -> bool)
- Un método cambia de retorno implícito `None` a `bool`, pero los callers siguen usando truthiness genérica.
- Efecto: los mocks y paths legacy producen falsos positivos o falsos negativos.

## AP-06 - Validator evidence missing
- El plan declara un validador, pero el execution log no conserva el comando exacto y la salida limpia.
- Efecto: no hay trazabilidad verificable del gate.

## AP-07 - Scaffolding misclassified as code
- Un ticket que solo crea estructura, placeholders o `.gitkeep` se clasifica como `code`.
- Efecto: se activan gates que no aportan señal y generan ruido.

## AP-08 - Test coverage drift
- El Builder ejecuta el suite existente, ve que pasa, y declara calidad satisfecha — pero las funciones nuevas introducidas en el diff no tienen ningún test directo.
- Efecto: el suite pasa sin probar el código nuevo; los bugs en las funciones nuevas son invisibles.

## AP-09 - Protocol key assumption (implementación contra contrato asumido)
- El Builder implementa un handler de protocolo externo usando nombres de clave supuestos en lugar de verificar el contrato real del protocolo.
- La misma suposición errónea se propaga a los tests, que usan el mismo formato incorrecto — producción y tests se refuerzan mutuamente en el error.
- Efecto: el handler nunca procesa nada real; funciona como no-op encubierto.

## AP-10 - Test surrogate (test que prueba un sustituto, no el código real)
- Los tests de integración crean un script o clase sintética que imita el comportamiento del código bajo test, y validan ese sustituto en lugar del módulo real.
- Efecto: los tests pasan mientras el código real tiene bugs críticos no detectados.

## AP-11 - Security gate fail-open on config error
- Un componente de seguridad o guarda retorna "allow" cuando encuentra configuración inválida, desconocida o parcialmente migrada, en lugar de bloquear.
- Efecto: la corrupción de config silencia la protección en lugar de activarla.
