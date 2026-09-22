@echo off
setlocal
set "PROYECTO=C:\Users\jonathan.marquina\Documents\Jonathan Marquina\proyectos\servicio_documentos"
set "MODO_SOLICITADO=%~1"

if "%MODO_SOLICITADO%"=="" goto :uso
if /I "%MODO_SOLICITADO%"=="PRUEBA" goto :cargar_prueba
if /I "%MODO_SOLICITADO%"=="PRODUCCION" goto :cargar_produccion
goto :uso

:cargar_prueba
set "CONN_SPRING_PRODUCCION="
set "BD_SPRING_PRODUCCION="
set "RUTA_RAIZ_PRODUCCION="
call "%PROYECTO%\config_modo.bat"
if /I not "%MODO_SERVICIO%"=="PRUEBA" (
    echo [BLOQUEADO] config_modo.bat no declara MODO_SERVICIO=PRUEBA.
    exit /b 2
)
if /I not "%BD_SPRING_PRUEBA%"=="HASS_SPRING_PRUEBA" (
    echo [BLOQUEADO] La base de prueba no es HASS_SPRING_PRUEBA.
    exit /b 2
)
if /I not "%RUTA_RAIZ_PRUEBA%"=="\\172.16.20.24\SpringGestionDoc\PRUEBAS" (
    echo [BLOQUEADO] La raiz compartida de prueba no coincide con la autorizada.
    exit /b 2
)
if /I "%TIPO_COPIA_PRUEBA%"=="LOCAL" goto :iniciar_prueba
if /I "%TIPO_COPIA_PRUEBA%"=="COMPARTIDA" goto :iniciar_prueba
echo [BLOQUEADO] TIPO_COPIA_PRUEBA debe ser LOCAL o COMPARTIDA.
exit /b 2

:iniciar_prueba
call :validar_credenciales
if errorlevel 1 exit /b 1
set "CONN_MS_HASS=DRIVER={ODBC Driver 17 for SQL Server};SERVER=%SERVIDOR_MS_HASS%;DATABASE=%BD_MS_HASS%;UID=%SQL_USER%;PWD=%SQL_PASSWORD%;"
set "CONN_SPRING_PRUEBA=DRIVER={ODBC Driver 17 for SQL Server};SERVER=%SERVIDOR_SPRING%;DATABASE=%BD_SPRING_PRUEBA%;UID=%SQL_USER%;PWD=%SQL_PASSWORD%;"
set "ENTORNO_VALIDADO=PRUEBA"
echo [MODO] PRUEBA
echo [BASE PORTAL] %BD_MS_HASS%
echo [BASE SPRING] %BD_SPRING_PRUEBA%
echo [COPIA] %TIPO_COPIA_PRUEBA%
if /I "%TIPO_COPIA_PRUEBA%"=="LOCAL" echo [RUTA] %RUTA_PRUEBA_LOCAL%
if /I "%TIPO_COPIA_PRUEBA%"=="COMPARTIDA" echo [RUTA] %RUTA_RAIZ_PRUEBA%
call "%PROYECTO%\ejecutar_prueba.bat"
exit /b %ERRORLEVEL%

:cargar_produccion
set "CONFIG_PRODUCCION=%PROYECTO%\config.env"
if not exist "%CONFIG_PRODUCCION%" (
    echo [BLOQUEADO] No existe config.env de produccion.
    exit /b 2
)
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%CONFIG_PRODUCCION%") do set "%%A=%%B"
if /I not "%MODO_SERVICIO%"=="PRODUCCION" (
    echo [BLOQUEADO] config.env no declara MODO_SERVICIO=PRODUCCION.
    exit /b 2
)
if /I not "%HABILITAR_PRODUCCION%"=="SI_PRODUCCION" (
    echo [BLOQUEADO] Produccion no esta habilitada.
    exit /b 2
)
if /I not "%BD_SPRING_PRODUCCION%"=="HP_SPRING_PRD" (
    echo [BLOQUEADO] La base de produccion no es HP_SPRING_PRD.
    exit /b 2
)
if /I not "%RUTA_RAIZ_PRODUCCION%"=="\\172.16.20.24\SpringGestionDoc\PROD" (
    echo [BLOQUEADO] La raiz de produccion no coincide con la autorizada.
    exit /b 2
)
call :validar_credenciales
if errorlevel 1 exit /b 1
set "CONN_MS_HASS=DRIVER={ODBC Driver 17 for SQL Server};SERVER=%SERVIDOR_MS_HASS%;DATABASE=%BD_MS_HASS%;UID=%SQL_USER%;PWD=%SQL_PASSWORD%;"
set "CONN_SPRING_PRODUCCION=DRIVER={ODBC Driver 17 for SQL Server};SERVER=%SERVIDOR_SPRING%;DATABASE=%BD_SPRING_PRODUCCION%;UID=%SQL_USER%;PWD=%SQL_PASSWORD%;"
set "ENTORNO_VALIDADO=PRODUCCION"
echo [MODO] PRODUCCION
echo [BASE PORTAL] %BD_MS_HASS%
echo [BASE SPRING] %BD_SPRING_PRODUCCION%
echo [RUTA] %RUTA_RAIZ_PRODUCCION%
call "%PROYECTO%\ejecutar_produccion.bat"
exit /b %ERRORLEVEL%

:validar_credenciales
if "%SQL_USER%"=="" (
    echo [ERROR] Falta SQL_USER en la configuracion.
    exit /b 1
)
if "%SQL_PASSWORD%"=="" (
    echo [ERROR] Falta la variable protegida SQL_PASSWORD de Windows.
    exit /b 1
)
exit /b 0

:uso
echo [ERROR] Debe indicar el ambiente explicitamente.
echo Uso: iniciar_servicio.bat PRUEBA
echo Uso: iniciar_servicio.bat PRODUCCION
exit /b 1
