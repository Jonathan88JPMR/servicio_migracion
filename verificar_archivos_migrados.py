import os
import pyodbc

CONN_SPRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER=172.16.20.24;"
    "DATABASE=HP_SPRING_PRD;UID=usr_migracion_adjuntos;"
    f"PWD={os.environ['SQL_PASSWORD']};"
)

conn = pyodbc.connect(CONN_SPRING, timeout=30)
rows = conn.cursor().execute(
    "SELECT ArchivoId, RutaArchivo FROM dbo.GD_Archivo"
    " WHERE Codigo = 'WH' AND UltimoUsuario = 'MIGRACION'"
).fetchall()

ok = vacios = inexistentes = 0
problemas = []
for archivo_id, ruta in rows:
    if not ruta:
        inexistentes += 1
        problemas.append((archivo_id, "SIN_RUTA", ""))
        continue
    if not os.path.exists(ruta):
        inexistentes += 1
        problemas.append((archivo_id, "NO_EXISTE", ruta))
        continue
    tam = os.path.getsize(ruta)
    if tam == 0:
        vacios += 1
        problemas.append((archivo_id, "CERO_BYTES", ruta))
    else:
        ok += 1

print(f"Total registros MIGRACION: {len(rows)}")
print(f"OK (>0 bytes): {ok}")
print(f"Cero bytes: {vacios}")
print(f"No existe / sin ruta: {inexistentes}")
for aid, motivo, ruta in problemas:
    print(f"  [{motivo}] ArchivoId={aid} {ruta}")
