# Plan — `migracion_documentos` (Angular) + `api_migracion_documentos` (.NET 8)

Migra el dashboard Flask a la misma arquitectura de `alquiler_maquinaria` + `api_alquiler_maquinaria`, para desplegar en IIS. **El servicio migrador (Python/exe) no cambia**: la API solo lo dispara y lee sus resultados.

Decisiones confirmadas:
- Sin login (herramienta interna).
- Acceso a datos vía stored procedures con parámetro `@json` que devuelven JSON (`FOR JSON`), igual que `api_alquiler_maquinaria`.
- El dashboard Flask convive en `:5000` hasta validar el nuevo.

## 1. Proyectos nuevos (misma carpeta `proyectos/`)

```
proyectos/
├── alquiler_maquinaria/          (referencia)
├── api_alquiler_maquinaria/      (referencia)
├── servicio_documentos/          (sin cambios)
├── migracion_documentos/         NUEVO - Angular 20
└── api_migracion_documentos/     NUEVO - .NET 8 Web API
```

## 2. `api_migracion_documentos` — estructura

Idéntica a la guía (Domain / Application / Infraestructure):

```
api_migracion_documentos/
├── api_migracion_documentos.sln / .csproj   (net8.0, EF Core 9, Swashbuckle)
├── Program.cs                               (CORS AllowAll, 2 DbContexts, Swagger, ExceptionMiddleware, DI)
├── appsettings.json
│     ConnectionStrings: MsHass (portal) + Spring (ERP)
│     Migracion: { RutaServicio: "C:\\Servicios\\servicio_documentos", LogPrueba, Iniciador }
├── Domain/
│   ├── Models/MigracionModels.cs            DTOs (EntornoItem, ArchivoFila, RunInfo, OrdenRequest, PagedResult…)
│   ├── Repository/IMigracionMsRepository.cs  (portal)
│   ├── Repository/IMigracionSpringRepository.cs (AP_Documentos / GD_Archivo)
│   └── UseCase/IMigracionUseCase.cs
├── Application/UseCaseImpl/MigracionUseCase.cs
├── Infraestructure/
│   ├── Controller/MigracionController.cs    Route: api/migracion-documentos
│   ├── Persistence/MsHassDbContext.cs
│   ├── Persistence/SpringDbContext.cs       (2ª conexión; la guía usa una sola)
│   ├── RepositoryImpl/BaseRepository.cs     EjecutarStoredProcedureAsync(sp, json) FOR JSON
│   ├── RepositoryImpl/MigracionMsRepositoryImpl.cs
│   ├── RepositoryImpl/MigracionSpringRepositoryImpl.cs
│   ├── Services/RunManager.cs               Process + captura stdout (equivalente al de Flask)
│   ├── Services/ServicioFiles.cs            regenera config_modo.bat/config.env + tail del log
│   └── Shared/Exceptions/ExceptionMiddleware.cs
└── Scripts/
    ├── 01_sp_ms_hass.sql                    SPs en MS_HASS_PROVEEDOR
    └── 02_sp_spring.sql                     SPs en HASS_SPRING_PRUEBA (y luego HP_SPRING_PRD)
```

### Endpoints (convención POST + `@json`, salvo descargas)

| Endpoint | Equivale en Flask | SP(s) |
|---|---|---|
| `POST api/migracion-documentos/stats` | `/api/stats` | `sp_mig_stats_portal` + `sp_mig_gd_prueba_count` |
| `POST .../archivos` | `/api/files` (tipo, estado, gatipo, ref, page, per_page) | `sp_mig_candidatos_ap` → `sp_mig_referencias_obligaciones` (Spring) → `sp_mig_archivos_ap` / `sp_mig_archivos_ms` |
| `GET  .../preview/ap/{id}` | `/api/preview/ap` | `sp_mig_preview_ap` (binario) |
| `GET  .../preview/ms/{id}` | `/api/preview/ms` | `sp_mig_preview_ms` (si COMPLETADO, sirve el archivo del `RutaDestino`) |
| `POST .../entornos` | `/api/entornos` | `sp_mig_entornos` |
| `POST .../cambiar-entorno` | `/api/cambiar-entorno` | `sp_mig_entorno_activo` (G/S) + `sp_mig_auditoria_entorno` + regen. archivos |
| `POST .../config-get` / `config-update` | `GET/POST /api/config` | `sp_mig_config` (G/U sobre `Entornos_Migracion`, columnas permitidas) + `validate_config` en C# |
| `POST .../log` | `/api/log?tail=` | archivo (no SP) |
| `POST .../run` | `/api/run` | proceso (no SP) |
| `POST .../run-all` | `/api/run/all` | `sp_mig_contar_pendientes` + `sp_mig_actualizar_lotes` + proceso |
| `POST .../run-orden` `{numero, tipo}` | `/api/run/orden` | `sp_mig_obligaciones_referencia` (Spring) + `sp_mig_contar_pendientes_orden` (portal, OPENJSON) + proceso con `SOLO_REFERENCIA`/`SOLO_REFERENCIA_TIPO` |
| `POST .../run-status` | `/api/run/{rid}` | memoria (RunManager) |

