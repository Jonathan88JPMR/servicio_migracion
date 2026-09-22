# Flujo de migración de adjuntos del portal de proveedores a Spring

## 1. Objetivo

Migrar documentos almacenados en el portal de proveedores hacia Spring Gestión Documental, conservando la relación con la obligación, orden de compra o servicio, proveedor, empresa, grupo documental y ruta física. El proceso debe permitir reintentos y registrar la etapa exacta de cada error.

## 2. Ambientes

### Pruebas

- Ejecutable: `ejecutar_prueba.bat`.
- Programa: `migrar_adjuntos_spring_prueba.py`.
- Copia física: carpeta local `pruebas_adjuntos`.
- No modifica `MS_Archivo` ni `MS_ArchivoTraslado`.
- No inserta en `GD_Grupo` ni `GD_Archivo`.
- No escribe en la ruta UNC de Spring.

### Producción

- Ejecutable reservado: `ejecutar_produccion.bat`.
- Programa: `migrar_adjuntos_spring.py`.
- No debe habilitarse hasta completar y aprobar las pruebas.
- La implementación de producción todavía debe alinearse con la tabla de control y con los campos reales de `GD_Archivo`.

## 3. Bases y tablas

### MS_HASS_PROVEEDOR

#### dbo.MS_Archivo

Fuente original del portal. Campos utilizados:

- `IdArchivo`: identificador único del adjunto.
- `Empresa`: empresa del portal.
- `Tabla`: entidad de origen, por ejemplo `Obligaciones`.
- `Id`: relación funcional. Para obligaciones usa `Proveedor|TipoObligacion|NumeroObligacion`.
- `Nombre`: nombre físico del archivo.
- `Tipo`: MIME, por ejemplo `application/pdf`; no es la clasificación documental de Spring.
- `Tamano`: tamaño.
- `Contenido`: archivo binario.
- `FechaCreacion`: orden de selección.

#### dbo.MS_ArchivoTraslado

Control de ejecución y reintentos. Campos principales:

- `IdArchivo`: referencia a `MS_Archivo`.
- `Estado`: `PENDIENTE`, `PROCESANDO`, `ERROR` o `COMPLETADO`.
- `Intentos`: cantidad de intentos.
- `Etapa`: última etapa ejecutada.
- `MensajeError`: causa técnica o funcional.
- `RutaDestino`: ruta final de Spring.
- `IdGrupo`: grupo documental utilizado.
- `ArchivoId`: registro insertado en `GD_Archivo`.
- Fechas de primer intento, último intento y traslado.

### HASS_SPRING_PRUEBA / HP_SPRING_PRD

- `HASS_SPRING_PRUEBA`: base Spring utilizada exclusivamente por el modo de pruebas.
- `HP_SPRING_PRD`: base Spring utilizada exclusivamente por producción.
- Variables separadas: `CONN_SPRING_PRUEBA` y `CONN_SPRING_PRODUCCION`.

#### dbo.AP_Documentos

Relaciona la obligación con la OC/OS y proporciona la ruta documental. Campos utilizados:

- `Proveedor`.
- `ObligacionTipoDocumento`.
- `ObligacionNumeroDocumento`.
- `ReferenciaTipoDocumento`: `OC` u otro código válido de servicio.
- `ReferenciaNumeroDocumento`: número de OC/OS.
- `Fecha`.
- `CompaniaSocio`.
- `DocumentoClasificacion`.
- `DocumentoReferencia`.
- `RutaArchivo`: carpeta UNC completa del nivel 6.

Ejemplo confirmado:

