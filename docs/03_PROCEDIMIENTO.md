# Documento de procedimiento — Servicio de migración de adjuntos

## 1. Operación normal

El servicio corre por tarea programada **cada 2 horas** (`MigrarAdjuntosPortalProveedores`). Cada corrida:

1. Lee los archivos pendientes de `MS_Archivo` (lote `BATCH_PRUEBA`) y de `MS_AP_DocumentoArchivo` (lote `BATCH_AP_DOCUMENTO_PRUEBA`).
2. Resuelve para cada uno la OC/OS vía `AP_Documentos`.
3. Copia el archivo a la carpeta de la orden y registra `GD_Archivo` (modo ESCRITURA).
4. Actualiza la tabla de control (`COMPLETADO`/`ERROR` + etapa).

No requiere intervención. El monitoreo se hace desde el dashboard.

## 2. Monitoreo diario

1. Abrir el dashboard → pestaña **Dashboard**: revisar AP pendientes / completados.
2. Pestaña **Archivos**: filtrar Estado = ERROR → botón **Ver error** por fila.
3. Pestaña **Log**: revisar líneas `[FALLIDO]` y la etapa.

## 3. Qué hacer ante errores

| Etapa del error | Causa típica | Acción |
|---|---|---|
| `RESOLVER_AP_DOCUMENTOS` | la factura no tiene registro en `AP_Documentos` o sin referencia OC/OS | verificar la obligación en Spring; cuando se regularice, el reintento la toma sola |
| `VALIDAR_RUTA` | `RutaArchivo` no cumple la estructura de 6 niveles | revisar `AP_Documentos.RutaArchivo` de esa obligación |
| `CONSTRUIR_RUTA_DINAMICA` | sin `RutaArchivo` y faltan compañía/tipo/número/fecha | completar datos en `AP_Documentos` |
| `BUSCAR_GD_GRUPO` | no se pudo crear/encontrar la jerarquía | revisar permisos INSERT en `GD_Grupo` |
| `COPIAR_PRUEBA` | sin acceso al UNC o disco lleno | permisos de red de la cuenta de la tarea |
| `INSERTAR_GD_ARCHIVO` | permisos o PK | permisos INSERT en `GD_Archivo` |

Los errores se **reintentan automáticamente** en cada corrida (estado ERROR vuelve a entrar al lote). No hace falta intervenir salvo para corregir la causa raíz.

## 4. Escenario: adjuntan archivos nuevos a una OC/OS ya migrada

Flujo esperado (verificado):

1. El portal inserta **filas nuevas** en `MS_AP_DocumentoArchivo` / `MS_Archivo` → sin registro de traslado → pendientes.
2. La siguiente corrida las procesa hacia la **misma carpeta** de la orden (el grupo documental existente se reutiliza; no se duplican niveles).
3. Se crean `ArchivoId` nuevos en `GD_Archivo`. Un archivo idéntico (mismo nombre y contenido) se omite; mismo nombre con contenido distinto recibe sufijo `_001`.

**Para no esperar a la tarea**: pestaña *Ejecución personalizada* → ingresar el n° de OC/OS → **Procesar orden**.

**Caso a vigilar**: si el portal *actualizara* el binario en una fila ya COMPLETADO (mismo `IdApDocumentoArchivo`), el servicio **no lo detecta** — los completados no se releen. Si se confirma ese comportamiento del portal, se debe agregar comparación por hash/fecha de modificación.

## 5. Ejecuciones manuales

| Necesidad | Dónde |
|---|---|
| Correr el lote configurado | Dashboard → Ejecución → **Ejecutar ahora** |
| Migrar todo lo pendiente de una vez | Dashboard → Ejecución → **Procesar todo lo faltante** |
| Migrar una sola OC/OS | Dashboard → Ejecución personalizada |
| Manual por consola | `iniciar_servicio_sin_python.bat PRUEBA` (servidor) o `iniciar_servicio.bat PRUEBA` (dev) |

## 6. Cambio de parámetros

Dashboard → Configuración → editar → **Guardar configuración**. Valida y regenera los archivos de arranque. Los lotes controlan cuántos archivos procesa cada corrida.

## 7. Paso a producción (checklist)

Prerequisitos antes de habilitar:

- [ ] Prueba local y compartida aprobadas (resolución de OC/OS, jerarquía, copia íntegra, duplicados).
- [ ] Volumen de prueba suficiente migrado sin errores recurrentes.
- [ ] `ValorTexto1` y `Descripcion` de `GD_Archivo` definidos y aprobados (hoy `PENDIENTE_DEFINIR` / `MIGRACION_PRUEBA`).
- [ ] `migrar_adjuntos_spring.py` (producción) alineado con la tabla de control y campos reales — **pendiente de corrección**, no es copia del de prueba.
- [ ] Permisos de escritura de la cuenta de la tarea sobre `\\172.16.20.24\SpringGestionDoc\PROD`.
- [ ] Aprobación formal registrada.

Activación:

1. En `MS_HASS_PROVEEDOR` ejecutar `preparar_paso_produccion.sql` (cuenta con ALTER/UPDATE):
   crea las columnas `Entornos_Migracion.FECHA_MINIMA`/`FECHA_MAXIMA`, amplía
   `CK_MS_ArchivoTraslado_Estado` (`SIN_AP`, `OMITIDO`) y resetea las tablas de
   control (los COMPLETADO actuales corresponden a HASS_SPRING_PRUEBA).
   Luego re-ejecutar `api_migracion_documentos/Scripts/01_sp_ms_hass.sql` para
   que `sp_mig_config` lea/actualice las columnas nuevas.
2. Ejecutar `python marcar_omitidos_previos.py --ejecutar` (dry-run sin el flag):
   marca OMITIDO los pendientes fuera del rango `[FECHA_MINIMA, FECHA_MAXIMA]`
   (misma regla que el servicio). Sin efecto si ambos límites son TODOS.

   El rango `[FECHA_MINIMA, FECHA_MAXIMA]` es parametrizable por entorno
   (columnas de `Entornos_Migracion`, editables desde el dashboard en
   Configuración): `YYYY-MM-DD` filtra, `TODOS` = sin límite en ese extremo,
   `FECHA_MINIMA` vacío = 2026-01-01, `FECHA_MAXIMA` vacío = sin límite.

   Plan de activación por fases (piloto contabilidad):
   - Fase 1: `FECHA_MINIMA=2026-09-01`, `FECHA_MAXIMA=2026-09-30` → solo
     setiembre 2026 migra; el resto queda OMITIDO con Etapa='VALIDAR_RANGO'.
   - Fase 2 (aprobado por contabilidad): ampliar el rango (p.ej.
     `FECHA_MAXIMA=TODOS` y/o bajar `FECHA_MINIMA`) y reactivar los OMITIDO:
     `UPDATE dbo.MS_ArchivoTraslado SET Estado='PENDIENTE', Etapa=NULL,
     MensajeError=NULL WHERE Estado='OMITIDO' AND Etapa='VALIDAR_RANGO'`
     (idem para `MS_AP_DocumentoArchivoTraslado`). Los COMPLETADO no se tocan.

   Para dejar la base de prueba limpia: `limpiar_todo_prueba.sql` en
   `HASS_SPRING_PRUEBA` borra todos los GD_Archivo/GD_Grupo creados por
   MIGRACION (los archivos físicos en `...\PRUEBAS` se borran a mano).
3. Recompilar: `build_servicio.bat` y copiar `dist\migrar_produccion.exe` al servidor
   (`desplegar_servidor.bat \\servidor\ruta SOLO_EXE`).
4. `cambiar_modo_tarea.ps1 -Modo PRODUCCION` en el servidor (deja `config.env`
   con `HABILITAR_PRODUCCION=NO`; la tarea queda registrada pero bloqueada).
5. En `Entornos_Migracion`, poner `ProduccionHabilitado = 1` para el entorno PRODUCCION.
6. Dashboard → Cambiar entorno → PRODUCCION: regenera `config.env` con
   `HABILITAR_PRODUCCION=SI_PRODUCCION` y `FECHA_MINIMA`, y audita el cambio.
   (Si luego se reejecuta el paso 4, repetir este paso: el ps1 vuelve a dejar NO.)
7. Monitorear las primeras corridas desde el dashboard.

Bloqueos de seguridad vigentes: `iniciar_servicio*.bat` exige `PRODUCCION` explícito + `HABILITAR_PRODUCCION=SI_PRODUCCION` + base `HP_SPRING_PRD` + raíz `...\PROD` exacta; el dashboard solo permite ejecutar en modo PRUEBA.
