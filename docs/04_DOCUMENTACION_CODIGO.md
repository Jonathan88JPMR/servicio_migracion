# Documentación del código

Cinco piezas: **servicio migrador** (script Python → exe), **API/dashboard legado** (Flask), **frontend legado** (Bootstrap + JS vanilla), **API REST** (`api_migracion_documentos`, .NET 8) y **frontend web** (`migracion_documentos`, Angular 20). Más scripts de soporte (bat/ps1/sql) y el paquete publicado `api_migracion_doc`.

## 1. Servicio migrador — `migrar_adjuntos_spring_prueba.py`

Migración en modo PRUEBA. Escribe en `MS_*Traslado` y `GD_Archivo`/`GD_Grupo` de `HASS_SPRING_PRUEBA` solo si `MODO_PRUEBA=ESCRITURA`; en `SIMULACION` todo es lectura + log.

### Conexiones y resolución de la orden

| Función | Rol |
|---|---|
| `conectar(connection_string)` | pyodbc con timeout 30 s |
| `obtener_ap_documento_por_obligacion(conn, prov, tipo, num)` | `AP_Documentos` por proveedor+obligación → referencia OC/OS, ruta, compañía, fecha |
| `obtener_ap_documento_por_referencia(conn, tipo, num)` | `AP_Documentos` por `ReferenciaTipoDocumento`+número (para `WH_OrdenCompra`/`Compromiso`) |
| `obtener_obligaciones_por_referencia(conn, numero, tipo)` | set de obligaciones `(prov, tipo, num)` ligadas a una OC/OS — base del filtro `SOLO_REFERENCIA` |
| `resolver_oc_os(conn, tabla, id_registro)` | unifica la resolución según origen: `Obligaciones` (Id `prov\|tipo\|num`), `WH_OrdenCompra` (Id = OC), `Compromiso` (Id = OS) |

### Ruta destino

| Función | Rol |
|---|---|
| `descomponer_ruta_spring(ruta_unc)` | valida y extrae los 6 niveles tras `PROD`: Empresa › Expediente › Orden › Año › Mes › Número |
| `plantilla_ruta_por_compania(conn, compania, ref_tipo)` | cachea una `RutaArchivo` de referencia por compañía (y tipo) |
| `construir_ruta_dinamica(conn, compania, tipo, num, fecha)` | arma la jerarquía cuando `RutaArchivo` es nula (OC→"Orden Compra", SO→"Orden Servicio", mes `NN-Nombre` español) |
| `buscar_grupo_ruta(conn, jerarquia)` | recorre `GD_Grupo` por `IdGrupoPadre`+`NivelGrupo`+`Descripcion` (`Estado='A'`) |
| `buscar_o_crear_jerarquia_gd_grupo(conn, jerarquia, usuario)` | reutiliza niveles existentes y crea los que falten; devuelve `IdGrupo` hoja (nivel 6) |
| `construir_destino_prueba(ruta, jerarquia, nombre, tipo_copia)` | arma la ruta final; en COMPARTIDA bloquea destinos fuera de `...\PRUEBAS` o que contengan `PROD` |
| `guardar_archivo_prueba(destino, contenido)` | crea carpetas, escribe y verifica tamaño; idéntico → omite; mismo nombre distinto → `_generar_nombre_unico` (`_001`…) |

### Control y registro

| Función | Rol |
|---|---|
| `upsert_control_inicio` / `upsert_control_inicio_ap` | MERGE a `PROCESANDO`, `Intentos+1` |
| `actualizar_control` / `actualizar_control_ap` | UPDATE estado/etapa/mensaje/ruta/`IdGrupo`/`ArchivoId`; `FechaTraslado` solo si COMPLETADO |
| `insertar_gd_archivo_prueba(conn, id_grupo, codigo, ruta, nombre, usuario)` | `ArchivoId = MAX+1` con `TABLOCKX`; `ValorTexto1='PENDIENTE_DEFINIR'`, `Descripcion='MIGRACION_PRUEBA'` |

### Orquestación

