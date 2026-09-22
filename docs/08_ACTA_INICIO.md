# ACTA DE INICIO DE PROYECTO

| Campo | Detalle |
|---|---|
| **Nombre del proyecto** | Migración de adjuntos del portal de proveedores a Spring Gestión Documental |
| **Código / referencia** | servicio_documentos |
| **Fecha de inicio** | 14 de septiembre de 2026 |
| **Elaborado por** | Jonathan Marquina — Desarrollo |
| **Aprobado por** | [Nombre del jefe de proyecto / TI] |

---

## 1. Antecedentes y justificación

El portal de proveedores (`MS_HASS_PROVEEDOR`, servidor 172.16.20.25) almacena documentos binarios adjuntados por los proveedores (facturas XML/PDF, CDR, guías, documentos de identidad y otros) en las tablas `MS_Archivo` y `MS_AP_DocumentoArchivo`. Estos documentos deben residir en **Spring Gestión Documental** (`GD_Grupo` / `GD_Archivo`), bajo la jerarquía documental de expedientes de compras, para su consulta y gestión por las áreas usuarias.

Se requiere un servicio automatizado que traslade los archivos, respete la estructura documental `Empresa > Expediente Compras > Orden Compra/Servicio > Año > Mes > Número de orden`, mantenga trazabilidad de cada traslado y permita monitoreo y reintentos.

## 2. Objetivo

Migrar los documentos del portal de proveedores hacia Spring Gestión Documental conservando la relación con la obligación (factura), orden de compra/servicio, proveedor, empresa, grupo documental y ruta física, con control de errores por etapa y capacidad de reintento.

### Objetivos específicos

1. Servicio de migración ejecutable por tarea programada (cada 2 horas) y por demanda.
2. Copia física del archivo al recurso compartido de Spring (`\\172.16.20.24\SpringGestionDoc`) y registro de metadata en `GD_Archivo`/`GD_Grupo`.
3. Tabla de control por archivo (estado, intentos, etapa, mensaje de error, ruta destino).
4. Dashboard web para monitoreo, ejecución manual, ejecución por orden y configuración.
5. Seguridad: producción bloqueada hasta aprobación formal; credenciales fuera del código.

## 3. Alcance

### Incluye

- Servicio migrador en Python compilado a ejecutable (`migrar_prueba.exe`, `migrar_produccion.exe`).
- Modos de operación: PRUEBA (SIMULACION/ESCRITURA, copia LOCAL/COMPARTIDA) y PRODUCCION (bloqueada por defecto).
- Dashboard web: inicialmente Flask; evolucionado a **API .NET 8 + Angular 20** desplegado en IIS (`apimigraciondoc.agroapps.net:7631`).
- Stored procedures `sp_mig_*` para el acceso a datos del dashboard.
- Documentación técnica, de operación, de usuario y de gestión del proyecto.

### No incluye

- Cambios en el portal de proveedores ni en Spring (solo lectura/inserción sobre tablas existentes).
- Migración de históricos no relacionados a obligaciones/órdenes.
- Habilitación productiva (requiere aprobación separada, ver acta de cierre).

## 4. Entregables

| # | Entregable | Criterio de aceptación |
|---|---|---|
| 1 | Servicio migrador ejecutable | Copia íntegra, registra control, reintenta errores |
| 2 | Tablas de control y configuración | `MS_ArchivoTraslado`, `MS_AP_DocumentoArchivoTraslado`, `Entornos_Migracion`, `Config_Activo`, `Auditoria_Cambio_Entorno` |
| 3 | Dashboard web operativo | Stats, archivos, preview, ejecución, configuración, log |
| 4 | API REST + SPs | Endpoints documentados, fallback de consultas, Swagger |
| 5 | Despliegue en servidor | Tarea programada cada 2 h + sitio IIS |
| 6 | Documentación completa | Técnica, flujo, usuario (con imágenes), gestión |

## 5. Recursos y prerrequisitos

- Usuario SQL `usr_migracion_adjuntos` con permisos acotados (SELECT en fuentes, INSERT/UPDATE en control, SELECT/INSERT en `GD_Grupo`/`GD_Archivo`).
- Variable de entorno `SQL_PASSWORD` en la cuenta ejecutora (nunca en archivos).
- Permisos de red de la cuenta Windows sobre el recurso compartido de Spring.
- ODBC Driver 17 for SQL Server; .NET 8 Hosting Bundle; Node/Python solo en desarrollo.

## 6. Riesgos iniciales identificados

| Riesgo | Mitigación |
|---|---|
| Escritura accidental en producción | Doble bloqueo (`HABILITAR_PRODUCCION` + validaciones de base/raíz exactas en el iniciador) |
| Datos incompletos en `AP_Documentos` (sin `RutaArchivo`) | Construcción de ruta dinámica con plantilla por compañía; error con etapa y reintento |
| Duplicados en `GD_Archivo` | Validación por `(IdGrupo, RutaArchivo)` antes de insertar |
| Pérdida de trazabilidad | Tabla de control por archivo + log por etapa + auditoría de entorno |

## 7. Duración estimada

Una semana de desarrollo (14–21/09/2026), detalle en `10_CRONOGRAMA_GANTT.md`.

## 8. Firmas

| Rol | Nombre | Firma | Fecha |
|---|---|---|---|
| Responsable del proyecto | [Nombre] | | 14/09/2026 |
| Desarrollador | Jonathan Marquina | | 14/09/2026 |
| Usuario funcional | [Nombre] | | 14/09/2026 |
