# 12. Informe de conformidad — Jerarquía GD_Grupo y GD_Archivo

**Fecha:** 21/09/2026
**Alcance:** `migrar_adjuntos_spring_prueba.py` (pruebas) y `migrar_adjuntos_spring.py` (producción)
**Evidencia:** datos reales de `HP_SPRING_PRD` (agosto 2026), jerarquía del expediente `8-00010848` → `IdGrupo=43605` y sus `GD_Archivo`.

---

## 1. Proceso definido por el negocio

1. Procesar registros con flag de traslado en `0`.
2. Por cada factura/archivo del portal: ubicar la **Orden de Compra/Servicio** y el **RUC/proveedor**.
3. Recuperar el **nivel 6** de `GD_Grupo` con el número de orden **+ código del proveedor**.
4. Con ese `IdGrupo`, insertar en `GD_Archivo` el registro con la ubicación del archivo **y copiar el archivo** a la carpeta.
5. Si no existen las rutas, crearlas; igual con los 6 niveles de la tabla.
6. Niveles 1–3 (rojo en captura) los crea el sistema Spring y son **fijos**; niveles 4–5 (morado) son **Año** y **Mes/Fecha**; el **nivel 6 es el detalle** (la orden).

### Jerarquía real confirmada (caso `8-00010848`)

| Nivel | IdGrupo | Padre | Descripcion | Orden | ValorTexto | Quién lo crea |
|---|---|---|---|---|---|---|
| 1 | 1 | NULL | `HASS PERU` | `0001` | `00000800` (cía) | Sistema (fijo) |
| 2 | 2 | 1 | `Expediente Compras` | `0001.0001` | `C` | Sistema (fijo) |
| 3 | 4 | 2 | `Orden Servicio` | `0001.0001.0002` | `NULL` | Sistema (fijo) |
| 4 | 34651 | 4 | `2026` | `0001.0001.0002.0008` | `NULL` | Dinámico (año) |
| 5 | 41511 | 34651 | `06-Junio` | `0001.0001.0002.0008.0008` | `NULL` | Dinámico (mes) |
| 6 | **43605** | 41511 | `8-00010848` | `0001.0001.0002.0008.0008.0410` | `NULL` | **Detalle (orden + proveedor)** |

Datos del nivel 6 real: `GrupoTipo=1`, `Raiz='N'`, `EsPrincipal=NULL`, `Estado='A'`, `DescripcionLarga='EMPRESA DE TRANSF…'` (razón social), `Persona`=código proveedor, `Fecha`=fecha de la orden, `LastFlag='S'`.

`GD_Archivo` real para 43605: `Codigo='WH'`, `Nombre=NULL`, `RutaArchivo=\\...\8-00010848\archivo`, `ValorTexto1='OS'`, `Descripcion='COTIZACION'/'SUSTENTO'/NULL`, `Archivo=NULL`, `UltimoUsuario=NULL`. Los registros `Codigo='AP'` + `ValorTexto1='VO'` son **vouchers internos de Spring** (`VO_00000800_CPxxxx`, `XPDFOBLIGACION…`) — no son adjuntos migrados.

---

## 2. Lo que el servicio SÍ hace bien hoy

`migrar_adjuntos_spring_prueba.py` respeta la estructura del flujo:

| Paso del proceso | Implementación | Estado |
|---|---|---|
| Flag traslado = 0 | `MS_ArchivoTraslado` LEFT JOIN → procesa `PENDIENTE`/`ERROR`/sin registro | ✅ equivalente (mejor: guarda etapa, intentos y error) |
| Ubicar OC + proveedor por factura | `Obligaciones` → `Id = Proveedor\|TipoObl\|NumObl` → `AP_Documentos` | ✅ |
| Resolver OC/OS | `ReferenciaTipoDocumento` + `ReferenciaNumeroDocumento` de `AP_Documentos` | ✅ |
| Empresa correcta | Se toma de `AP_Documentos.RutaArchivo`/`CompaniaSocio` (no fija) | ✅ |
| 6 niveles por padres | `buscar_o_crear_jerarquia_gd_grupo` recorre nivel 1→6 por `IdGrupoPadre`+`Descripcion` | ✅ reutiliza niveles fijos existentes |
| Crear niveles faltantes | Inserta niveles 4–6 que falten | ⚠️ los crea, pero con campos incorrectos (§3) |
| Copiar archivo | `guardar_archivo_prueba` escribe, verifica tamaño, no pisa archivos distintos | ✅ |
| Duplicados | Busca `GD_Archivo` por `IdGrupo`+`RutaArchivo` antes de insertar | ✅ |
| Insertar `GD_Archivo` con `IdGrupo` nivel 6 | `insertar_gd_archivo_prueba` | ⚠️ inserta, pero campos placeholder (§3) |
| Marcar flag | `actualizar_control` → `COMPLETADO` con `RutaDestino`, `IdGrupo`, `ArchivoId` | ✅ solo tras copiar + insertar |
| Trazabilidad | Log por etapas (`INICIO`→`COMPLETADO`), reintentos con `Intentos`/`Etapa` | ✅ |