- `migrar_prueba(..., solo=None)` — fuente `MS_Archivo`. Etapas por archivo: `INICIO → RESOLVER_AP_DOCUMENTOS → VALIDAR_RUTA|CONSTRUIR_RUTA_DINAMICA → BUSCAR_GD_GRUPO → CONSTRUIR_RUTA_PRUEBA → COPIAR_PRUEBA → VALIDAR_DUPLICADO → INSERTAR_GD_ARCHIVO` (o `SIMULAR_*`). Candidatos: `Contenido IS NOT NULL` y sin traslado `COMPLETADO`.
- `migrar_ap_documento_archivo_prueba(..., solo_obligaciones=None)` — fuente `MS_AP_DocumentoArchivo` (`Gadatos IS NOT NULL`); resolución directa por obligación; `Codigo = Gatipo`.
- `VALIDAR_DUPLICADO`: si `GD_Archivo` ya tiene `(IdGrupo, RutaArchivo)` → marca COMPLETADO sin duplicar.
- Ante excepción: rollback de ambas conexiones y `ERROR` con etapa y mensaje.

### Variables de entorno del servicio

| Variable | Uso |
|---|---|
| `CONN_MS_HASS`, `CONN_SPRING_PRUEBA`, `CONN_SPRING_PRODUCCION` | cadenas ODBC completas (las arma el .bat) |
| `TABLA_ADJUNTOS` | tabla origen MS (default `MS_Archivo`) |
| `EMPRESA_GD_GRUPO` | nombre empresa por defecto (la real sale de `AP_Documentos.RutaArchivo`) |
| `USUARIO_MIGRACION` | `UltimoUsuario` en inserciones (default `MIGRACION`) |
| `TIPO_COPIA_PRUEBA` | `LOCAL` (a `RUTA_PRUEBA_LOCAL`) o `COMPARTIDA` (a `RUTA_RAIZ_PRUEBA`) |
| `MODO_PRUEBA` | `SIMULACION` o `ESCRITURA` |
| `BATCH_PRUEBA`, `BATCH_AP_DOCUMENTO_PRUEBA` | tamaño de lote por corrida |
| `SOLO_REFERENCIA`, `SOLO_REFERENCIA_TIPO` | filtro por OC/OS para ejecución personalizada (los inyecta el dashboard) |

`migrar_adjuntos_spring.py` es la versión de producción (mismo esqueleto; pendiente de alinear con control/campos reales antes del pase).

## 2. API — `frontend/app.py` (Flask)

Config: parsea `config_modo.bat` (`parse_config_modo`) y `config.env`; la config activa vive en `Entornos_Migracion` + `Config_Activo` (`get_activo_cfg`). `connect_ms`/`connect_spring` arman conexiones ODBC con `SQL_USER` + `SQL_PASSWORD` (env, nunca expuesta).

### Endpoints

| Método / ruta | Qué hace |
|---|---|
| `GET /` | index.html |
| `GET /api/entornos` | lista `Entornos_Migracion` activos + entorno actual |
| `POST /api/cambiar-entorno` `{entorno}` | valida `ProduccionHabilitado`, actualiza `Config_Activo`, regenera archivos (`_regenerar_archivos`) y audita (`Auditoria_Cambio_Entorno`) |
| `GET /api/config` | config del entorno activo + lista de entornos |
| `POST /api/config` `{k:v}` | valida (`validate_config`), persiste en `Entornos_Migracion`, regenera archivos |
| `GET /api/stats` | contadores AP/MS por estado y GATipo, `GD_Archivo` de prueba, última ejecución |
| `GET /api/files` | paginado. Params: `tipo=ap\|ms`, `estado`, `gatipo`, `ref=OC\|SO`, `page`, `per_page` (≤200). Para `ap` agrega `Referencias` (OC/OS) vía `_referencias_ap`; con `ref` filtra por `_claves_por_referencia` cruzando a `AP_Documentos` por lotes de 150 antes de paginar |
| `GET /api/preview/ap/{id}` | binario `Gadatos` inline (XML→text/plain) |
| `GET /api/preview/ms/{id}` | `Contenido`; si COMPLETADO sirve el archivo del disco destino |
| `GET /api/log?tail=N` | últimas N líneas del log |
| `POST /api/run` | lanza `iniciar_servicio.bat PRUEBA` (solo modo PRUEBA) |
| `POST /api/run/all` | cuenta pendientes AP+MS, sube los lotes del entorno a ese total y corre |
| `POST /api/run/orden` `{numero, tipo}` | valida `numero` `[0-9A-Za-z-]{1,30}`; resuelve obligaciones (`_obligaciones_por_referencia`) y pre-cuenta pendientes (`_contar_pendientes_orden`); 404 si no hay; lanza el batch con `SOLO_REFERENCIA`/`SOLO_REFERENCIA_TIPO` |
| `GET /api/run/{rid}` | estado/salida de una ejecución (`RunManager`: hilo por proceso, captura stdout) |

