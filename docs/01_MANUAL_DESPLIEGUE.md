# Manual de despliegue en el servidor

Servicio de migración de adjuntos del portal de proveedores hacia Spring Gestión Documental.

## 1. Componentes

| Componente | Archivo | Dónde corre |
|---|---|---|
| Servicio de migración (prueba) | `migrar_prueba.exe` | Servidor, tarea programada cada 2 h |
| Servicio de migración (producción) | `migrar_produccion.exe` | Servidor, tarea programada (tras aprobación) |
| Iniciador del servicio | `iniciar_servicio_sin_python.bat` | Servidor |
| Config prueba | `config_modo.bat` | Servidor |
| Config producción | `config.env` | Servidor |
| Dashboard web | `frontend/` (Flask + waitress + IIS) | Servidor o PC de soporte |

## 2. Prerequisitos del servidor

1. **ODBC Driver 17 for SQL Server** instalado.
2. **Usuario SQL** `usr_migracion_adjuntos` creado con `crear_usuario_migracion.sql` (SELECT en tablas fuente; SELECT/INSERT/UPDATE en tablas de control; SELECT en `AP_Documentos`; SELECT/INSERT en `GD_Grupo` y `GD_Archivo` — en `HASS_SPRING_PRUEBA` y luego `HP_SPRING_PRD`).
3. **Variable de entorno `SQL_PASSWORD`** configurada a nivel usuario del servidor (la cuenta que ejecutará la tarea). Nunca se guarda en archivos.
4. **Permisos de red**: la cuenta de Windows de la tarea necesita escritura sobre `\\172.16.20.24\SpringGestionDoc\PRUEBAS` (y `...\PROD` solo cuando se apruebe producción). El usuario SQL no concede permisos del recurso compartido.
5. Carpeta de despliegue: `C:\Servicios\servicio_documentos`.
6. **Solo para el dashboard**: Python 3.x + `pip install -r requirements.txt` (pyodbc, Flask, waitress).

## 3. Compilar los ejecutables

En la máquina de desarrollo:

```bat
build_servicio.bat
```

Genera `dist\migrar_prueba.exe` y `dist\migrar_produccion.exe` con PyInstaller. El servidor no necesita Python para el servicio.

> Cada cambio en `migrar_adjuntos_spring_prueba.py` o `migrar_adjuntos_spring.py` requiere recompilar antes de desplegar.

## 4. Copiar archivos al servidor

A `C:\Servicios\servicio_documentos`:

```
dist\migrar_prueba.exe
dist\migrar_produccion.exe
iniciar_servicio_sin_python.bat
config_modo.bat
config.env
frontend\            (carpeta completa, solo si el dashboard va en el servidor)
docs\                (opcional)
```

Verificar que `iniciar_servicio_sin_python.bat` tenga `PROYECTO=C:\Servicios\servicio_documentos` (ya viene así).

## 5. Configuración

### `config_modo.bat` (PRUEBA)

```bat
set "MODO_SERVICIO=PRUEBA"
set "TIPO_COPIA_PRUEBA=COMPARTIDA"
set "MODO_PRUEBA=ESCRITURA"
set "BATCH_PRUEBA=20"
set "BATCH_AP_DOCUMENTO_PRUEBA=500"
set "SQL_USER=usr_migracion_adjuntos"
set "SERVIDOR_MS_HASS=172.16.20.25"
set "BD_MS_HASS=MS_HASS_PROVEEDOR"
set "SERVIDOR_SPRING=172.16.20.24"
set "TABLA_ADJUNTOS=MS_Archivo"
set "USUARIO_MIGRACION=MIGRACION"
set "BD_SPRING_PRUEBA=HASS_SPRING_PRUEBA"
set "RUTA_PRUEBA_LOCAL=<ruta local opcional>"
set "RUTA_RAIZ_PRUEBA=\\172.16.20.24\SpringGestionDoc\PRUEBAS"
```

### `config.env` (PRODUCCION — permanece bloqueada)

```
MODO_SERVICIO=PRODUCCION
HABILITAR_PRODUCCION=NO
SERVIDOR_MS_HASS=172.16.20.25
BD_MS_HASS=MS_HASS_PROVEEDOR
SERVIDOR_SPRING=172.16.20.24
BD_SPRING_PRODUCCION=HP_SPRING_PRD
RUTA_RAIZ_PRODUCCION=\\172.16.20.24\SpringGestionDoc\PROD
SQL_USER=usr_migracion_adjuntos
```

`HABILITAR_PRODUCCION` solo cambia a `SI_PRODUCCION` tras la aprobación formal.

## 6. Tablas de configuración del dashboard

En `MS_HASS_PROVEEDOR` (una sola vez, con cuenta admin):

```sql
-- ejecutar frontend\crear_tablas_entornos.sql
```

Crea `Entornos_Migracion`, `Config_Activo` y `Auditoria_Cambio_Entorno`. Luego, desde una consola con `SQL_PASSWORD` cargada:

```bat
cd frontend
python inicializar_bd_config.py
```

