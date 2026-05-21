@echo off
setlocal

cd /d "%~dp0"

echo Iniciando validacion de la plantilla Orquestacion Agentes...
echo ------------------------------------------------------------

echo.
echo Ejecutando: 1. Validar configuracion del controlador
echo ^> python .agent/agent_controller.py --validate --json --force
python .agent/agent_controller.py --validate --json --force
if %errorlevel% neq 0 (
    echo [FAIL] 1. Validar configuracion del controlador
    goto :fail
)
echo [OK] 1. Validar configuracion del controlador

echo.
echo Ejecutando: 2. Comprobar estado base del agente
echo ^> python .agent/agent_controller.py --json --force
python .agent/agent_controller.py --json --force
if %errorlevel% neq 0 (
    echo [FAIL] 2. Comprobar estado base del agente
    goto :fail
)
echo [OK] 2. Comprobar estado base del agente

echo.
echo Ejecutando: 3. Validar runtime temporal de tests (Windows-safe)
echo ^> python scripts/run_pytest_safe.py tests/unit/test_windows_safe_temp_runtime.py -q -p no:cacheprovider
python scripts/run_pytest_safe.py tests/unit/test_windows_safe_temp_runtime.py -q -p no:cacheprovider
if %errorlevel% neq 0 (
    echo [FAIL] 3. Validar runtime temporal de tests (Windows-safe)
    goto :fail
)
echo [OK] 3. Validar runtime temporal de tests (Windows-safe)

echo.
echo Ejecutando: 4. Ejecutar lint minimo del nucleo
echo ^> ruff check .agent/hooks/guard_paths.py tests
ruff check .agent/hooks/guard_paths.py tests
if %errorlevel% neq 0 (
    echo [FAIL] 4. Ejecutar lint minimo del nucleo
    goto :fail
)
echo [OK] 4. Ejecutar lint minimo del nucleo

echo.
echo ------------------------------------------------------------
echo RESUMEN: [OK] Validacion de plantilla completada con exito.
echo El proyecto esta listo para usarse.
exit /b 0

:fail
echo.
echo ------------------------------------------------------------
echo RESUMEN: [FAIL] La validacion fallo en el paso anterior.
echo Por favor, revisa la salida para corregir el problema.
exit /b 1
