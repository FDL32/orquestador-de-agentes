# Exit-code pipe false-negative

Caso medido (2026-08-08): un gate se reporto como defectuoso ("devuelve rc=0 con
violaciones") por leer `$?` tras `| tail`; su `main()` hacia `return 1`
correctamente. El defecto era del probe, no del gate. Un rc leido mal es un
hallazgo FALSO con formato de evidencia: cumple `command:` + `exit_code:` y aun
asi miente.
