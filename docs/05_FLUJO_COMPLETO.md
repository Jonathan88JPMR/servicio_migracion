# Flujo completo del servicio

Cómo viaja un adjunto desde el portal de proveedores hasta Spring Gestión Documental, y cómo se opera todo desde el dashboard (frontend → API → servicio).

## 1. Vista general

```
┌────────────────────────────┐         ┌──────────────────────────────┐
│  Portal de proveedores     │         │  Spring (ERP + Gestión Doc.) │
│  MS_HASS_PROVEEDOR         │         │  HASS_SPRING_PRUEBA / HP_PRD │
│  172.16.20.25              │         │  172.16.20.24                │
│                            │         │                              │
│  MS_Archivo                │  lee    │  AP_Documentos (obligación→  │
│  MS_AP_DocumentoArchivo    ├────────▶│   OC/OS + RutaArchivo)       │
│                            │         │  GD_Grupo (jerarquía 6 niv.) │
│  MS_ArchivoTraslado        │ escribe │  GD_Archivo (metadata)       │
│  MS_AP_Doc...Traslado      ├────────▶│                              │
│  Entornos_Migracion        │ control │                              │
│  Config_Activo             │         │  \\172.16.20.24\             │
│  Auditoria_Cambio_Entorno  │         │   SpringGestionDoc\PRUEBAS   │
└─────────────┬──────────────┘         │   \PROD   (archivos físicos) │
              │                        └──────────────▲───────────────┘
              │ ODBC (usr_migracion_adjuntos)         │ copy + INSERT
              │                                       │
┌─────────────▼───────────────────────────────────────┴───────────────┐
│              SERVICIO DE MIGRACIÓN (Python / exe)                   │
│  iniciar_servicio_sin_python.bat → migrar_prueba.exe                │
│  Tarea programada cada 2 h · también manual desde el dashboard      │
└──────────────────────────────▲──────────────────────────────────────┘
                               │ HTTP JSON
┌──────────────────────────────┴──────────────────────────────────────┐
│  DASHBOARD  frontend/app.py (Flask) + waitress/IIS                  │
│  index.html + app.js (Bootstrap, Chart.js)                          │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. Flujo de migración de un archivo (servicio)

### Origen A — `MS_AP_DocumentoArchivo` (archivos de facturas)

1. **Selección**: `Gadatos IS NOT NULL` y sin traslado `COMPLETADO` (sin registro, `PENDIENTE` o `ERROR`). `TOP {BATCH_AP_DOCUMENTO_PRUEBA}` ordenado por Id.
2. `INICIO`: upsert en `MS_AP_DocumentoArchivoTraslado` → `PROCESANDO`, `Intentos+1`.
3. `RESOLVER_AP_DOCUMENTOS`: busca en `AP_Documentos` por `Proveedor + ObligacionTipoDocumento + ObligacionNumeroDocumento` → obtiene `ReferenciaTipoDocumento` (OC/SO), `ReferenciaNumeroDocumento`, `RutaArchivo`, `CompaniaSocio`, `Fecha`. Sin registro → ERROR "No se encontró AP_Documentos".
4. `VALIDAR_RUTA`: si hay `RutaArchivo`, extrae los 6 niveles tras `PROD`. Si no hay → `CONSTRUIR_RUTA_DINAMICA` con plantilla por compañía (requiere compañía+tipo+número+fecha).
5. `BUSCAR_GD_GRUPO`: recorre `GD_Grupo` nivel por nivel (`IdGrupoPadre`,`NivelGrupo`,`Descripcion`,`Estado='A'`); crea los niveles que falten; devuelve `IdGrupo` del nivel 6 (n° de orden).
6. `CONSTRUIR_RUTA_PRUEBA`: `raiz + jerarquía + Ganombre`. En COMPARTIDA valida que el destino quede bajo `...\PRUEBAS` y nunca contenga `PROD`.
7. `COPIAR_PRUEBA`: escribe `Gadatos` a disco y verifica tamaño. Idéntico → omite; nombre ocupado con contenido distinto → `_001`.
8. `VALIDAR_DUPLICADO`: si `GD_Archivo` ya tiene `(IdGrupo, RutaArchivo)` → marca COMPLETADO reutilizando el `ArchivoId` (sin duplicar).
9. `INSERTAR_GD_ARCHIVO`: `ArchivoId=MAX+1`, `Codigo=Gatipo`, `IdGrupo`, `RutaArchivo`, `ValorTexto1='PENDIENTE_DEFINIR'`, `Descripcion='MIGRACION_PRUEBA'`, `UltimoUsuario='MIGRACION'`.
10. Control → `COMPLETADO` con `RutaDestino`, `IdGrupo`, `ArchivoId`, `FechaTraslado`. Error en cualquier etapa → rollback + `ERROR` con etapa y mensaje.

### Origen B — `MS_Archivo` (adjuntos del portal)

Mismo pipeline, pero la resolución depende de `Tabla`:

- `Obligaciones`: `Id = "proveedor|tipo|numero"` → `AP_Documentos` por obligación.
- `WH_OrdenCompra`: `Id` = n° OC → `AP_Documentos` por referencia `OC` (o asume `tipo=OC` directo).
- `Compromiso`: `Id` = n° OS → referencia `SO`.

En `GD_Archivo` usa `Codigo='AP'`.

### Ejecución personalizada (`SOLO_REFERENCIA`)

Con la env var `SOLO_REFERENCIA` (y opcional `SOLO_REFERENCIA_TIPO=OC|SO`), el servicio primero resuelve en `AP_Documentos` las obligaciones de esa orden y luego filtra los pendientes:

- AP: `Proveedor+Tipo+Número` ∈ obligaciones de la orden.
- MS_Archivo: `Tabla='WH_OrdenCompra' AND Id=n°` (OC), `Tabla='Compromiso' AND Id=n°` (SO) u `Obligaciones` con `Id IN (prov|tipo|num…)`.

Ignora el límite de batch dentro del filtro. Los completados nunca se repiten.

## 3. Flujo desde el frontend y la API

### Carga inicial

`init()` → `GET /api/config` (entorno activo + parámetros de `Entornos_Migracion`), `GET /api/stats` (contadores y gráficos), `GET /api/log`.

### Consulta de archivos con OC/OS

```
usuario elige filtros → loadFiles()
  → GET /api/files?tipo=ap&estado=&gatipo=&ref=&page=
      ├── MS: SELECT paginado MS_AP_DocumentoArchivoTraslado ⋈ MS_AP_DocumentoArchivo
      ├── Spring: _referencias_ap() resuelve ReferenciaTipo+Numero por página (1 query)
      └── si ref=OC|SO: _claves_por_referencia() cruza candidatos contra
          AP_Documentos por lotes de 150 y filtra ANTES de paginar
  → renderFiles(): badges OC/OS, estado, preview y modal de error
