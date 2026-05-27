# Inventario Canonico de Anti-Patrones

Este archivo es la fuente compartida de referencia para Builder y Manager.

## AP-01 - Mock drift
- El patch o mock apunta a un simbolo distinto del que el codigo bajo test realmente llama.
- Efecto: el test puede pasar sin estar verificando el camino real.

## AP-02 - Floor assertion
- El umbral numerico ya queda satisfecho por el baseline sin la feature.
- Efecto: la asercion no prueba nada relevante.

## AP-03 - Zero-logic wrapper
- La funcion solo delega 1:1 sin aportar logica propia.
- Efecto: anade indireccion sin valor.

## AP-04 - Exclusive resource acquisition without reentrancy guard
- Un metodo que adquiere un recurso exclusivo puede ser reentrado desde varios call sites sin guarda de instancia.
- Efecto: el segundo intento falla con el propio proceso vivo y aborta el flujo.

## AP-05 - Return contract drift (None -> bool)
- Un metodo cambia de retorno implicito `None` a `bool`, pero los callers siguen usando truthiness generica.
- Efecto: los mocks y paths legacy producen falsos positivos o falsos negativos.

## AP-06 - Validator evidence missing
- El plan declara un validador, pero el execution log no conserva el comando exacto y la salida limpia.
- Efecto: no hay trazabilidad verificable del gate.

## AP-07 - Scaffolding misclassified as code
- Un ticket que solo crea estructura, placeholders o `.gitkeep` se clasifica como `code`.
- Efecto: se activan gates que no aportan senal y generan ruido.

## AP-08 - Test coverage drift
- El Builder ejecuta el suite existente, ve que pasa, y declara calidad satisfecha, pero las funciones nuevas del diff no tienen ningun test directo.
- Efecto: el suite pasa sin probar el codigo nuevo; los bugs en las funciones nuevas son invisibles.

## AP-09 - Protocol key assumption
- El Builder implementa un handler de protocolo externo usando nombres de clave supuestos en lugar de verificar el contrato real del protocolo.
- Efecto: el handler nunca procesa nada real; funciona como no-op encubierto.

## AP-10 - Test surrogate
- Los tests de integracion crean un script o clase sintetica que imita el comportamiento del codigo bajo test y validan ese sustituto en lugar del modulo real.
- Efecto: los tests pasan mientras el codigo real tiene bugs criticos no detectados.

## AP-11 - Security gate fail-open on config error
- Un componente de seguridad o guarda retorna "allow" cuando encuentra configuracion invalida, desconocida o parcialmente migrada, en lugar de bloquear.
- Efecto: la corrupcion de config silencia la proteccion en lugar de activarla.

## AP-12 - Review packet incomplete (untracked deliverables invisible to diff)
- El review packet se construye solo a partir de `git diff` y oculta archivos nuevos no rastreados, por lo que el Manager revisa un alcance incompleto.
- Efecto: se producen falsos positivos de scope o revisiones incompletas aunque el trabajo real exista en disco.
