<!-- Marcadores declarados: {{VUELO_ID}} {{RECEPTOR}} -->

# Paquete de relevo

0. Identifica el vuelo {{VUELO_ID}} y el receptor {{RECEPTOR}}.

1. Consulta el estado firmado vigente en `diseno/ESTADO_RELEVO_VIGENTE.json`.
   El paquete remite a ese estado; la identidad, autoridad, fecha y recibo
   viven allí.

2. Antes de aceptar la autoridad del relevo, el receptor verifica el estado:

   `python scripts/flight/sign_relevo_state.py --verify <ruta>`

3. Continúa solo si la verificación termina correctamente y conserva la ruta
   del estado como referencia del relevo.

Reporte final: receptor, ruta del estado y resultado de la verificación.