```

### Ejecución (normal / todo / por orden)

```
botón → POST /api/run | /api/run/all | /api/run/orden
  → valida MODO_SERVICIO=PRUEBA
  → /api/run/all: recalcula lotes en Entornos_Migracion y regenera config_modo.bat
  → /api/run/orden: resuelve obligaciones en Spring, pre-cuenta pendientes
    (404 si no hay), inyecta SOLO_REFERENCIA/SOLO_REFERENCIA_TIPO en el env
  → RunManager lanza: cmd /c iniciar_servicio.bat PRUEBA
      → valida config → ejecutar_prueba.bat → python migrar_adjuntos_spring_prueba.py
        (en servidor: iniciar_servicio_sin_python.bat → migrar_prueba.exe)
  → pollRun() cada 2 s: GET /api/run/{rid} → pinta stdout en .run-output
    (ambas pestañas Ejecución y Ejecución personalizada)
```

### Cambio de entorno

```
select Entorno → POST /api/cambiar-entorno {entorno}
  → verifica ProduccionHabilitado (PRODUCCION bloqueado si 0)
  → Config_Activo = entorno · Auditoria_Cambio_Entorno (anterior→nuevo, IP)
  → _regenerar_archivos: reescribe config_modo.bat (PRUEBA) o config.env (PRODUCCION)
```

### Vista previa

`Ver` → `GET /api/preview/ap/{id}` (binario de `Gadatos`) o `/api/preview/ms/{id}` (disco destino si ya migrado, si no `Contenido`) → iframe en modal.

## 4. Seguridad aplicada

- `SQL_PASSWORD` solo por variable de entorno; nunca en archivos, logs ni respuestas API.
- Ejecución desde el dashboard solo en PRUEBA; PRODUCCION requiere `ProduccionHabilitado` + `HABILITAR_PRODUCCION=SI_PRODUCCION` + validaciones de base/raíz exactas en el .bat.
- En `COMPARTIDA`, cualquier destino fuera de `...\PRUEBAS` o con segmento `PROD` se rechaza.
- Toda escritura lleva trazabilidad: `UltimoUsuario='MIGRACION'`, `Descripcion='MIGRACION_PRUEBA'`, etapa y mensaje en la tabla de control, auditoría de cambio de entorno.

## 5. Incrementalidad y archivos nuevos en una OC/OS ya migrada

- Los pendientes se detectan por **ausencia de COMPLETADO** en la tabla de control → archivos nuevos que el portal adjunte a una orden migrada se procesan solos en la siguiente corrida (o al instante con *Ejecución personalizada*).
- La jerarquía `GD_Grupo` existente se reutiliza; los archivos nuevos reciben `ArchivoId` nuevo; duplicados exactos `(IdGrupo, RutaArchivo)` no se duplican; mismo nombre con contenido distinto → sufijo `_001`.
- Limitación conocida: si el portal **reemplaza** el binario en una fila ya completada (sin crear registro nuevo), el servicio no lo detecta — los completados no se releen.
