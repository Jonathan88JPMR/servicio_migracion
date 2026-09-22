@echo off
setlocal

if /I not "%ENTORNO_VALIDADO%"=="PRODUCCION" (
    echo [BLOQUEADO] Use iniciar_servicio.bat PRODUCCION.
    exit /b 2
)

echo ============================================================
echo  MODO PRODUCCION - MIGRACION DE ADJUNTOS
echo ============================================================
echo.
echo Este batch ejecuta el script de PRODUCCION.
echo * Actualiza MS_ArchivoTraslado
 echo * Inserta en GD_Grupo y GD_Archivo
 echo * Copia archivos a la ruta UNC PROD
 echo.

if /I not "%HABILITAR_PRODUCCION%"=="SI_PRODUCCION" (
    echo [BLOQUEADO] Produccion no esta habilitada.
    exit /b 2
)
if /I not "%RUTA_RAIZ_PRODUCCION%"=="\\172.16.20.24\SpringGestionDoc\PROD" (
    echo [BLOQUEADO] La raiz de produccion no coincide con la ruta autorizada.
    exit /b 2
)
if "%CONN_SPRING_PRODUCCION%"=="" (
    echo [BLOQUEADO] Falta CONN_SPRING_PRODUCCION.
    exit /b 2
)

REM Ruta del proyecto
set PROYECTO=C:\Users\jonathan.marquina\Documents\Jonathan Marquina\proyectos\servicio_documentos

REM Ruta de Python
set PYTHON=C:\Users\jonathan.marquina\AppData\Local\Programs\Python\Python314\python.exe

echo Ejecutando script de produccion...
echo.

"%PYTHON%" "%PROYECTO%\migrar_adjuntos_spring.py"

set EXIT_CODE=%ERRORLEVEL%

echo.
echo ============================================================
if %EXIT_CODE% equ 0 (
    echo [OK] Migracion de produccion finalizada.
) else (
    echo [ERROR] La migracion de produccion finalizo con errores. Codigo: %EXIT_CODE%
)
echo Log de produccion: %PROYECTO%\migrar_adjuntos_spring.log
echo ============================================================

endlocal & exit /b %EXIT_CODE%
