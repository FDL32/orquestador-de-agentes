@echo off
REM ====================================================================
REM == LANZADOR EXTERNO - MI_PROYECTO
REM ====================================================================
REM Este script puede ejecutarse desde cualquier carpeta
REM Proyecto CLI: La consola permanece abierta

REM --- Configuración automática ---
set "PROJECT_PATH=%~dp0"
set "SCRIPT_TO_RUN=%PROJECT_PATH%\src\main.py"

echo.
echo [INFO] Iniciando MI_PROYECTO...
echo [INFO] Carpeta del proyecto: %PROJECT_PATH%
echo.

REM Verificar si el script existe
if not exist "%SCRIPT_TO_RUN%" (
    echo [ERROR] No se encuentra el script principal: %SCRIPT_TO_RUN%
    echo [ERROR] Asegurate que el proyecto este en la ruta correcta
    pause
    exit /b 1
)

REM Cambiar al directorio del proyecto temporalmente
pushd "%PROJECT_PATH%"

REM --- Verificar e instalar dependencias ---
if exist "pyproject.toml" (
    echo [INFO] Verificando dependencias con uv...
    uv sync >nul 2>&1
    if errorlevel 1 (
        echo [WARNING] uv no esta disponible o fallo. Intentando con pip...
        python -m pip install -e . >nul 2>&1
        if errorlevel 1 (
            echo [ERROR] Error instalando dependencias
            popd
            pause
            exit /b 1
        )
    )
) else if exist "requirements.txt" (
    echo [INFO] Instalando dependencias con pip...
    python -m pip install -r requirements.txt >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Error instalando dependencias
        popd
        pause
        exit /b 1
    )
)

REM --- Lanzar la aplicación como módulo ---
echo [INFO] Ejecutando la aplicación...
echo.

REM Iniciar Python como módulo
python -m src.main
if errorlevel 1 (
    echo.
    echo [ERROR] La aplicación finalizó con errores.
    popd
    pause
    exit /b 1
)

echo.
echo [INFO] Aplicación finalizada correctamente.
popd
pause
exit /b 0