Reglas transversales: ejecuciones solo en `MODO_SERVICIO=PRUEBA`; `PRODUCCION` requiere `ProduccionHabilitado`; errores → `{ok:false,error}` con código HTTP.

## 3. Frontend — `frontend/templates/index.html` + `static/app.js`

Bootstrap 5 + Chart.js (CDN). Sin framework JS.

- `init()` → `loadConfig`, `loadStats`, `loadLog` + listeners de pestañas/filtros.
- `loadFiles(page)` arma querystring desde `filesState` `{tipo, estado, gatipo, ref, page, per_page}`; `renderFiles` dibuja la tabla (columna OC/OS como badges desde `r.Referencias`, badges de estado, botones Ver/Ver error) y la paginación.
- Ejecuciones: `runNow`, `runAll`, `runOrden` → guardan `activeRunId`, limpian `.run-output` (ambas pestañas comparten la salida por clase) y arrancan `pollRun` (poll cada 2 s a `/api/run/{rid}`) + `startRunTimer` (`.run-info`).
- `previewFile` abre modal con iframe a `/api/preview/…`; `showError` modal con etapa+mensaje.
- `onEntornoChange` confirma el cambio y bloquea PRODUCCION si no está habilitada; `saveConfig` postea los `.config-input`.

`server.py`: waitress detrás de IIS (`HTTP_PLATFORM_PORT`). `inicializar_bd_config.py`: siembra presets PRUEBA/PRODUCCION en `Entornos_Migracion`.

## 4. Scripts de soporte

| Archivo | Rol |
|---|---|
| `iniciar_servicio.bat` | dev: carga `config_modo.bat` o `config.env`, valida bases/raíces exactas, arma `CONN_*`, exige `ENTORNO_VALIDADO` y llama `ejecutar_prueba.bat` / `ejecutar_produccion.bat` |
| `iniciar_servicio_sin_python.bat` | servidor: mismas validaciones, ejecuta `migrar_prueba.exe`/`migrar_produccion.exe` |
| `ejecutar_prueba.bat` / `ejecutar_produccion.bat` | corren el script Python correspondiente tras validar `ENTORNO_VALIDADO` |
| `ejecutar_migracion*.bat` | bloqueados a propósito (anti-ejecución accidental) |
| `build_servicio.bat` | PyInstaller `--onefile` de ambos scripts → `dist\` |
| `verificar_conexiones.bat/.py` | prueba ambas conexiones con la config de prueba |
| `crear_tarea.ps1` | registra la tarea en el servidor (`-Modo`, `-Ruta`, `-IntervaloHoras 2`) |
| `cambiar_modo_tarea.ps1` | cambia PRUEBA/PRODUCCION y tipo de copia; trigger cada 2 h |
| `actualizar_tarea_run_anytime.ps1` | credenciales para correr sin sesión |
| `crear_usuario_migracion.sql` | login + permisos en las 3 bases |
| `frontend/crear_tablas_entornos.sql` | `Entornos_Migracion`, `Config_Activo`, `Auditoria_Cambio_Entorno` |

## 5. Tablas

**MS_HASS_PROVEEDOR (portal)**: `MS_Archivo` (adjuntos: `IdArchivo`,`Tabla`,`Id`,`Nombre`,`Tipo`,`Contenido`,`Empresa`), `MS_AP_DocumentoArchivo` (`IdApDocumentoArchivo`,`Proveedor`,`ObligacionTipoDocumento`,`ObligacionNumeroDocumento`,`Gatipo`,`Ganombre`,`Gadatos`), controles `MS_ArchivoTraslado`/`MS_AP_DocumentoArchivoTraslado` (`Estado`,`Intentos`,`Etapa`,`MensajeError`,`RutaDestino`,`IdGrupo`,`ArchivoId`,fechas) y las del dashboard (`Entornos_Migracion`,`Config_Activo`,`Auditoria_Cambio_Entorno`).

**Spring**: `AP_Documentos` (obligación→OC/OS + `RutaArchivo`), `GD_Grupo` (jerarquía 6 niveles), `GD_Archivo` (metadata del archivo), auxiliares `PersonaMast`, `WH_OrdenCompra`, `Compromiso`.

## 6. API REST — `api_migracion_documentos` (.NET 8)

Reemplazo de `frontend/app.py` con arquitectura limpia (Domain / Application / Infraestructure). **No migra archivos**: orquesta el dashboard — dispara el servicio migrador, lee su log/config y consulta las bases vía SPs `sp_mig_*` con parámetro `@json` que devuelven `FOR JSON`.

### Estructura

```
api_migracion_documentos/
├── Program.cs                              CORS AllowAll, Swagger, DI, sirve el SPA desde wwwroot
├── appsettings.json                        ConnectionStrings (MsHass, Spring) + Migracion:{RutaServicio, Iniciador, ConfigModo, ConfigEnv, LogPrueba}
├── Domain/
│   ├── Models/MigracionModels.cs           ClaveObligacion (record p|t|n), RunInfo (id, status, output, started/finished)
│   ├── Repository/IMigracionRepository.cs  IMigracionMsRepository (portal) + IMigracionSpringRepository (Spring)
│   └── UseCase/IMigracionUseCase.cs        Contrato del caso de uso + ApiResult (Status + Body JSON)
├── Application/UseCaseImpl/
│   └── MigracionUseCase.cs                 Orquestación completa (port de app.py)
└── Infraestructure/
    ├── Controller/MigracionController.cs   Route api/migracion-documentos, POST+JSON salvo previews GET
    ├── Persistence/ConexionFactory.cs      Resuelve conexiones por entorno activo (Config_Activo + Entornos_Migracion); clave solo desde env SQL_PASSWORD
    ├── RepositoryImpl/BaseRepository.cs    EjecutarSpJsonAsync / EjecutarSpRowsetAsync (SPs @json → JSON)
    ├── RepositoryImpl/MigracionRepositoryImpl.cs        SPs del portal (MS_HASS_PROVEEDOR)
    ├── RepositoryImpl/MigracionSpringRepositoryImpl.cs  SPs de Spring con fallback a consulta en línea si el SP no está desplegado
    ├── Services/RunManager.cs              Lanza iniciador .bat como proceso hijo; captura stdout/stderr línea a línea (ConcurrentDictionary de RunInfo)
    ├── Services/ServicioFiles.cs           Parsea/regenera config_modo.bat y config.env, valida config, tail del log (256 KB, latin-1)
    └── Shared/Exceptions/ExceptionMiddleware.cs  Errores → {ok:false,error} JSON
