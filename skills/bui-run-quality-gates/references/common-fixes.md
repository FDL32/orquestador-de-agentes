# Fixes Comunes



## F401: Import no usado



**Solución:** Eliminar o usar `# noqa: F401`



## F841: Variable no usada



**Solución:** Eliminar o renombrar a `_`

```python

_ = calculate()  # Ignorar valor

```



## E501: Línea muy larga



**Solución:** Dividir string o parámetros

```python

long_line = (

    "texto largo "

    "más texto"

)



def funcion(

    param1: str,

    param2: int

) -> None:

    pass

```



## I001: Imports desordenados



**Solución:**

```bash

ruff check . --exclude .agent --fix

```



Orden: `__future__` â†’ stdlib â†’ third-party â†’ local



## E722: Bare except



**Solución:**

```python

try:

    process()

except ValueError as e:  # âœ… Específico

    logger.error(e)

```



## Comando útil



```bash

ruff check . --exclude .agent --fix

```
