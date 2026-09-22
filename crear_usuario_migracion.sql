USE master;
GO

-- 1. Crear login SQL para el servicio de migracion
-- Reemplazar 'TuContrasenaSegura123!' por una contrasena fuerte
CREATE LOGIN usr_migracion_adjuntos
WITH PASSWORD = 'CAMBIAR_ANTES_DE_EJECUTAR',
     CHECK_POLICY = OFF,
     CHECK_EXPIRATION = OFF;
GO

-- 2. Permisos en MS_HASS_PROVEEDOR (portal de proveedores)
USE MS_HASS_PROVEEDOR;
GO
CREATE USER usr_migracion_adjuntos FOR LOGIN usr_migracion_adjuntos;
GO
ALTER ROLE db_datareader ADD MEMBER usr_migracion_adjuntos;
ALTER ROLE db_datawriter ADD MEMBER usr_migracion_adjuntos;
GO

-- Permisos sobre adjuntos originales y control separado de traslados
GRANT SELECT ON dbo.MS_Archivo TO usr_migracion_adjuntos;
GRANT SELECT, INSERT, UPDATE ON dbo.MS_ArchivoTraslado TO usr_migracion_adjuntos;
GO

-- Permisos para facturas/proveedor y su nueva tabla de control
GRANT SELECT ON dbo.MS_AP_DocumentoArchivo TO usr_migracion_adjuntos;
GRANT SELECT, INSERT, UPDATE ON dbo.MS_AP_DocumentoArchivoTraslado TO usr_migracion_adjuntos;
GO

-- SPs del dashboard/api de migracion (Scripts/01_sp_ms_hass.sql)
GRANT EXECUTE ON dbo.sp_mig_respuesta         TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_entornos          TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_entorno_activo    TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_config            TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_stats             TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_candidatos_ap     TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_archivos_ap       TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_archivos_ms       TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_preview_ap        TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_preview_ms        TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_pendientes        TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_pendientes_orden  TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_actualizar_lotes  TO usr_migracion_adjuntos;
GO

-- 3. Permisos en HASS_SPRING_PRUEBA (ERP Spring de pruebas)
USE HASS_SPRING_PRUEBA;
GO
CREATE USER usr_migracion_adjuntos FOR LOGIN usr_migracion_adjuntos;
GO
ALTER ROLE db_datareader ADD MEMBER usr_migracion_adjuntos;
GO
GRANT SELECT ON dbo.AP_Documentos TO usr_migracion_adjuntos;
GRANT SELECT, INSERT ON dbo.GD_Grupo TO usr_migracion_adjuntos;
GRANT SELECT, INSERT ON dbo.GD_Archivo TO usr_migracion_adjuntos;
GO

-- SPs del dashboard/api de migracion (Scripts/02_sp_spring.sql)
GRANT EXECUTE ON dbo.sp_mig_respuesta               TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_referencias             TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_claves_por_ref          TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_obligaciones_referencia TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_gd_prueba_count         TO usr_migracion_adjuntos;
GO

-- 4. Permisos en HP_SPRING_PRD (ERP Spring de produccion)
USE HP_SPRING_PRD;
GO
CREATE USER usr_migracion_adjuntos FOR LOGIN usr_migracion_adjuntos;
GO
ALTER ROLE db_datareader ADD MEMBER usr_migracion_adjuntos;
GO
GRANT SELECT ON dbo.AP_Documentos TO usr_migracion_adjuntos;
GRANT SELECT, INSERT ON dbo.GD_Grupo TO usr_migracion_adjuntos;
GRANT SELECT, INSERT ON dbo.GD_Archivo TO usr_migracion_adjuntos;
GO

-- SPs del dashboard/api de migracion (Scripts/02_sp_spring.sql)
GRANT EXECUTE ON dbo.sp_mig_respuesta               TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_referencias             TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_claves_por_ref          TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_obligaciones_referencia TO usr_migracion_adjuntos;
GRANT EXECUTE ON dbo.sp_mig_gd_prueba_count         TO usr_migracion_adjuntos;
GO

PRINT 'Usuario usr_migracion_adjuntos creado y permisos asignados.';
GO
