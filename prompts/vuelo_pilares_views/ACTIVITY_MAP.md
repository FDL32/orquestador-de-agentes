<!-- ACTIVITY_MAP_GENERATOR: scripts/flight/check_pilares_views_fresh.py -->
<!-- ACTIVITY_UNIVERSE: mode=git ls-files; files=185 -->
<!-- ACTIVITY_SOURCE_SHA256: one hash per file containing an anchor -->
<!-- SOURCE_SHA256: .agent/rules/common/arranque_coordinadora_agnostica.md e284caae2028b2c41ec2c1121fd8ca87b42a2f68eb8f4a6a9163e9632380797e -->
<!-- SOURCE_SHA256: .agent/rules/common/espera_trabajo_paralelo.md e881874c9393781173697b091cd38e677b74ecb3150d27026c779bd11a0bf54c -->
<!-- la etiqueta la declara el ancla; la semantica no se comprueba -->

| id | nombre | dueno resuelto | estado | deuda |
|---|---|---|---|---|
| A-01 | derivar el latido | .agent/rules/common/arranque_coordinadora_agnostica.md:21 | TIPIFICADA | ninguna |
| A-02 | programar y deshabilitar el latido | ninguno | NO_TIPIFICADA | pendiente |
| A-03 | paquete de relevo ARRANQUE + HANDOFF | prompts/vuelo_pilares_templates/ARRANQUE_PLANTILLA.md:1 | TIPIFICADA | ninguna |
| A-04 | fases A/B, ACK y roster | docs/protocol/flight_supervision.md:93 | TIPIFICADA | ninguna |
| A-05 | traspaso R6 | ninguno | NO_TIPIFICADA | pendiente |
| A-06 | asiento, alta y nota en registry | .agent/rules/common/t3_lanzamiento_hilos_vuelo.md:3 | PARCIAL | pendiente |
| A-07 | settle P24 | prompts/t3_role_session_relief.md:523 | PARCIAL | pendiente |
| A-08 | lanzar un IM | .agent/rules/common/t3_lanzamiento_hilos_vuelo.md:3 | PARCIAL | pendiente |
| A-09 | lanzar un TR | .agent/rules/common/t3_lanzamiento_hilos_vuelo.md:3 | PARCIAL | pendiente |
| A-10 | brief IM desde el borrador de un TR | ninguno | NO_TIPIFICADA | pendiente |
| A-11 | verificar LISTO / LISTO_PARA_INTEGRAR | prompts/t3_role_session_relief.md:497 | PARCIAL | pendiente |
| A-12 | integrar un IM y verificar | .agent/rules/common/espera_trabajo_paralelo.md:84 | PARCIAL | pendiente |
| A-13 | alta de backlog con recibo | prompts/backlog_admit.md:88 | TIPIFICADA | ninguna |
| A-14 | archivar fila y enmendar ficha | ninguno | NO_TIPIFICADA | pendiente |
| A-15 | bucle de lentes P34, cierre, V1 | prompts/ensemble_loop.md:40 | PARCIAL | pendiente |
| A-16 | cupo y cambio de cuenta D5 | docs/protocol/ciclo_cuentas_madre_hija.md:3 | PARCIAL | pendiente |
| A-17 | vigilancia de hilos huerfanos | ninguno | NO_TIPIFICADA | pendiente |
| A-18 | ctx_acumulado y marcado del objetivo | .agent/rules/common/espera_trabajo_paralelo.md:124 | PARCIAL | pendiente |
| A-19 | GO de relevo | .agent/rules/common/avisos_parada_vuelo.md:223 | TIPIFICADA | ninguna |
| A-20 | mensajeria entre sesiones | docs/protocol/flight_supervision.md:375 | TIPIFICADA | ninguna |
| A-21 | push, suite y congelacion | ninguno | NO_TIPIFICADA | pendiente |
| A-22 | retirada de disco P7 | docs/protocol/rotacion_disco_vuelo.md:72 | TIPIFICADA | ninguna |
| A-23 | tick_trace, stall y post_relevo | prompts/vuelo_pilares_templates/LATIDO_PLANTILLA.md:53 | TIPIFICADA | ninguna |
