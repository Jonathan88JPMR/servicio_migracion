/* =====================================================================
   Preparacion de las tablas de control para el paso a PRODUCCION.
   Ejecutar en MS_HASS_PROVEEDOR (172.16.20.25) con una cuenta con
   permisos ALTER/UPDATE (usr_migracion_adjuntos solo tiene UPDATE).

   PASO 1: ampliar CK_MS_ArchivoTraslado_Estado para aceptar los estados
           'SIN_AP' (reintento 24h) y 'OMITIDO' (fuera del rango de fecha).
           Hoy el constraint no los acepta y los registros caen a ERROR.
   PASO 2: resetear las tablas de control. Los estados actuales
           (COMPLETADO/SIN_AP/ERROR) se generaron contra HASS_SPRING_PRUEBA;
           sin reset, produccion omitiria ~24 mil documentos ya migrados
           solo en la base de prueba.

   Orden: PASO 0 -> PASO 1 -> PASO 2 -> marcar_omitidos_previos.py --ejecutar
   ===================================================================== */
USE MS_HASS_PROVEEDOR;
SET NOCOUNT ON;
GO

-- ---------- PASO 0: rango de fechas por entorno ----------
-- [FECHA_MINIMA, FECHA_MAXIMA] configurables desde el dashboard
-- (Configuracion). 'YYYY-MM-DD' filtra; 'TODOS' = sin limite;
-- FECHA_MINIMA NULL/'' = 2026-01-01; FECHA_MAXIMA NULL/'' = sin limite.
-- Seed: solo setiembre 2026 (fase piloto de contabilidad). Para ampliar
-- el rango despues, cambiar los valores y reactivar los OMITIDO:
--   UPDATE dbo.MS_ArchivoTraslado
--   SET Estado='PENDIENTE', Etapa=NULL, MensajeError=NULL
--   WHERE Estado='OMITIDO' AND Etapa='VALIDAR_RANGO';
--   (idem para MS_AP_DocumentoArchivoTraslado)
IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.Entornos_Migracion') AND name = 'FECHA_MINIMA')
    ALTER TABLE dbo.Entornos_Migracion ADD FECHA_MINIMA varchar(10) NULL;
GO
IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dbo.Entornos_Migracion') AND name = 'FECHA_MAXIMA')
    ALTER TABLE dbo.Entornos_Migracion ADD FECHA_MAXIMA varchar(10) NULL;
GO
UPDATE dbo.Entornos_Migracion
SET FECHA_MINIMA = '2026-09-01', FECHA_MAXIMA = '2026-09-30'
WHERE Entorno = 'PRODUCCION' AND FECHA_MINIMA IS NULL;
GO
-- Re-ejecutar Scripts\01_sp_ms_hass.sql para que sp_mig_config
-- lea/actualice la columna nueva (CREATE OR ALTER, es idempotente).
GO

-- ---------- PASO 1: estados validos ----------
ALTER TABLE dbo.MS_ArchivoTraslado DROP CONSTRAINT CK_MS_ArchivoTraslado_Estado;
GO
ALTER TABLE dbo.MS_ArchivoTraslado ADD CONSTRAINT CK_MS_ArchivoTraslado_Estado
CHECK (Estado IN ('PENDIENTE','PROCESANDO','COMPLETADO','ERROR','SIN_AP','OMITIDO'));
GO

-- ---------- PASO 2: reset de controles (conserva la fila y auditoria) ----------
UPDATE dbo.MS_ArchivoTraslado
SET Estado = 'PENDIENTE', Etapa = NULL, MensajeError = NULL,
    RutaDestino = NULL, IdGrupo = NULL, ArchivoId = NULL,
    Intentos = 0, FechaTraslado = NULL, FechaUltimoIntento = NULL;
GO

UPDATE dbo.MS_AP_DocumentoArchivoTraslado
SET Estado = 'PENDIENTE', Etapa = NULL, MensajeError = NULL,
    RutaDestino = NULL, IdGrupo = NULL, ArchivoId = NULL,
    Intentos = 0, FechaTraslado = NULL, FechaUltimoIntento = NULL;
GO

/* Alternativa mas limpia (requiere DELETE): borrar y que el servicio
   recree las filas al procesar.
   DELETE FROM dbo.MS_ArchivoTraslado;
   DELETE FROM dbo.MS_AP_DocumentoArchivoTraslado;
*/
GO