```

### Endpoints — `api/migracion-documentos`

| Endpoint | Uso | Backend |
|---|---|---|
| `POST /entornos` | Lista `Entornos_Migracion` + activo (fallback PRUEBA si no hay DB) | `sp_mig_entornos` |
| `POST /cambiar-entorno` `{entorno}` | Cambia `Config_Activo`, audita IP, regenera configs. 403 si PRODUCCION no habilitada | `sp_mig_entorno_activo` + `sp_mig_config` |
| `POST /config-get` | Config del entorno activo + lista de entornos | `sp_mig_config` (G) |
| `POST /config-update` `{updates}` | Merge sobre claves permitidas, valida y regenera archivos | `sp_mig_config` (U) |
| `POST /stats` | Contadores AP/MS por estado y GATipo, GD prueba, última ejecución, lotes | `sp_mig_stats` + `sp_mig_gd_prueba_count` |
| `POST /archivos` `{tipo,estado,gatipo,ref,page,per_page}` | Bandeja paginada. `ref=OC\|SO` cruza claves contra `AP_Documentos` por lotes de 150; enriquece columna `Referencias` | `sp_mig_candidatos_ap`, `sp_mig_archivos_ap/ms`, `sp_mig_referencias`, `sp_mig_claves_por_ref` |
| `GET /preview/ap/{id}` | Binario `Gadatos` inline; XML → `text/plain` | `sp_mig_preview_ap` (rowset) |
| `GET /preview/ms/{id}` | `Contenido`; si COMPLETADO sirve el archivo desde `RutaDestino` | `sp_mig_preview_ms` |
| `POST /log` `{tail}` | Últimas N líneas del log (máx. 500) | archivo |
| `POST /run` | Ejecución manual con lotes configurados | `RunManager.Start(iniciador PRUEBA)` |
| `POST /run-all` | Recalcula lotes = pendientes totales, regenera config y corre | `sp_mig_pendientes` + `sp_mig_actualizar_lotes` + proceso |
| `POST /run-orden` `{numero,tipo}` | Valida número `[0-9A-Za-z-]{1,30}`; resuelve obligaciones y pre-cuenta pendientes (404 si no hay); inyecta `SOLO_REFERENCIA`/`SOLO_REFERENCIA_TIPO` | `sp_mig_obligaciones_referencia` + `sp_mig_pendientes_orden` |
| `POST /run-status` `{run_id}` | Estado y salida acumulada de la ejecución | memoria (`RunManager`) |

### Reglas transversales

- Ejecuciones solo si `MODO_SERVICIO=PRUEBA` (`ValidarEjecucion` → 403 en producción).
- `ValidarConfig` exige `BD_SPRING`/`RUTA_RAIZ` exactas por entorno; `TIPO_COPIA_PRUEBA ∈ {LOCAL,COMPARTIDA}`; `MODO_PRUEBA ∈ {SIMULACION,ESCRITURA}`; lotes numéricos.
- `SQL_PASSWORD` nunca en `appsettings` ni respuestas: `ConexionFactory` la toma del entorno.
- `RegenerarArchivos` reescribe `config_modo.bat` (PRUEBA) o `config.env` (PRODUCCION) con la fila del entorno; `HABILITAR_PRODUCCION=SI_PRODUCCION` solo si `ProduccionHabilitado=true`.
- `Program.cs` sirve el SPA Angular desde `wwwroot` (`UseDefaultFiles` + `UseStaticFiles` + `MapFallbackToFile("index.html")`).

### Stored procedures — `Scripts/`

Convención: entrada `@json NVARCHAR(MAX)` (JSON_VALUE/OPENJSON), salida `FOR JSON`. `sp_mig_respuesta` envuelve `{status,message,data}`; los previews devuelven rowset (varbinary no cabe en JSON).

| Script | Base | SPs |
|---|---|---|
| `01_sp_ms_hass.sql` | `MS_HASS_PROVEEDOR` | `sp_mig_respuesta`, `sp_mig_entornos`, `sp_mig_entorno_activo`, `sp_mig_config`, `sp_mig_stats`, `sp_mig_candidatos_ap`, `sp_mig_archivos_ap`, `sp_mig_archivos_ms`, `sp_mig_preview_ap`, `sp_mig_preview_ms`, `sp_mig_pendientes`, `sp_mig_pendientes_orden`, `sp_mig_actualizar_lotes` |
| `02_sp_spring.sql` | `HASS_SPRING_PRUEBA` (luego `HP_SPRING_PRD`) | `sp_mig_respuesta`, `sp_mig_referencias`, `sp_mig_claves_por_ref`, `sp_mig_obligaciones_referencia`, `sp_mig_gd_prueba_count` |

Si un SP de Spring no está desplegado, `MigracionSpringRepositoryImpl` detecta el error 2812 y ejecuta la consulta equivalente en línea (el usuario solo tiene SELECT); al desplegarlos con `GRANT EXECUTE` se usan automáticamente.

## 7. Frontend web — `migracion_documentos` (Angular 20)

SPA standalone con rutas con hash (`withHashLocation`, evita URL Rewrite en IIS). Bootstrap 5 + PrimeNG (p-chart) + sweetalert2. `MigracionService` encapsula todos los POST con `lastValueFrom`; `AlertService` centraliza los diálogos; `RunStateService` comparte la ejecución activa entre páginas.

| Ruta | Componente | Función |
|---|---|---|
| `#/dashboard` | `DashboardComponent` | Tarjetas de totales + 4 gráficos (AP por estado, AP por GATipo total/completados, MS por estado) |
| `#/archivos` | `ArchivosComponent` | Tabla paginada con filtros (tabla, estado, GATipo, OC/OS), preview en iframe y modal de error |
| `#/configuracion` | `ConfiguracionComponent` | Selector de entorno (PRODUCCION bloqueado hasta `ProduccionHabilitado`) + edición de parámetros con validación |
| `#/ejecucion` | `EjecucionComponent` | "Ejecutar ahora" / "Procesar todo lo faltante" + consola en vivo (poll `run-status` cada 2 s) + temporizador |
| `#/ejecucion-personalizada` | `EjecucionPersonalizadaComponent` | N° de orden + tipo (Auto/OC/OS) → migra solo los pendientes de esa orden |
| `#/log` | `LogComponent` | Visor de las últimas líneas del log con recarga manual |

`environment.ts` → `apiUrl` local (`http://localhost:5080/...`); `environment.prod.ts` → `https://apimigraciondoc.agroapps.net:7631/api/migracion-documentos`.

## 8. Paquete de despliegue — `api_migracion_doc`

Carpeta publicada (`dotnet publish -c Release`) desplegada en IIS: `api_migracion_documentos.dll/.exe`, `appsettings*.json`, `web.config` (ASP.NET Core Module), `publish/` y `wwwroot` con el build de Angular. URL productiva de la API: `https://apimigraciondoc.agroapps.net:7631`. Requiere .NET 8 Hosting Bundle, AppPool "Sin código administrado" y la variable `SQL_PASSWORD` en la identidad del pool.