Además procesa la segunda fuente (`MS_AP_DocumentoArchivo` → `Gadatos`) con su tabla de control `MS_AP_DocumentoArchivoTraslado`.

---

## 3. Brechas encontradas (NO conforme aún)

### 3.1 `GD_Grupo` — inserción de niveles faltantes

Línea de insert: `migrar_adjuntos_spring_prueba.py` `buscar_o_crear_jerarquia_gd_grupo`.

| Campo | Real Spring | Servicio actual | Brecha |
|---|---|---|---|
| `GrupoTipo` | `1` | `0` | ❌ |
| `Orden` | `padre.Orden + '.' + posición(4d)` → `…0008.0008.0410` | `NULL` | ❌ crítico: Spring ordena la UI por este campo |
| `DescripcionLarga` | **razón social del proveedor** (nivel 6) | `descripcion[:200]` (repite el nro. de orden) | ❌ |
| `Persona` | código del proveedor (`17325`, `17500`…) | `0` | ❌ la regla dice "orden **+ código de proveedor**" |
| `Fecha` | fecha de la orden | `GETDATE()` | ❌ año/mes de la jerarquía pueden no cuadrar con la fecha |
| `LastFlag` | `S` | `N` | ❌ |
| `EsPrincipal` | `NULL` en hijos | `'S'`/`'N'` | ⚠️ menor |
| `Raiz` | `S` solo en raíz | `S`/`N` correcto | ✅ |
| Búsqueda nivel 6 | orden + proveedor | solo `Descripcion` bajo el padre-mes | ⚠️ añadir `Persona` al match |

### 3.2 `GD_Archivo` — inserción del adjunto

| Campo | Real Spring | Servicio actual | Brecha |
|---|---|---|---|
| `Codigo` | **`WH`** (adjuntos OC/OS); `AP` solo vouchers | `AP` (MS_Archivo) / `Gatipo` (MS_AP_…) | ❌ |
| `ValorTexto1` | **`OC`/`OS`** (tipo de la orden) | `PENDIENTE_DEFINIR` | ❌ |
| `Descripcion` | clasificación funcional o `NULL` | `MIGRACION_PRUEBA` | ❌ placeholder |
| `Nombre` | `NULL` | `NULL` | ✅ |
| `Archivo` | `NULL` | nombre del archivo | ⚠️ menor |
| `UltimoUsuario` | `NULL` | `MIGRACION` | ⚠️ recomendable mantenerlo (auditoría) |
| `ArchivoId` | secuencial | `MAX()+1` con `TABLOCKX` | ⚠️ funciona; verificar si `ArchivoId` es `IDENTITY` en PRD |
| `IdGrupo`/`RutaArchivo`/`Estado` | nivel 6 / UNC completa / `A` | correcto | ✅ |

### 3.3 Script de producción `migrar_adjuntos_spring.py` — desalineado

Es una versión **anterior** al rediseño. Diferencias frente al de prueba y a la regla:

| Aspecto | Producción actual | Problema |
|---|---|---|
| Selección | `MS_Archivo.FlagTraslado=0` | No usa tabla de control → sin etapa/reintento ni visibilidad en el dashboard |
| Empresa | `EMPRESA_GD_GRUPO` fija (`HASS PERU`) | ❌ la regla exige empresa dinámica desde `AP_Documentos` |
| Nivel 2/3 | busca `Expediente Compras`/`Orden Compra` hardcodeado | ⚠️ solo cubre OC/OS de compras |
| `Orden` | `f"{id_padre:04d}.{seq:04d}"` | ❌ formato incorrecto (usa IdGrupo, no la posición) |
| `Fecha` jerarquía | `datetime.now()` | ❌ debe ser fecha de la orden |
| `Persona`/`DescripcionLarga`/`LastFlag` | no los envía | ❌ |
| Ruta | exige `AP_Documentos.RutaArchivo`; si es NULL omite | ⚠️ el de prueba sí construye ruta dinámica |
| Duplicados | sin validación | ❌ puede duplicar `GD_Archivo` |
| `GD_Archivo` | `Codigo=tipo[:2]` (del MIME!) | ❌ |
| `MS_AP_DocumentoArchivo` | no lo procesa | ❌ falta toda la fuente |

**Conclusión: el script de producción NO está listo; hay que reescribirlo reutilizando la lógica del de prueba.**

---

## 4. Plan aplicado (21/09/2026) — correcciones implementadas

