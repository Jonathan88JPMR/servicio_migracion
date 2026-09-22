USE MS_HASS_PROVEEDOR;
GO

-- Ejecutar este script con una cuenta admin en SQL Server (sa o sysadmin).
-- Luego ejecutar desde consola: python inicializar_bd_config.py

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Entornos_Migracion')
CREATE TABLE dbo.Entornos_Migracion (
    Entorno                   varchar(20)  NOT NULL,
    Descripcion               varchar(100),
    MODO_SERVICIO             varchar(20),
    SERVIDOR_MS_HASS          varchar(100),
    BD_MS_HASS                varchar(100),
    SERVIDOR_SPRING           varchar(100),
    BD_SPRING                 varchar(100),
    RUTA_PRUEBA_LOCAL         varchar(500),
    RUTA_RAIZ                 varchar(500),
    TIPO_COPIA_PRUEBA         varchar(20),
    MODO_PRUEBA               varchar(20),
    BATCH_PRUEBA              varchar(20),
    BATCH_AP_DOCUMENTO_PRUEBA varchar(20),
    TABLA_ADJUNTOS            varchar(50),
    USUARIO_MIGRACION         varchar(50),
    SQL_USER                  varchar(100),
    ProduccionHabilitado      bit DEFAULT 0,
    Activo                    bit DEFAULT 1,
    FechaRegistro             datetime DEFAULT GETDATE(),
    CONSTRAINT PK_Entornos_Migracion PRIMARY KEY (Entorno)
);
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Config_Activo')
CREATE TABLE dbo.Config_Activo (
    Id            int PRIMARY KEY DEFAULT 1,
    Entorno       varchar(20) NOT NULL,
    FechaCambio   datetime DEFAULT GETDATE()
);
GO

IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Auditoria_Cambio_Entorno')
CREATE TABLE dbo.Auditoria_Cambio_Entorno (
    Id                int IDENTITY PRIMARY KEY,
    EntornoAnterior   varchar(20),
    EntornoNuevo      varchar(20),
    Usuario           varchar(100),
    Fecha             datetime DEFAULT GETDATE(),
    IP                varchar(50)
);
GO

-- Permisos para el usuario de migración (reemplazar si el usuario es otro)
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.Entornos_Migracion TO usr_migracion_adjuntos;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.Config_Activo        TO usr_migracion_adjuntos;
GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.Auditoria_Cambio_Entorno TO usr_migracion_adjuntos;
GO

PRINT 'Tablas creadas.';
GO
