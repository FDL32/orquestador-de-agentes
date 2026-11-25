# T3: lanzamiento de hilos de vuelo (referencia bajo demanda)

## Procedimiento

Para un hilo de vuelo con worktree propio, no uses
`workspaceStrategy: worktree`. Crea primero el worktree desde `repo_motor`,
sobre un SHA base explicito:

    git worktree add -b <rama> <ruta> <sha-base>

Lanza despues el hilo con `workspaceStrategy: existing_worktree`, indicando la
ruta y la rama ya creadas.

Declara siempre la seleccion como `modelSelection: {instanceId, model}`. No
pases proveedor o modelo como parametros sueltos. Tras el lanzamiento,
confirma la seleccion efectiva con `t3_thread_configuration`.

Comprueba tambien con `t3_thread_read` que `worktreePath` no sea nulo y que el
estado sea distinto de `failed`.

Si el lanzamiento falla, deja asentado el hilo failed, conserva la evidencia y usa
el siguiente codigo de sesion; no reutilices el codigo ni reintentes sobre ese
hilo. Da de alta cada hilo en el registry con `registry_ops.py alta --apply`
y `--roster` antes de continuar el vuelo.