**Ambos scripts** (`migrar_adjuntos_spring_prueba.py` y `migrar_adjuntos_spring.py`) fueron corregidos y el de producción reescrito alineado al flujo de prueba.

### A. `GD_Grupo` — implementado

- `Orden` = `padre.Orden + '.' + posición(4d)`, posición = `MAX(TRY_CAST(RIGHT(Orden,4)))+1` entre hermanos → `…0008.0410`.
- Nivel 6 (hoja): `Persona`=proveedor, `DescripcionLarga`=`PersonaMast.NombreCompleto`, `Fecha`=fecha de la orden, `LastFlag='S'`, `GrupoTipo=1`, `EsPrincipal=NULL`, `Raiz='N'`, `UltimoUsuario='MIGRACION'`.
- Niveles 4–5 (año/mes): `GrupoTipo=1` y el resto `NULL` (igual que los reales creados por Spring).
- **Match nivel 6 por `Descripcion + Persona`** (obligatorio: el mismo número de orden existe con hasta 4 proveedores distintos).
- Proveedor/fecha se obtienen de la **tabla de la orden**: `Compromiso.FechaDocumento` (SO) y `WH_OrdenCompra.FechaPreparacion` (OC, filtrando por `Proveedor` — verificado: `0000003399`+5783 → 09/09 = FechaPreparacion, no FechaAprobacion).
- En SIMULACION ya no se crean niveles: se informan los que faltarían (`crear=False`).

### B. `GD_Archivo` — implementado

- `Codigo='WH'` en ambas fuentes (MS_Archivo y MS_AP_DocumentoArchivo).
- `ValorTexto1` = `ReferenciaTipoDocumento` de AP (`OC`/`SO`), propagado tal cual.
- `Archivo=NULL`, `Nombre=NULL`; `UltimoUsuario='MIGRACION'` (trazabilidad).
- `Descripcion` = mapa `CLASIFICACION_GATIPO` (`FAC→FACTURA`, `XML→XML`, `CDR→CDR`, `DIM/OTR→SUSTENTO`) — **pendiente aprobación funcional**; `MS_Archivo` queda `NULL`.

### C. Producción (`migrar_adjuntos_spring.py`) — reescrito

- Usa `MS_ArchivoTraslado`/`MS_AP_DocumentoArchivoTraslado` (la columna `FlagTraslado` **no existe** en `MS_Archivo`).
- Empresa dinámica desde `AP_Documentos` (ya no fija), ruta real `\\…\PROD` + construcción dinámica si `RutaArchivo` es NULL.
- Duplicados por `IdGrupo`+`RutaArchivo`, nombre único si el contenido difiere, rollback por registro.
- Guard `HABILITAR_PRODUCCION=SI_PRODUCCION`; soporta `SOLO_REFERENCIA`/`SOLO_REFERENCIA_TIPO` para ejecución por orden.

### D. Validación ejecutada

Simulación real `8-00010848` (SO): resolvió `Proveedor=5886`, `FechaOrden=2026-06-25`, `RazonSocial=EMICER`, jerarquía `HASS PERU > Expediente Compras > Orden Servicio > 2026 > 06-Junio > 8-00010848` y **`IdGrupo=43605`** — idéntico al grupo real de Spring. 3 adjuntos `MS_AP_DocumentoArchivo` simulados con `Codigo=WH`, `ValorTexto1=SO`, `Descripcion=XML/FACTURA/SUSTENTO`.

---

## 5. Pendiente de revisión para dar conformidad

**Verificado directamente en las bases (21/09/2026):**

| # | Punto | Resultado verificado |
|---|---|---|
| 1 | `IdGrupo`/`ArchivoId` ¿IDENTITY? | **NO son IDENTITY** (int manual) → `MAX()+1` es la única vía; mantener `TABLOCKX`+commit inmediato |
| 2 | `MS_Archivo.FlagTraslado` | **La columna NO existe** → el script de producción actual fallaría (`Invalid column name`). La tabla `MS_ArchivoTraslado` ES la implementación del "flag en 0" |
| 3 | `ReferenciaTipoDocumento` | Solo existen `'OC'` (19 728) y `'SO'` (49 997) → `SO` es correcto para consultar AP |
| 4 | `ValorTexto1` en `GD_Archivo` | Bajo `Orden Compra`='OC'; bajo `Orden Servicio` conviven `'SO'` (25 689) y `'OS'` (23 258) → propagar el tipo de AP es válido; `'OS'` proviene de otra fuente |
| 5 | `Fecha` del nivel 6 | **Resuelto**: `Compromiso.FechaDocumento` (caso `8-00010848` → 25/06/2026 → nivel `06-Junio` ✓). Para OC definir columna de `WH_OrdenCompra` (`FechaAprobacion`?) |
| 6 | Niveles 4–5 creados | Real: `DescripcionLarga/Persona/Fecha/LastFlag/EsPrincipal=NULL`, `GrupoTipo=1` → `LastFlag='S'` solo en la hoja (nivel 6) |
| 7 | Duplicados nivel 6 | **CRÍTICO**: el mismo número de orden existe con distinto `Persona` (ej. `'0000000004'` → 4 grupos, 4 proveedores) → el match debe ser `Descripcion + Persona`, no solo descripción |
| 8 | SPs `sp_mig_*` | Desplegados en `MS_HASS_PROVEEDOR` (13 SPs). **NO desplegados en `HASS_SPRING_PRUEBA` ni `HP_SPRING_PRD`** → la API usa fallback SQL inline; desplegar `Scripts/02_sp_spring.sql` en ambas |
| 9 | Permisos `usr_migracion_adjuntos` | PRUEBA: `INSERT/SELECT` en `GD_*`, `SELECT` en `AP_Documentos/Compromiso/WH_OrdenCompra/PersonaMast` ✓. **PRD falta `SELECT` en `Compromiso`, `WH_OrdenCompra`, `PersonaMast`** |

