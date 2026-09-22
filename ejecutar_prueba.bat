@echo off
setlocal

if /I not "%ENTORNO_VALIDADO%"=="PRUEBA" (
    echo [BLOQUEADO] Use iniciar_servicio.bat PRUEBA.
    exit /b 2
)

echo ============================================================
echo  MODO PRUEBA - MIGRACION DE ADJUNTOS
echo ============================================================
echo.
echo Este batch ejecuta el script de PRUEBAS.
echo * Copia segun TIPO_COPIA_PRUEBA: LOCAL o COMPARTIDA
echo * Con MODO_PRUEBA=ESCRITURA escribe en MS_ArchivoTraslado y GD_Archivo (HASS_SPRING_PRUEBA)
echo * Con MODO_PRUEBA=SIMULACION no escribe en bases
echo.

REM Ruta del proyecto
set PROYECTO=C:\Users\jonathan.marquina\Documents\Jonathan Marquina\proyectos\servicio_documentos

REM Ruta de Python
set PYTHON=C:\Users\jonathan.marquina\AppData\Local\Programs\Python\Python314\python.exe

if "%CONN_MS_HASS%"=="" (
    echo [ERROR] No esta configurada CONN_MS_HASS para el usuario SQL.
    echo Inicia mediante iniciar_servicio.bat y verifica SQL_USER/SQL_PASSWORD.
    exit /b 1
)
if "%CONN_SPRING_PRUEBA%"=="" (
    echo [ERROR] No esta configurada CONN_SPRING_PRUEBA para HASS_SPRING_PRUEBA.
    exit /b 1
)
echo.
echo Ejecutando script de prueba...
echo.

"%PYTHON%" "%PROYECTO%\migrar_adjuntos_spring_prueba.py"

set EXIT_CODE=%ERRORLEVEL%

echo.
echo ============================================================
if %EXIT_CODE% equ 0 (
    echo [OK] Prueba finalizada. Revisa el log y las carpetas creadas.
) else (
    echo [ERROR] La prueba finalizo con errores. Codigo: %EXIT_CODE%
)
echo Log de prueba: %PROYECTO%\migrar_adjuntos_spring_prueba.log
if /I "%TIPO_COPIA_PRUEBA%"=="LOCAL" echo Carpeta de pruebas: %RUTA_PRUEBA_LOCAL%
if /I "%TIPO_COPIA_PRUEBA%"=="COMPARTIDA" echo Carpeta de pruebas: %RUTA_RAIZ_PRUEBA%
echo ============================================================

endlocal & exit /b %EXIT_CODE%

