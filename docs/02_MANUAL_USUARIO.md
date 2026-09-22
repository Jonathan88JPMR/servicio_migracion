# Manual de usuario — Dashboard de Migración de Adjuntos

Aplicación web para monitorear y controlar la migración de adjuntos del portal de proveedores hacia Spring Gestión Documental.

Acceso local: `http://127.0.0.1:5000` (o la URL del sitio IIS si está desplegado en el servidor).

## Pestañas

### 1. Dashboard

Tarjetas de resumen:

- **AP total**: archivos en `MS_AP_DocumentoArchivo` (portal de facturas).
- **AP pendientes**: archivos con datos aún sin traslado completado.
- **AP completados**: archivos ya migrados.
- **MS pendientes**: adjuntos de `MS_Archivo` pendientes.
- **GD_Archivo (prueba)**: registros insertados por la migración en la base de pruebas.
- **Última ejecución**: fecha del último traslado y batch AP configurado.

Gráficos: AP por estado, AP por GATipo (totales y completados), MS_Archivo por estado.

### 2. Archivos

Lista paginada de archivos con su estado de migración.

**Filtros:**

- **Tabla**: `AP_DocumentoArchivo` (archivos de facturas) o `MS_Archivo` (adjuntos del portal).
- **Estado**: PENDIENTE / COMPLETADO / ERROR.
- **GATipo** (solo AP): XML, CDR, FAC, DIM, OTR.
- **OC/OS** (solo AP): muestra solo archivos cuya factura está relacionada a una Orden de Compra (OC) u Orden de Servicio (OS).

**Columnas (AP):** Id, GATipo, Nombre, Obligación (n° de factura), **OC/OS** (orden relacionada, ej. `SO 6-00001624` o `OC 0000001710` — puede haber varias), Estado, Intentos, Traslado, ArchivoId (id en `GD_Archivo`), Error, acciones.

**Acciones por fila:**

- **Ver**: vista previa del archivo (PDF/XML/imagen) sin descargarlo.
- **Ver error**: detalle del error y la etapa donde falló (para filas en ERROR).

### 3. Configuración

- **Entorno**: selector de entorno activo (PRUEBA / PRODUCCION). PRODUCCION aparece bloqueado hasta que se habilite explícitamente en la base (`Entornos_Migracion.ProduccionHabilitado`). Cada cambio queda auditado.
- **Parámetros**: edita los valores del entorno activo (servidores, bases, lotes `BATCH_PRUEBA`/`BATCH_AP_DOCUMENTO_PRUEBA`, tipo de copia, modo de prueba, etc.). **Guardar configuración** valida y regenera `config_modo.bat`/`config.env`.

Validaciones automáticas: en PRUEBA exige `BD_SPRING=HASS_SPRING_PRUEBA` y la raíz `...\PRUEBAS`; en PRODUCCION exige `HP_SPRING_PRD` y `...\PROD`.

### 4. Ejecución

- **Ejecutar ahora**: corre una migración con los lotes configurados.
- **Procesar todo lo faltante**: ajusta los lotes al total de pendientes y corre una sola vez (puede tardar bastante).
- El panel negro muestra la salida en vivo; arriba se indica inicio, fin y duración.

### 5. Ejecución personalizada

Procesa **solo** los archivos pendientes relacionados a una orden:

- **N° de orden**: número de OC (ej. `0000001710`) u OS (ej. `6-00001624`).
- **Tipo**: `Auto` (busca en OC y OS), `OC` u `OS`.
- **Procesar orden**: primero informa cuántos archivos AP y adjuntos MS pendientes tiene esa orden y cuántas obligaciones (facturas) la componen; luego lanza la migración filtrada. Si todo ya estaba migrado, avisa que no hay pendientes.

Uso típico: cuando en el portal adjuntan archivos nuevos a una OC/OS ya migrada y se quiere sincronizarla de inmediato sin esperar a la tarea de las 2 horas.

### 6. Log

Últimas líneas de `migrar_adjuntos_spring_prueba.log` con botón **Recargar**.

## Estados de un archivo

| Estado | Significado |
|---|---|
| PENDIENTE | registrado para traslado, aún sin procesar |
| PROCESANDO | en ejecución |
| COMPLETADO | copiado al destino y registrado en `GD_Archivo` |
| ERROR | falló; el detalle muestra la etapa y el mensaje. Se reintenta en la siguiente ejecución |

## Comportamiento frente a archivos ya migrados

- Los archivos COMPLETADO **no se reprocesan** nunca.
- Si el portal adjunta archivos nuevos a una OC/OS ya migrada, aparecen como pendientes y se copian a la **misma carpeta** de la orden en la siguiente ejecución.
- Un archivo con el mismo nombre y contenido idéntico se omite; mismo nombre con contenido distinto se guarda con sufijo `_001`, `_002`, etc.
- Los registros insertados en la base de prueba llevan la marca `MIGRACION_PRUEBA`.
