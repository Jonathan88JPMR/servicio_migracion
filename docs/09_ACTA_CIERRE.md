# ACTA DE CIERRE DE PROYECTO

| Campo | Detalle |
|---|---|
| **Nombre del proyecto** | Migración de adjuntos del portal de proveedores a Spring Gestión Documental |
| **Código / referencia** | servicio_documentos |
| **Fecha de inicio** | 14 de septiembre de 2026 |
| **Fecha de cierre (desarrollo)** | 21 de septiembre de 2026 |
| **Duración total** | 8 días calendario / 6 días hábiles |
| **Elaborado por** | Jonathan Marquina — Desarrollo |
| **Aprobado por** | [Nombre del jefe de proyecto / TI] |

> **Nota de alcance del cierre:** este acta cierra la **fase de construcción e implementación en modo PRUEBA**. La habilitación productiva queda como actividad posterior condicionada a la aprobación formal (ver sección 6).

---

## 1. Resumen de ejecución

El proyecto se ejecutó en el periodo planificado. Se entregó el servicio migrador completo, el dashboard web de monitoreo (evolucionado de Flask a Angular + API .NET 8 durante el proyecto), el despliegue en el servidor con tarea programada y el paquete documental completo.

### Avance real medido (al 21/09/2026)

| Métrica | Valor |
|---|---|
| Archivos AP totales (`MS_AP_DocumentoArchivo`) | 117,626 |
| AP completados | 13,512 |
| AP pendientes | 104,114 |
| AP en error | 81 |
| Adjuntos `MS_Archivo` totales | 2,207 |
| MS completados | 617 |
| Registros en `GD_Archivo` (base de pruebas) | 771 |
| Ejecución programada | cada 2 horas, operativa |

## 2. Entregables — conformidad

| # | Entregable | Estado | Observación |
|---|---|---|---|
| 1 | Servicio migrador ejecutable | ✅ Conforme | `migrar_prueba.exe` / `migrar_produccion.exe` compilados con PyInstaller |
| 2 | Tablas de control y configuración | ✅ Conforme | Control por estado/etapa/intentos; entornos y auditoría en `MS_HASS_PROVEEDOR` |
| 3 | Dashboard web operativo | ✅ Conforme | Angular 20 + API .NET 8 en IIS; dashboard Flask conservado como respaldo |
| 4 | API REST + SPs | ✅ Conforme | 13 SPs en `MS_HASS_PROVEEDOR` desplegados; SPs de Spring funcionan con fallback hasta que el DBA los despliegue |
| 5 | Despliegue en servidor | ✅ Conforme | Tarea `MigrarAdjuntosPortalProveedores` cada 2 h; API en `apimigraciondoc.agroapps.net:7631` |
| 6 | Documentación completa | ✅ Conforme | Carpeta `docs/` con 12 documentos + manual ilustrado |

## 3. Verificación de criterios de aceptación

- [x] Resolución obligación → OC/OS vía `AP_Documentos` (incluye filtro por orden).
- [x] Jerarquía `GD_Grupo` de 6 niveles reutilizada o creada; empresa tomada de la ruta real (no fija).
- [x] Copia física íntegra con verificación de tamaño; idénticos omitidos; colisión de nombre → sufijo `_NNN`.
- [x] Duplicados detectados por `(IdGrupo, RutaArchivo)`.
- [x] Reintentos automáticos por estado ERROR con etapa y mensaje.
- [x] Producción protegida: `HABILITAR_PRODUCCION`, validación de base/raíz exacta, dashboard limitado a PRUEBA.
- [x] Credenciales fuera del código (`SQL_PASSWORD` por variable de entorno).

## 4. Desviaciones durante la ejecución

| Desviación | Resolución |
|---|---|
| El dashboard inicial (Flask + JS vanilla) se migró a Angular + .NET para homologar con la arquitectura corporativa (referencia `alquiler_maquinaria`) | Se planificó y ejecutó dentro del mismo periodo (docs/06) |
| `migrar_adjuntos_spring.py` (versión producción) no quedó alineado con la tabla de control | Se mantiene producción bloqueada; ítem pendiente (sección 6) |
| SPs de Spring sin permisos de ejecución para el usuario del servicio | La API opera con fallback de consultas en línea hasta su despliegue |

## 5. Lecciones aprendidas

- Separar la configuración de prueba (`config_modo.bat`) y producción (`config.env`) con validaciones exactas en el iniciador evita errores de entorno de forma efectiva.
- El log por etapas (`[PRUEBA][ETAPA]`) resultó clave para diagnosticar fallos sin depurar el código.
- La tabla de control con reintento automático reduce la operación manual a revisar la causa raíz.

## 6. Actividades y pendientes posteriores al cierre

| Pendiente | Responsable | Condición |
|---|---|---|
| Definir `ValorTexto1` y `Descripcion` finales de `GD_Archivo` para adjuntos manuales (hoy `PENDIENTE_DEFINIR` / `MIGRACION_PRUEBA`) | Usuario funcional + Desarrollo | Antes del pase a producción |
| Alinear `migrar_adjuntos_spring.py` (producción) con la tabla de control y campos reales | Desarrollo | Antes del pase a producción |
| Desplegar `Scripts/02_sp_spring.sql` en `HASS_SPRING_PRUEBA` y `HP_SPRING_PRD` con `GRANT EXECUTE` | DBA | Mejora de rendimiento (API ya funciona con fallback) |
| Aprobación formal y habilitación de producción (`ProduccionHabilitado`, `HABILITAR_PRODUCCION=SI_PRODUCCION`, cambio de tarea) | Responsable + TI | Tras completar los ítems anteriores |
| Volumen restante de migración (~104k AP pendientes) | Automático | Se procesa por corridas de la tarea programada |

## 7. Conformidad y cierre

Se deja constancia de que los entregables comprometidos fueron completados y el sistema opera en modo PRUEBA con monitoreo web, quedando la habilitación productiva condicionada a la aprobación formal.

| Rol | Nombre | Firma | Fecha |
|---|---|---|---|
| Responsable del proyecto | [Nombre] | | 21/09/2026 |
| Desarrollador | Jonathan Marquina | | 21/09/2026 |
| Usuario funcional | [Nombre] | | 21/09/2026 |
