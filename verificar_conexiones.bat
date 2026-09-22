@echo off
setlocal
set "PYTHON=C:\Users\jonathan.marquina\AppData\Local\Programs\Python\Python314\python.exe"
set "PROYECTO=C:\Users\jonathan.marquina\Documents\Jonathan Marquina\proyectos\servicio_documentos"
call "%PROYECTO%\config_modo.bat"

if /I not "%MODO_SERVICIO%"=="PRUEBA" (
    echo [BLOQUEADO] config_modo.bat no esta en PRUEBA.
    exit /b 2
)
if /I not "%BD_SPRING_PRUEBA%"=="HASS_SPRING_PRUEBA" (
    echo [BLOQUEADO] La base de prueba no es HASS_SPRING_PRUEBA.
    exit /b 2
)
if "%SQL_USER%"=="" (
    echo [ERROR] Falta SQL_USER en config_modo.bat.
    exit /b 1
)
if "%SQL_PASSWORD%"=="" (
    echo [ERROR] Falta la variable protegida SQL_PASSWORD de Windows.
    exit /b 1
)

set "CONN_MS_HASS=DRIVER={ODBC Driver 17 for SQL Server};SERVER=%SERVIDOR_MS_HASS%;DATABASE=%BD_MS_HASS%;UID=%SQL_USER%;PWD=%SQL_PASSWORD%;"
set "CONN_SPRING_PRUEBA=DRIVER={ODBC Driver 17 for SQL Server};SERVER=%SERVIDOR_SPRING%;DATABASE=%BD_SPRING_PRUEBA%;UID=%SQL_USER%;PWD=%SQL_PASSWORD%;"

echo ============================================================
echo Verificando MS_HASS_PROVEEDOR y HASS_SPRING_PRUEBA
echo ============================================================
"%PYTHON%" "%PROYECTO%\verificar_conexiones.py"
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% neq 0 (
    echo.
    echo [ERROR] Una o mas conexiones fallaron.
) else (
    echo.
    echo [OK] Todas las conexiones de prueba funcionan.
)

endlocal & exit /b %EXIT_CODE%
