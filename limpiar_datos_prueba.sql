/* =====================================================================
   Limpieza de datos de prueba - HASS_SPRING_PRUEBA (172.16.20.24)

   Ejecutar en SSMS con un usuario con permisos DELETE en GD_Archivo y
   GD_Grupo (usr_migracion_adjuntos solo tiene INSERT/SELECT).

   Que borra:
     - GD_Archivo insertados por la version anterior del servicio
       (placeholder PENDIENTE_DEFINIR / MIGRACION_PRUEBA / Codigo<>'WH').
     - GD_Grupo malformados (Orden NULL o GrupoTipo=0) que no tengan
       archivos ni grupos hijos. Hoja -> raiz en pasadas sucesivas.

   El reseteo de las tablas de control en MS_HASS_PROVEEDOR lo hace
   limpiar_datos_prueba.py --solo-reset (corre con usr_migracion_adjuntos).
   ===================================================================== */
USE HASS_SPRING_PRUEBA;
SET NOCOUNT ON;

-- ---------- 0) PREVIEW: lo que se va a borrar ----------
SELECT COUNT(*) AS archivos_placeholder_a_borrar
FROM dbo.GD_Archivo
WHERE UltimoUsuario = 'MIGRACION'
  AND (ValorTexto1 = 'PENDIENTE_DEFINIR'
       OR Descripcion = 'MIGRACION_PRUEBA'
       OR Codigo <> 'WH');

SELECT IdGrupo, IdGrupoPadre, NivelGrupo, Descripcion, Orden, GrupoTipo, Persona
FROM dbo.GD_Grupo
WHERE UltimoUsuario = 'MIGRACION' AND (Orden IS NULL OR GrupoTipo = 0);

-- ---------- 1) Borrar adjuntos placeholder ----------
BEGIN TRAN;
DELETE FROM dbo.GD_Archivo
WHERE UltimoUsuario = 'MIGRACION'
  AND (ValorTexto1 = 'PENDIENTE_DEFINIR'
       OR Descripcion = 'MIGRACION_PRUEBA'
       OR Codigo <> 'WH');
PRINT 'GD_Archivo borrados: ' + CAST(@@ROWCOUNT AS varchar(10));
COMMIT TRAN;

-- ---------- 2) Borrar grupos malformados sin archivos ni hijos ----------
DECLARE @pasada int = 0, @borrados int = 1, @total int = 0;
WHILE @pasada < 6 AND @borrados > 0
BEGIN
    DELETE g
    FROM dbo.GD_Grupo g
    WHERE g.UltimoUsuario = 'MIGRACION' AND (g.Orden IS NULL OR g.GrupoTipo = 0)
      AND NOT EXISTS (SELECT 1 FROM dbo.GD_Archivo a WHERE a.IdGrupo = g.IdGrupo)
      AND NOT EXISTS (SELECT 1 FROM dbo.GD_Grupo h WHERE h.IdGrupoPadre = g.IdGrupo);
    SET @borrados = @@ROWCOUNT;
    SET @total += @borrados;
    SET @pasada += 1;
END
PRINT 'GD_Grupo borrados: ' + CAST(@total AS varchar(10));

-- ---------- 3) Verificacion: ambos deben devolver 0 ----------
SELECT COUNT(*) AS placeholders_restantes
FROM dbo.GD_Archivo
WHERE UltimoUsuario = 'MIGRACION'
  AND (ValorTexto1 = 'PENDIENTE_DEFINIR'
       OR Descripcion = 'MIGRACION_PRUEBA'
       OR Codigo <> 'WH');

SELECT COUNT(*) AS grupos_malformados_restantes
FROM dbo.GD_Grupo
WHERE UltimoUsuario = 'MIGRACION' AND (Orden IS NULL OR GrupoTipo = 0);
