import os
import sys
import pyodbc

variables_requeridas = ("CONN_MS_HASS", "CONN_SPRING_PRUEBA")
faltantes = [nombre for nombre in variables_requeridas if not os.environ.get(nombre)]
if faltantes:
    print(f"[FALLO] Faltan variables de conexión: {', '.join(faltantes)}")
    sys.exit(1)

CONEXIONES = {
    "MS_HASS_PROVEEDOR": os.environ["CONN_MS_HASS"],
    "HASS_SPRING_PRUEBA": os.environ["CONN_SPRING_PRUEBA"],
}

print("Verificando conexiones...")
print("=" * 60)

exit_code = 0
for nombre, conn_str in CONEXIONES.items():
    try:
        conn = pyodbc.connect(conn_str, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT DB_NAME(), GETDATE()")
        db, fecha = cursor.fetchone()
        conn.close()
        print(f"[OK] {nombre}: conectado a '{db}' - {fecha}")
    except Exception as ex:
        print(f"[FALLO] {nombre}: {ex}")
        exit_code = 1

print("=" * 60)
if exit_code == 0:
    print("Todas las conexiones funcionan correctamente.")
else:
    print("Algunas conexiones fallaron. Revisa permisos o credenciales.")

sys.exit(exit_code)