Carga los presets PRUEBA y PRODUCCION (esta última con `ProduccionHabilitado=0`).

## 7. Tarea programada (cada 2 horas)

En PowerShell del servidor (como administrador), desde la carpeta del proyecto:

```powershell
powershell -ExecutionPolicy Bypass -File crear_tarea.ps1 -Modo PRUEBA
```

Registra `MigrarAdjuntosPortalProveedores` ejecutando `iniciar_servicio_sin_python.bat PRUEBA` cada 2 horas. Para que corra sin sesión iniciada:

```powershell
powershell -ExecutionPolicy Bypass -File actualizar_tarea_run_anytime.ps1
```

(solicita usuario y contraseña de Windows).

Para cambiar entre PRUEBA/PRODUCCION más adelante:

```powershell
powershell -ExecutionPolicy Bypass -File cambiar_modo_tarea.ps1 -Modo PRUEBA -TipoPrueba COMPARTIDA
powershell -ExecutionPolicy Bypass -File cambiar_modo_tarea.ps1 -Modo PRODUCCION
```

## 8. Dashboard web

### Opción A — consola (soporte/pruebas)

```bat
frontend\iniciar_dashboard.bat
```

Abre `http://127.0.0.1:5000`. Requiere `SQL_PASSWORD` en el entorno de la consola.

### Opción B — IIS (servidor)

`frontend\web.config` ya trae `httpPlatformHandler` apuntando a `server.py` (waitress):

1. Instalar Python en el servidor y `pip install -r requirements.txt`.
2. Ajustar `processPath` en `web.config` si el exe de Python está en otra ruta.
3. Crear el sitio/aplicación en IIS apuntando a `frontend\`.
4. Configurar la variable de entorno `SQL_PASSWORD` para la identidad del Application Pool.
5. Asegurarse de que la identidad del pool tenga acceso de lectura a `config_modo.bat` y escritura solo si se usará el cambio de entorno desde la web.

## 9. Verificación post-despliegue

1. Ejecutar la tarea manualmente desde el Programador de tareas o:
   ```bat
   iniciar_servicio_sin_python.bat PRUEBA
   ```
2. Revisar `migrar_adjuntos_spring_prueba.log` — debe mostrar `INICIO DE PRUEBA`, procesamiento y `RESUMEN` sin `[FALLIDO]`.
3. En el dashboard: pestaña Dashboard muestra contadores; pestaña Archivos lista los traslados con su columna OC/OS.
4. Confirmar en el UNC `\\172.16.20.24\SpringGestionDoc\PRUEBAS` que se crean carpetas con la jerarquía `Empresa > Expediente > Orden > Año > Mes > Número`.

## 10. Nuevo stack Angular + API .NET 8 (IIS)

Proyectos:

- `api_migracion_documentos` — API .NET 8 (misma máquina que el servicio; lanza el exe/bat y lee log/config).
- `migracion_documentos` — frontend Angular 20 (hash routing, sin URL Rewrite).

### 10.1 Publicar

```bat
cd api_migracion_documentos
dotnet publish -c Release -o publish
cd ..\migracion_documentos
ng build --configuration production
xcopy /E /I /Y dist\migracion_documentos\browser\* ..\api_migracion_documentos\publish\wwwroot\
```

La API sirve el frontend desde `wwwroot` en el mismo sitio (`UseStaticFiles` + fallback a `index.html`), así `environment.prod.ts` usa la ruta relativa `/api/migracion-documentos` sin configurar hostname.

### 10.2 IIS

1. Instalar **.NET 8 Hosting Bundle** en el servidor.
2. Crear sitio/aplicación IIS apuntando a `api_migracion_documentos\publish`.
3. Application Pool: **No Managed Code**, identidad con:
   - Lectura/escritura de `config_modo.bat`, `config.env` y el log del servicio.
   - Permiso para ejecutar `iniciar_servicio_sin_python.bat` / `migrar_prueba.exe`.
   - Variable de entorno `SQL_PASSWORD` (o cadena en `appsettings.json` con la clave SQL).
4. Verificar `http://<servicio>/` (SPA) y `POST /api/migracion-documentos/stats`.

### 10.3 Permisos SQL pendientes (DBA)

- `Scripts\01_sp_ms_hass.sql` ya ejecutado en `MS_HASS_PROVEEDOR` con `GRANT EXECUTE` a `usr_migracion_adjuntos`.
- `Scripts\02_sp_spring.sql` **pendiente**: `usr_migracion_adjuntos` solo tiene `SELECT` en `HASS_SPRING_PRUEBA`. La API funciona hoy con fallback de consultas directas; al ejecutar el script + `GRANT EXECUTE` usará los SPs automáticamente. Repetir en `HP_SPRING_PRD` al pasar a producción.

### 10.4 Coexistencia con Flask

El dashboard Flask (puerto 5000 / sitio `frontend\` en IIS) sigue operativo durante la validación. El nuevo sitio Angular/API no comparte estado con él: ambos leen las mismas tablas y el mismo log. Evitar lanzar migraciones desde ambos a la vez (el servicio no tiene bloqueo de concurrencia).
