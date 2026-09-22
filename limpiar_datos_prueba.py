"""Limpieza de datos de prueba en HASS_SPRING_PRUEBA.

Borra los GD_Archivo/GD_Grupo insertados por la version anterior del servicio
(placeholder 'PENDIENTE_DEFINIR'/'MIGRACION_PRUEBA'/Codigo<>'WH' y grupos con
Orden NULL o GrupoTipo=0) y resetea en MS_HASS_PROVEEDOR las filas de control
afectadas a PENDIENTE para que se re-migren con el formato correcto.

Uso:
    set SQL_PASSWORD=***
    python limpiar_datos_prueba.py              # solo muestra (dry-run)
    python limpiar_datos_prueba.py --ejecutar   # aplica los borrados + reset
    python limpiar_datos_prueba.py --solo-reset # solo resetea controles en MS

Nota: usr_migracion_adjuntos tiene INSERT/SELECT en GD_* pero NO DELETE.
Los DELETE de GD_Archivo/GD_Grupo deben correrlos un usuario con permisos
(script limpiar_datos_prueba.sql en SSMS). --solo-reset solo necesita UPDATE
en las tablas de control del portal, que si esta concedido.
"""
import os
import sys

import pyodbc

SOLO_RESET = "--solo-reset" in sys.argv
DRY_RUN = "--ejecutar" not in sys.argv and not SOLO_RESET

CONN_MS = (
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER=172.16.20.25;"
    "DATABASE=MS_HASS_PROVEEDOR;UID=usr_migracion_adjuntos;PWD=" + os.environ["SQL_PASSWORD"] + ";"
)
CONN_SPRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER=172.16.20.24;"
    "DATABASE=HASS_SPRING_PRUEBA;UID=usr_migracion_adjuntos;PWD=" + os.environ["SQL_PASSWORD"] + ";"
)

FILTRO_ARCHIVO_VIEJO = (
    "UltimoUsuario='MIGRACION' AND "
    "(ValorTexto1='PENDIENTE_DEFINIR' OR Descripcion='MIGRACION_PRUEBA' OR Codigo<>'WH')"
)
FILTRO_GRUPO_VIEJO = "UltimoUsuario='MIGRACION' AND (Orden IS NULL OR GrupoTipo=0)"


def main():
    with pyodbc.connect(CONN_SPRING, timeout=30) as sp, \
         pyodbc.connect(CONN_MS, timeout=30) as ms:
        cur = sp.cursor()

        archivo_ids = [r[0] for r in cur.execute(
            f"SELECT ArchivoId FROM GD_Archivo WHERE {FILTRO_ARCHIVO_VIEJO}"
        ).fetchall()]
        grupo_ids = [r[0] for r in cur.execute(
            f"SELECT IdGrupo FROM GD_Grupo WHERE {FILTRO_GRUPO_VIEJO}"
        ).fetchall()]

        print(f"[PREVIEW] GD_Archivo placeholder a borrar : {len(archivo_ids)}")
        print(f"[PREVIEW] GD_Grupo malformados a borrar   : {len(grupo_ids)} -> {grupo_ids}")

        if DRY_RUN:
            print("[DRY-RUN] Sin cambios. Ejecutar con --ejecutar o --solo-reset.")
            return

        if SOLO_RESET:
            print("[MODO] --solo-reset: no se borra nada en Spring, solo se resetean controles.")
        else:
            # 1) Borrar adjuntos placeholder
            cur.execute(f"DELETE FROM GD_Archivo WHERE {FILTRO_ARCHIVO_VIEJO}")
            borrados_archivos = cur.rowcount
            sp.commit()
            print(f"[OK] GD_Archivo borrados: {borrados_archivos}")

            # 2) Borrar grupos malformados (hoja -> raiz por si hay niveles intermedios)
            total_grupos = 0
            for _ in range(6):
                cur.execute("""
                    DELETE g FROM GD_Grupo g
                    WHERE g.UltimoUsuario='MIGRACION' AND (g.Orden IS NULL OR g.GrupoTipo=0)
                      AND NOT EXISTS (SELECT 1 FROM GD_Archivo a WHERE a.IdGrupo = g.IdGrupo)
                      AND NOT EXISTS (SELECT 1 FROM GD_Grupo h WHERE h.IdGrupoPadre = g.IdGrupo)
                """)
                total_grupos += cur.rowcount
                if cur.rowcount == 0:
                    break
            sp.commit()
            print(f"[OK] GD_Grupo borrados: {total_grupos}")

        # 3) Resetear controles en el portal para re-migrar con formato correcto
        if archivo_ids:
            marks = ",".join("?" * len(archivo_ids))
            reset_sql = """
                UPDATE {t}
                SET Estado='PENDIENTE', Etapa='REPROCESAR', MensajeError=NULL,
                    RutaDestino=NULL, IdGrupo=NULL, ArchivoId=NULL, FechaTraslado=NULL
                WHERE ArchivoId IN ({marks})
            """
            for tabla in ("MS_AP_DocumentoArchivoTraslado", "MS_ArchivoTraslado"):
                n = ms.cursor().execute(
                    reset_sql.format(t=tabla, marks=marks), archivo_ids
                ).rowcount
                ms.commit()
                print(f"[OK] {tabla} reseteadas a PENDIENTE: {n}")

        print("[FIN] Limpieza completada.")


if __name__ == "__main__":
    main()
