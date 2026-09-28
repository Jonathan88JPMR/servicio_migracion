/* =====================================================================
   Limpieza TOTAL de datos de prueba - HASS_SPRING_PRUEBA (172.16.20.24)

   A diferencia de limpiar_datos_prueba.sql (que solo quitaba filas
   placeholder de la version antigua), este borra TODO lo que el servicio
   escribio durante las pruebas ESCRITURA:

     - GD_Archivo con UltimoUsuario='MIGRACION' apuntando a ...\PRUEBAS\
     - GD_Grupo creados por MIGRACION que queden sin archivos ni hijos
       (hoja -> raiz, hasta 6 pasadas)

   Ejecutar con un usuario con DELETE en GD_* (usr_migracion_adjuntos
   solo tiene INSERT/SELECT). El reseteo de las tablas de control del
   portal va aparte: preparar_paso_produccion.sql (PASO 2).

   Los archivos fisicos bajo \\172.16.20.24\SpringGestionDoc\PRUEBAS
   se borran a mano o con robocopy; no se tocan aqui.
   ===================================================================== */
USE HASS_SPRING_PRUEBA;
SET NOCOUNT ON;

-- ---------- 0) PREVIEW ----------
SELECT COUNT(*) AS gd_archivo_prueba
FROM dbo.GD_Archivo
WHERE UltimoUsuario = 'MIGRACION' AND RutaArchivo LIKE '%\PRUEBAS\%';

SELECT COUNT(*) AS gd_grupo_migracion
FROM dbo.GD_Grupo WHERE UltimoUsuario = 'MIGRACION';

-- ---------- 1) GD_Archivo de prueba ----------
BEGIN TRAN;
DELETE FROM dbo.GD_Archivo
WHERE UltimoUsuario = 'MIGRACION' AND RutaArchivo LIKE '%\PRUEBAS\%';
PRINT 'GD_Archivo borrados: ' + CAST(@@ROWCOUNT AS varchar(10));
-- Revisar el conteo antes de confirmar:
COMMIT TRAN;  -- o ROLLBACK TRAN para abortar

-- ---------- 2) GD_Grupo creados por pruebas (hoja -> raiz) ----------
DECLARE @pasada int = 0, @borrados int = 1, @total int = 0;
WHILE @pasada < 6 AND @borrados > 0
BEGIN
    DELETE g
    FROM dbo.GD_Grupo g
    WHERE g.UltimoUsuario = 'MIGRACION'
      AND NOT EXISTS (SELECT 1 FROM dbo.GD_Archivo a WHERE a.IdGrupo = g.IdGrupo)
      AND NOT EXISTS (SELECT 1 FROM dbo.GD_Grupo h WHERE h.IdGrupoPadre = g.IdGrupo);
    SET @borrados = @@ROWCOUNT;
    SET @total += @borrados;
    SET @pasada += 1;
END
PRINT 'GD_Grupo borrados: ' + CAST(@total AS varchar(10));

-- ---------- 3) Verificacion: ambos deben quedar en 0 ----------
SELECT COUNT(*) AS gd_archivo_prueba_restantes
FROM dbo.GD_Archivo
WHERE UltimoUsuario = 'MIGRACION' AND RutaArchivo LIKE '%\PRUEBAS\%';

SELECT COUNT(*) AS gd_grupo_migracion_restantes
FROM dbo.GD_Grupo g
WHERE g.UltimoUsuario = 'MIGRACION'
  AND NOT EXISTS (SELECT 1 FROM dbo.GD_Archivo a WHERE a.IdGrupo = g.IdGrupo)
  AND NOT EXISTS (SELECT 1 FROM dbo.GD_Grupo h WHERE h.IdGrupoPadre = g.IdGrupo);
GO
