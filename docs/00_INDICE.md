# Índice de documentación — Proyecto Migración de Documentos

**Proyecto:** Migración de adjuntos del portal de proveedores a Spring Gestión Documental
**Periodo:** 14/09/2026 – 21/09/2026
**Estado:** Operativo en modo PRUEBA (producción pendiente de habilitación formal)

## Componentes del sistema

| Componente | Carpeta | Tecnología |
|---|---|---|
| Servicio migrador | `servicio_documentos` | Python 3 → PyInstaller (exe), tarea programada |
| Dashboard legado | `servicio_documentos/frontend` | Flask + waitress + Bootstrap |
| API | `api_migracion_documentos` | .NET 8 Web API (clean architecture) |
| Frontend web | `migracion_documentos` | Angular 20 + PrimeNG + Bootstrap |
| Publicación IIS | `api_migracion_doc` | Binarios publicados de la API + wwwroot |

## Documentos

### Documentación técnica

| # | Documento | Contenido |
|---|---|---|
| — | `../FLUJO_MIGRACION_ADJUNTOS.md` | Reglas funcionales detalladas del flujo de migración (tablas, campos, etapas, permisos, seguridad) |
| 01 | `01_MANUAL_DESPLIEGUE.md` | Despliegue del servicio, tarea programada, dashboard Flask e IIS (Angular + API) |
| 02 | `02_MANUAL_USUARIO.md` | Manual de usuario (versión texto) |
| 03 | `03_PROCEDIMIENTO.md` | Procedimiento operativo: monitoreo, errores, paso a producción |
| 04 | `04_DOCUMENTACION_CODIGO.md` | Documentación del código: servicio Python, Flask, API .NET, Angular, scripts, tablas |
| 05 | `05_FLUJO_COMPLETO.md` | Flujo completo: origen → resolución → copia → registro → control |
| 06 | `06_PLAN_NUEVO_FRONTEND_API.md` | Plan de migración del dashboard Flask a Angular + API .NET |
| 07 | `07_MANUAL_USUARIO_WEB.md` | **Manual de usuario con capturas de pantalla** (aplicación Angular) |
| 12 | `12_INFORME_CONFORMIDAD_GD.md` | Conformidad GD_Grupo/GD_Archivo: flujo actual vs. real Spring, brechas y plan propuesto |

### Documentación de gestión del proyecto

| # | Documento | Contenido |
|---|---|---|
| 08 | `08_ACTA_INICIO.md` | Acta de inicio del proyecto |
| 09 | `09_ACTA_CIERRE.md` | Acta de cierre del proyecto |
| 10 | `10_CRONOGRAMA_GANTT.md` | Cronograma de ejecución y diagrama de Gantt |
| 11 | `11_INFORME_DURACION.md` | Duración del proyecto por fases (inicio → cierre) |

## Imágenes del manual

Las capturas del manual de usuario están en `docs/img/`:

| Archivo | Pantalla |
|---|---|
| `01_dashboard.png` | Dashboard principal (tarjetas + gráficos) |
| `02_archivos.png` | Bandeja de archivos con filtros y estados |
| `03_archivos_preview.png` | Vista previa de un documento (modal) |
| `04_configuracion.png` | Configuración del servicio y entorno activo |
| `05_ejecucion.png` | Ejecución manual / procesar todo |
| `06_ejecucion_personalizada.png` | Ejecución por orden OC/OS |
| `07_log.png` | Visor del log del servicio |
| `08_archivos_error.png` | Archivos filtrados por estado ERROR |
| `09_modal_error.png` | Detalle del error (etapa + mensaje) |

## Contactos y soporte

- Desarrollo: Jonathan Marquina
- Código fuente: carpetas `proyectos/` del equipo de desarrollo
- Log del servicio: `migrar_adjuntos_spring_prueba.log` (carpeta del servicio)