- `MS_Archivo.Id`: `17500|01|F001-0028813`.
- Proveedor: `17500`.
- Referencia: `OC 0000001571`.
- Fecha AP: `2025-04-30`.
- Ruta: `\\172.16.20.24\SpringGestionDoc\PROD\BERRY HARVEST\Expediente Compras\Orden Compra\2025\04-Abril\0000001571\`.

#### dbo.PersonaMast

Fuente prevista de razón social:

- `Persona` se relaciona con `AP_Documentos.Proveedor`.
- `NombreCompleto` se utiliza como `GD_Grupo.DescripcionLarga` cuando sea necesario crear un nivel 6.

#### dbo.WH_OrdenCompra / dbo.Compromiso

Fuentes previstas para obtener la fecha exacta de la OC/OS al crear un grupo nuevo. En el caso confirmado, `AP_Documentos.Fecha` es `2025-04-30`, mientras que `GD_Grupo.Fecha` es `2025-04-29`; por eso no se debe asumir que ambas fechas siempre coinciden.

### Tablas de gestión documental dentro de Spring

`GD_Grupo` y `GD_Archivo` están en `HASS_SPRING_PRUEBA` para pruebas y en `HP_SPRING_PRD` para producción. No existe una tercera conexión de base de datos para gestión documental. El nombre `SpringGestionDoc` que aparece en la ruta UNC corresponde al recurso compartido físico.

#### dbo.GD_Grupo

Jerarquía documental:

1. Empresa, por ejemplo `BERRY HARVEST`.
2. `Expediente Compras`.
3. `Orden Compra` u `Orden Servicio`.
4. Año.
5. Mes con formato `NN-Nombre`.
6. Número de OC/OS.

El nivel 6 contiene:

- `Descripcion`: número de OC/OS.
- `DescripcionLarga`: razón social.
- `Persona`: proveedor.
- `Fecha`: fecha real de la orden o compromiso.

La búsqueda debe recorrer los padres. El número de orden por sí solo no es único. Para `0000001571` existen varios grupos; el correcto para proveedor `17500` y BERRY HARVEST es `IdGrupo=19321`.

#### dbo.GD_Archivo

Metadata del archivo físico:

- `ArchivoId`: identificador generado.
- `Codigo`: `AP` para adjuntos de `Obligaciones`; `WH` queda sujeto a validación para otros orígenes.
- `Nombre`: los ejemplos reales usan `NULL`.
- `RutaArchivo`: ruta UNC completa incluyendo el nombre físico.
- `IdGrupo`: nivel 6.
- `ValorTexto1`: clasificación funcional pendiente de confirmar para adjuntos manuales.
- `Estado`: `A`.
- `Descripcion`: clasificación funcional pendiente de confirmar para adjuntos manuales.

## 4. Flujo funcional

### Paso 1: seleccionar candidatos

Leer `MS_Archivo` con `Contenido IS NOT NULL` y unirlo con `MS_ArchivoTraslado`. Son candidatos los que no tienen control o están en `PENDIENTE`/`ERROR`. Los `COMPLETADO` no se procesan de nuevo.

### Paso 2: interpretar el origen

Para `Tabla='Obligaciones'`, dividir `Id` en tres partes:

1. proveedor;
2. tipo de obligación;
3. número de obligación.

Si el formato no tiene exactamente tres partes, registrar error en `RESOLVER_AP_DOCUMENTOS`.

### Paso 3: resolver AP_Documentos

Buscar por proveedor, tipo y número de obligación. Obtener OC/OS, fecha, compañía, clasificación, referencia y ruta. Si no hay registro o `RutaArchivo` es nula, no copiar ni insertar; registrar el motivo y dejar disponible para reintento.

### Paso 4: validar la ruta

La ruta debe contener esta estructura después de `PROD`:

`Empresa > Expediente Compras > TipoOrden > Año > Mes > NumeroOrden`

No debe usarse una empresa fija. La empresa se toma de la ruta devuelta por Spring.

### Paso 5: buscar GD_Grupo

Recorrer `GD_Grupo` desde nivel 1 hasta nivel 6 usando `IdGrupoPadre`, `NivelGrupo`, `Descripcion` y `Estado='A'`. Si existe, reutilizar el `IdGrupo`. En pruebas, si falta un nivel se informa; no se crea.

### Paso 6: validar duplicados

Construir `RutaArchivo = AP_Documentos.RutaArchivo + MS_Archivo.Nombre`. Buscar en `GD_Archivo` por `IdGrupo` y ruta completa. Si existe, no volver a copiar ni insertar.

### Paso 7: copiar

En pruebas, copiar a:

`pruebas_adjuntos\Empresa\Expediente Compras\TipoOrden\Año\Mes\NumeroOrden\Nombre`

En producción, crear la carpeta UNC si no existe y escribir el contenido binario. La cuenta de Windows que ejecuta la tarea necesita permisos de red para crear carpetas y archivos; el usuario SQL no concede permisos sobre el recurso compartido.

### Paso 8: insertar GD_Archivo

Para obligaciones, usar `Codigo='AP'`, `Nombre=NULL`, la ruta UNC completa y el `IdGrupo` encontrado. `ValorTexto1` y `Descripcion` de adjuntos manuales siguen pendientes de validación funcional, por lo cual producción no debe activarse aún.

### Paso 9: actualizar control

En producción, marcar `COMPLETADO` solamente después de copiar el archivo e insertar exitosamente `GD_Archivo`. Guardar ruta, `IdGrupo`, `ArchivoId` y fecha. Ante error, hacer rollback de las operaciones SQL posibles y guardar `ERROR`, etapa y mensaje para reintento.

## 5. Etapas del log de prueba

- `INICIO`.
- `RESOLVER_AP_DOCUMENTOS`.
- `VALIDAR_RUTA`.
- `BUSCAR_GD_GRUPO`.
- `VALIDAR_DUPLICADO`.
- `COPIAR_PRUEBA`.
- `SIMULAR_GD_ARCHIVO`.
- `RESUMEN`.

Cada línea identifica `IdArchivo`; los fallos incluyen etapa, tabla, Id, nombre, mensaje y traza técnica.

## 6. Permisos

### MS_HASS_PROVEEDOR

```sql
GRANT SELECT ON dbo.MS_Archivo TO usr_migracion_adjuntos;
GRANT SELECT, INSERT, UPDATE ON dbo.MS_ArchivoTraslado TO usr_migracion_adjuntos;
```

### HASS_SPRING_PRUEBA

El modo prueba usa `CONN_SPRING_PRUEBA` y solamente necesita lectura.

```sql
GRANT SELECT ON dbo.AP_Documentos TO usr_migracion_adjuntos;
GRANT SELECT ON dbo.PersonaMast TO usr_migracion_adjuntos;
GRANT SELECT ON dbo.WH_OrdenCompra TO usr_migracion_adjuntos;
GRANT SELECT ON dbo.Compromiso TO usr_migracion_adjuntos;
GRANT SELECT ON dbo.GD_Grupo TO usr_migracion_adjuntos;
GRANT SELECT ON dbo.GD_Archivo TO usr_migracion_adjuntos;
```

### HP_SPRING_PRD

Producción usa exclusivamente `CONN_SPRING_PRODUCCION`. En esta misma base están `AP_Documentos`, `GD_Grupo` y `GD_Archivo`. Sus permisos de escritura no se utilizan durante las pruebas.

## 7. Configuración segura de inicio

`config_modo.bat` contiene exclusivamente la configuración de pruebas: `HASS_SPRING_PRUEBA`, copia `LOCAL` o `COMPARTIDA` y la raíz `\\172.16.20.24\SpringGestionDoc\PRUEBAS`. No contiene valores productivos.

`config.env` contiene exclusivamente la configuración de producción: `HP_SPRING_PRD`, la raíz `\\172.16.20.24\SpringGestionDoc\PROD` y `HABILITAR_PRODUCCION=NO`. No contiene valores de pruebas ni la contraseña SQL.

`iniciar_servicio.bat` exige el argumento `PRUEBA` o `PRODUCCION`. Para pruebas carga únicamente `config_modo.bat`; para producción carga únicamente `config.env`. Exige `SQL_PASSWORD` como variable protegida de Windows, construye las conexiones sin imprimirla y valida bases y rutas exactas.

Producción requiere `iniciar_servicio.bat PRODUCCION` y `HABILITAR_PRODUCCION=SI_PRODUCCION`. `ejecutar_produccion.bat` exige además la marca interna `ENTORNO_VALIDADO=PRODUCCION`. Producción permanece deshabilitada mientras no esté validada.

## 8. Ejecución en el orden requerido

### 8.1 Seguridad de credenciales

1. Rotar en SQL Server la contraseña que fue colocada en archivos.
2. Mantener valores ficticios en `config.env.example` y `crear_usuario_migracion.sql`.
3. Configurar `SQL_USER` y `SQL_PASSWORD` como variables del sistema.
4. No registrar ni guardar la contraseña en Git, logs, SQL o archivos batch.

### 8.2 Prueba local

1. Mantener `MODO_SERVICIO=PRUEBA` y `TIPO_COPIA_PRUEBA=LOCAL`.
2. Ejecutar `verificar_conexiones.bat`.
3. Ejecutar `iniciar_servicio.bat PRUEBA`.
4. Revisar `migrar_adjuntos_spring_prueba.log` y `pruebas_adjuntos`.
5. Confirmar resolución de empresa, obligación, OC/OS, jerarquía e IdGrupo.

### 8.3 Prueba física compartida

1. Cambiar únicamente `TIPO_COPIA_PRUEBA=COMPARTIDA` en `config_modo.bat`.
2. Confirmar que `config_modo.bat` conserva `MODO_SERVICIO=PRUEBA` y `HASS_SPRING_PRUEBA`.
3. Ejecutar `iniciar_servicio.bat PRUEBA` manualmente.
4. El destino se reconstruye bajo `\\172.16.20.24\SpringGestionDoc\PRUEBAS` conservando empresa, expediente, tipo de orden, año, mes, número y nombre.
5. El programa rechaza cualquier destino fuera de la raíz autorizada o que contenga el segmento `PROD`.
6. Verificar archivo, tamaño y log. La prueba no escribe `MS_ArchivoTraslado`, `GD_Grupo` ni `GD_Archivo`.

### 8.4 Tarea automática de pruebas

Ejecutar como administrador:

```powershell
powershell -ExecutionPolicy Bypass -File cambiar_modo_tarea.ps1 -Modo PRUEBA -TipoPrueba COMPARTIDA
```

La tarea ejecutará `iniciar_servicio.bat PRUEBA` cada 2 horas. El proceso no usa `pause`, por lo que puede finalizar sin una sesión interactiva.

Para el despliegue en el servidor (`C:\Servicios\servicio_documentos`, con `migrar_prueba.exe` compilado):

```powershell
powershell -ExecutionPolicy Bypass -File crear_tarea.ps1 -Modo PRUEBA
```

Registra la misma tarea apuntando a `iniciar_servicio_sin_python.bat` cada 2 horas. Si debe correr sin sesión iniciada, ejecutar además `actualizar_tarea_run_anytime.ps1`.

### 8.5 Producción

No habilitar hasta aprobar la prueba local, la prueba compartida, el mapeo de metadata, los reintentos y el script de producción. Al solicitar `-Modo PRODUCCION`, el configurador deja `HABILITAR_PRODUCCION=NO`; se requiere una aprobación separada antes de cambiarlo.

## 9. Criterios de aprobación

- Resuelve correctamente obligación, OC/OS y proveedor.
- La empresa y jerarquía coinciden con `AP_Documentos.RutaArchivo`.
- Encuentra el nivel 6 correcto entre números repetidos.
- Copia íntegramente el archivo en pruebas.
- Detecta duplicados.
- No modifica producción durante la prueba.
- El log permite localizar cualquier fallo.
- Se define y aprueba el valor de `ValorTexto1` y `Descripcion` para adjuntos manuales.
- Se corrige y valida el programa de producción antes de cambiar la tarea programada.