### Reglas portadas desde Flask

- Solo se ejecutan corridas si `MODO_SERVICIO=PRUEBA`; PRODUCCION requiere `ProduccionHabilitado`.
- Filtro OC/OS: candidatos del portal → claves `(proveedor|tipo|num)` → Spring resuelve referencias → filtra y pagina en portal (SP recibe la lista por `OPENJSON`).
- `run-orden` pre-cuenta pendientes y responde 404 si la orden no tiene nada pendiente.
- Preview sirve el binario con `FileResult` (XML → `text/plain`).

### Dependencia de despliegue (BD)

Los SPs `sp_mig_*` se crean en **dos** bases: `MS_HASS_PROVEEDOR` y `HASS_SPRING_PRUEBA`. Para producción habrá que crearlos también en `HP_SPRING_PRD`. Los scripts quedan versionados en `Scripts/` con permisos `GRANT EXECUTE` a `usr_migracion_adjuntos`.

## 3. `migracion_documentos` — Angular 20

Mismo stack de `alquiler_maquinaria` (standalone, `withHashLocation()`, PrimeNG Aura + Bootstrap + sweetalert2). **Sin** módulo auth, **sin** PWA/dexie (dashboard interno; se pueden agregar luego si hace falta).

```
src/app/
├── app.config.ts / app.routes.ts
├── modules/main/
│   ├── layout/layout.component           (menú lateral/topbar)
│   ├── pages/dashboard/                  tarjetas de stats + p-chart
│   ├── pages/archivos/                   p-table lazy + filtros (tipo, estado, GATipo, OC/OS)
│   │                                    + dialog preview (iframe a /preview) + dialog error
│   ├── pages/configuracion/              select entorno + form + guardar
│   ├── pages/ejecucion/                  ejecutar ahora / procesar todo + consola en vivo
│   ├── pages/ejecucion-personalizada/    n° orden + tipo OC/OS + consola en vivo
│   └── pages/log/                        visor del log
├── modules/main/services/migracion.service.ts   (post() con lastValueFrom, igual a la guía)
├── shared/alertas/alerts.service.ts      (sweetalert2)
└── environments/environment(.prod).ts    apiUrl
```

La consola de ejecución hace polling a `run-status` cada 2 s (igual que hoy).

## 4. Despliegue en IIS

| Pieza | Cómo |
|---|---|
| API | `dotnet publish -c Release` → sitio/app IIS con AppPool "Sin código administrado". Requiere **.NET 8 Hosting Bundle** en el servidor (verificar; api_alquiler ya sugiere que existe). El AppPool corre en **el mismo servidor del servicio** para poder lanzar `iniciar_servicio_sin_python.bat`, leer el log y reescribir configs en `C:\Servicios\servicio_documentos`. |
| Frontend | `ng build` → `dist/` como sitio estático en IIS. `withHashLocation()` evita instalar URL Rewrite. |
| Credenciales | Por convención de la guía, connection strings en `appsettings.json`. Nota: el diseño Flask guardaba la clave solo en `SQL_PASSWORD` de entorno; si se prefiere, la API puede leerla de env var — definir antes de implementar. |
| Flask | Sigue en `127.0.0.1:5000` como respaldo hasta dar conformidad al nuevo. |

## 5. Orden de trabajo

1. `Scripts/01_sp_ms_hass.sql` y `02_sp_spring.sql` — crear SPs en ambas bases.
2. API .NET 8 (DbContexts, repositories, use case, controller, RunManager, archivos/log).
3. Frontend Angular (layout, 6 páginas, servicio).
4. Validación local de paridad con el dashboard Flask (mismos conteos, mismas filas, preview, ejecución por orden).
5. Publicación en IIS + actualizar `docs/01_MANUAL_DESPLIEGUE.md`.

## 6. Fuera de alcance

- El servicio migrador y la tarea cada 2 h quedan tal cual.
- `migrar_adjuntos_spring.py` (producción) sigue pendiente de alineación, ítem aparte del checklist de pase a producción.
