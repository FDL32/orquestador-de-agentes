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
