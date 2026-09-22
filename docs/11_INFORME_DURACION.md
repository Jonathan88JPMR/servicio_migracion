# Informe de duración y fases del proyecto

**Proyecto:** Migración de adjuntos del portal de proveedores a Spring Gestión Documental
**Inicio:** 14/09/2026 · **Cierre de desarrollo:** 21/09/2026
**Duración total:** **8 días calendario · 6 días hábiles** (19 y 20/09 fueron fin de semana)

---

## 1. Resumen ejecutivo

El proyecto se completó en una semana calendario de trabajo intensivo. Del 14 al 21 de septiembre de 2026 se construyeron cuatro componentes: el servicio migrador (Python → ejecutable), el dashboard de monitoreo (primero Flask, luego Angular + API .NET 8), la infraestructura de despliegue (tarea programada + IIS) y el paquete documental completo.

La migración tecnológica del dashboard (Flask → Angular/.NET) se ejecutó **dentro** del periodo sin extender el cronograma, en paralelo con las pruebas del servicio.

## 2. Fases y duración

| Fase | Nombre | Inicio | Fin | Duración | Entregable principal |
|---|---|---|---|---|---|
| F1 | Inicio y análisis | 14/09 | 14/09 | 1 día | Diseño del flujo, análisis de tablas origen/destino |
| F2 | Servicio migrador | 14/09 | 16/09 | 3 días | `migrar_adjuntos_spring_prueba.py` + exe, tablas de control, iniciadores, tarea programada |
| F3 | Dashboard Flask | 15/09 | 16/09 | 2 días | Dashboard operativo (`frontend/`) con stats, archivos, preview, ejecución, entornos |
| F4 | Documentación base | 16/09 | 16/09 | 1 día | `FLUJO_MIGRACION_ADJUNTOS.md`, manuales 01–05, plan 06 |
| F5 | API .NET 8 | 16/09 | 18/09 | 3 días | `api_migracion_documentos`: 13 SPs portal + 5 Spring, publicación IIS |
| F6 | Frontend Angular | 16/09 | 18/09 | 3 días | `migracion_documentos`: 6 páginas, build productivo |
| F7 | Pruebas, ajustes y cierre | 16/09 | 21/09 | 6 días | Pruebas local/compartida, ejecutables finales, actas y manuales |

**Distribución del esfuerzo (días solapados entre fases):** desarrollo ~70 %, despliegue e infraestructura ~15 %, documentación ~15 %.

## 3. Línea de tiempo del proyecto

```
14 sep ─── Inicio · análisis · primer script migrador
15 sep ─── Servicio en PRUEBA · tablas de control · dashboard Flask · tarea 2 h
16 sep ─── Documentación del flujo · inicio API .NET + Angular · prueba compartida
17 sep ─── API completa · SPs desplegados en portal · publish · script despliegue
18 sep ─── Build productivo Angular · appsettings.Production · paquete IIS
 19-20 sep · (fin de semana — servicio corriendo por tarea programada)
21 sep ─── Ejecutables finales · ajustes · publicación API · documentación de gestión · CIERRE
```

## 4. Estado al cierre

- **Operativo en modo PRUEBA** con escritura (`MODO_PRUEBA=ESCRITURA`, copia `COMPARTIDA` a `\\172.16.20.24\SpringGestionDoc\PRUEBAS`).
- Tarea `MigrarAdjuntosPortalProveedores` ejecutando cada 2 horas.
- Migrados al 21/09: **13,512 archivos AP** y **617 adjuntos MS**; 771 registros en `GD_Archivo` de pruebas; ~104k archivos AP pendientes en proceso continuo.
- API en producción de infraestructura (`apimigraciondoc.agroapps.net:7631`) atendiendo el dashboard.
- **Producción del servicio migrador: bloqueada por diseño** hasta aprobación formal (ver acta de cierre, sección 6).

## 5. Factores que influyeron en la duración

| Factor | Efecto |
|---|---|
| Cambio de arquitectura del dashboard a mitad del proyecto | Absorbido en paralelo sin extender el plazo (plan docs/06) |
| Usuario del servicio sin permisos de ejecución de SPs en Spring | Resuelto con fallback de consultas en línea; despliegue de SPs queda como mejora posterior |
| Reglas de seguridad de producción | Añadieron validaciones en iniciadores y API; mantienen producción bloqueada intencionalmente |
| Fin de semana 19–20/09 | No afectó: el servicio siguió procesando por tarea programada |

## 6. Estadísticas del repositorio

- 13 commits de desarrollo registrados el 15/09/2026 (servicio + dashboard Flask).
- Componentes versionados: servicio Python (2 variantes), dashboard Flask, API .NET (4 capas, 13 archivos C#), frontend Angular (6 páginas), 18 SPs, ~15 scripts de soporte (bat/ps1/sql).
- Documentación: 12 documentos en `docs/` + documento de flujo + 9 capturas de pantalla.

## 7. Conclusión

El proyecto cumplió su objetivo dentro del periodo estimado: existe un servicio automatizado, trazable, seguro y monitoreable que migra los adjuntos del portal a Spring Gestión Documental, con la producción resguardada detrás de una aprobación formal y un checklist de pase documentado.
