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

1. Recompilar: `build_servicio.bat` y copiar `dist\migrar_produccion.exe` al servidor.
2. En `Entornos_Migracion`, poner `ProduccionHabilitado = 1` para el entorno PRODUCCION.
3. En `config.env`: `HABILITAR_PRODUCCION=SI_PRODUCCION`.
4. `cambiar_modo_tarea.ps1 -Modo PRODUCCION` en el servidor.
5. Monitorear las primeras corridas desde el dashboard.

Bloqueos de seguridad vigentes: `iniciar_servicio*.bat` exige `PRODUCCION` explícito + `HABILITAR_PRODUCCION=SI_PRODUCCION` + base `HP_SPRING_PRD` + raíz `...\PROD` exacta; el dashboard solo permite ejecutar en modo PRUEBA.
