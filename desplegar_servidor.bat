@echo off
setlocal

REM ============================================================
REM Copia el servicio compilado al servidor.
REM Uso:
REM   desplegar_servidor.bat \\SERVIDOR\C$\Servicios\servicio_documentos
REM Ejemplo:
REM   desplegar_servidor.bat \\172.16.20.3\c$\servicios\servicio_documentos
REM
REM No sobrescribe config_modo.bat / config.env si ya existen en
REM el destino (la configuracion del servidor manda).
REM ============================================================

set "DESTINO=%~1"
if "%DESTINO%"=="" (
    echo [ERROR] Indique la carpeta destino en el servidor.
    echo Uso: desplegar_servidor.bat \\SERVIDOR\C$\Servicios\servicio_documentos
    exit /b 1
)

set "ORIGEN=%~dp0"
echo [ORIGEN]  %ORIGEN%
echo [DESTINO] %DESTINO%

if not exist "%ORIGEN%dist\migrar_prueba.exe" (
    echo [ERROR] Falta dist\migrar_prueba.exe. Ejecute primero build_servicio.bat
    exit /b 1
)
if not exist "%ORIGEN%dist\migrar_produccion.exe" (
    echo [ERROR] Falta dist\migrar_produccion.exe. Ejecute primero build_servicio.bat
    exit /b 1
)

if not exist "%DESTINO%" (
    echo [INFO] Creando carpeta destino...
    mkdir "%DESTINO%" || (echo [ERROR] No se pudo crear %DESTINO% & exit /b 1)
)

echo [COPIA] Ejecutables...
copy /Y "%ORIGEN%dist\migrar_prueba.exe" "%DESTINO%\" || exit /b 1
copy /Y "%ORIGEN%dist\migrar_produccion.exe" "%DESTINO%\" || exit /b 1

echo [COPIA] Lanzador y configuracion...
copy /Y "%ORIGEN%iniciar_servicio_sin_python.bat" "%DESTINO%\" || exit /b 1
if exist "%DESTINO%\config_modo.bat" (
    echo [OMITIDO] config_modo.bat ya existe en el servidor (no se sobrescribe)
) else (
    copy /Y "%ORIGEN%config_modo.bat" "%DESTINO%\" || exit /b 1
)
if exist "%DESTINO%\config.env" (
    echo [OMITIDO] config.env ya existe en el servidor (no se sobrescribe)
) else (
    copy /Y "%ORIGEN%config.env" "%DESTINO%\" || exit /b 1
)

echo [COPIA] Scripts de tarea programada...
copy /Y "%ORIGEN%crear_tarea.ps1" "%DESTINO%\" || exit /b 1
copy /Y "%ORIGEN%cambiar_modo_tarea.ps1" "%DESTINO%\" || exit /b 1
copy /Y "%ORIGEN%actualizar_tarea_run_anytime.ps1" "%DESTINO%\" || exit /b 1

echo [VERIFICACION] Archivos en destino:
dir /B "%DESTINO%\*.exe" "%DESTINO%\*.bat" "%DESTINO%\*.ps1" 2>nul

echo ============================================================
echo [OK] Archivos copiados a %DESTINO%
echo.
echo En el servidor falta:
echo   1. ODBC Driver 17 for SQL Server instalado.
echo   2. Variable de entorno SQL_PASSWORD del usuario de la tarea.
echo   3. Registrar la tarea:
echo      powershell -ExecutionPolicy Bypass -File crear_tarea.ps1 -Modo PRUEBA
echo   4. Prueba manual: iniciar_servicio_sin_python.bat PRUEBA
echo ============================================================

endlocal