**Aún pendiente de decisión/validación funcional:**

| # | Punto | Quién valida |
|---|---|---|
| A | `GD_Archivo.Descripcion` (clasificación): mapeo `Gatipo` implementado (`FAC→FACTURA`, `XML→XML`, `CDR→CDR`, `DIM/OTR→SUSTENTO`) — aprobar o ajustar | Funcional |
| B | ~~`ValorTexto1` SO/OS~~ → **resuelto por el usuario**: `OS` para orden de servicio, `OC` para orden de compra (`TIPO_ORDEN_GD` mapea `SO→OS`) | ✅ |
| C | ~~Columna de fecha para OC~~ → **resuelto**: `WH_OrdenCompra.FechaPreparacion` (verificado contra datos reales) | ✅ |
| D | `UltimoUsuario='MIGRACION'` (real usa NULL) — se mantiene por auditoría | Funcional (informativo) |
| E | ~~Proveedor sin AP_Documentos~~ → **implementado**: se lee `Proveedor`/`Fecha` directo de `WH_OrdenCompra`/`Compromiso` | ✅ |

**Pendientes de infraestructura (previos a habilitar producción):**

| # | Acción | Dónde |
|---|---|---|
| F | Desplegar `Scripts/02_sp_spring.sql` (`sp_mig_*` de Spring) | `HASS_SPRING_PRUEBA` y `HP_SPRING_PRD` |
| G | `GRANT SELECT` en `Compromiso`, `WH_OrdenCompra`, `PersonaMast` para `usr_migracion_adjuntos` | `HP_SPRING_PRD` (en PRUEBA ya están) |
| H | Recompilar ejecutables PyInstaller (`migrar_prueba.spec`, `migrar_produccion.spec`) y redesplegar a `C:\Servicios\servicio_documentos` | Dev |
| I | Prueba ESCRITURA en `HASS_SPRING_PRUEBA` con una orden real y comparación campo a campo (queries §6) | Dev + Funcional |

---

## 6. Verificación post-corrección (queries de aceptación)

```sql
-- 1) El nivel 6 creado debe verse idéntico a uno real
SELECT * FROM GD_Grupo WHERE IdGrupo = @id_nivel6_creado;
--    Orden con 6 segmentos, Persona=proveedor, DescripcionLarga=razón social,
--    GrupoTipo=1, LastFlag='S', Fecha=fecha de la orden

-- 2) El adjunto enlazado al nivel 6
SELECT * FROM GD_Archivo WHERE IdGrupo = @id_nivel6_creado;
--    Codigo='WH', ValorTexto1='OC'/'OS', RutaArchivo=UNC completa existente

-- 3) Sin duplicados ni huérfanos
SELECT IdGrupo, RutaArchivo, COUNT(*) FROM GD_Archivo
GROUP BY IdGrupo, RutaArchivo HAVING COUNT(*) > 1;

SELECT * FROM MS_ArchivoTraslado WHERE Estado='COMPLETADO' AND ArchivoId IS NULL;

-- 4) Caso de prueba de punta a punta (orden conocida)
--    Compromiso.NumeroCompromiso='8-00010848' → GD_Grupo.IdGrupo=43605
--    → GD_Archivo.IdGrupo=43605 → archivo físico presente en la UNC
```

**Criterio de conformidad:** ejecutar en `HASS_SPRING_PRUEBA` (modo ESCRITURA) una orden real con adjuntos, comparar campo a campo contra un grupo creado por Spring (p. ej. 43605), copiar físicamente y validar que Spring abre el adjunto desde Gestión Documental. Solo entonces habilitar producción.
