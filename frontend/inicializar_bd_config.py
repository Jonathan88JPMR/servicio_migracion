# -*- coding: utf-8 -*-
"""
Carga/actualiza los presets de entornos en MS_HASS_PROVEEDOR.
Las tablas deben existir previamente (ejecutar crear_tablas_entornos.sql con admin).
Requiere SQL_PASSWORD en el entorno.
"""
import os
import re
import pyodbc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
CONFIG_PATH = os.path.join(PROJECT_DIR, 'config_modo.bat')


def parse_config_modo():
    cfg = {}
    with open(CONFIG_PATH, 'r', encoding='latin-1') as f:
        for line in f:
            m = re.match(r'^set\s+"([^"]+)=([^"]*)"$', line.strip())
            if m:
                cfg[m.group(1)] = m.group(2)
    return cfg


def main():
    cfg = parse_config_modo()
    server = cfg.get('SERVIDOR_MS_HASS')
    db = cfg.get('BD_MS_HASS')
    uid = cfg.get('SQL_USER')
    pwd = os.environ.get('SQL_PASSWORD', '')
    if not all((server, db, uid, pwd)):
        print('[ERROR] Faltan datos de conexión o SQL_PASSWORD')
        return

    conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};"
        f"DATABASE={db};UID={uid};PWD={pwd};"
    )
    cur = conn.cursor()

    # Verificar tablas
    for tabla in ('Entornos_Migracion', 'Config_Activo', 'Auditoria_Cambio_Entorno'):
        cur.execute("SELECT COUNT(*) FROM sys.tables WHERE name = ?", (tabla,))
        if cur.fetchone()[0] == 0:
            print(f'[ERROR] La tabla {tabla} no existe.')
            print('[INFO] Ejecuta frontend/crear_tablas_entornos.sql con una cuenta admin primero.')
            return

    cur.execute("SELECT COUNT(*) FROM dbo.Entornos_Migracion WHERE Entorno = 'PRUEBA'")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO dbo.Entornos_Migracion (
                Entorno, Descripcion, MODO_SERVICIO, SERVIDOR_MS_HASS, BD_MS_HASS,
                SERVIDOR_SPRING, BD_SPRING, RUTA_PRUEBA_LOCAL, RUTA_RAIZ,
                TIPO_COPIA_PRUEBA, MODO_PRUEBA, BATCH_PRUEBA, BATCH_AP_DOCUMENTO_PRUEBA,
                TABLA_ADJUNTOS, USUARIO_MIGRACION, SQL_USER, FECHA_MINIMA, FECHA_MAXIMA,
                ProduccionHabilitado, Activo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'PRUEBA', 'Entorno de pruebas HASS_SPRING_PRUEBA',
            cfg.get('MODO_SERVICIO', 'PRUEBA'),
            cfg.get('SERVIDOR_MS_HASS', ''),
            cfg.get('BD_MS_HASS', ''),
            cfg.get('SERVIDOR_SPRING', ''),
            cfg.get('BD_SPRING_PRUEBA', ''),
            cfg.get('RUTA_PRUEBA_LOCAL', ''),
            cfg.get('RUTA_RAIZ_PRUEBA', ''),
            cfg.get('TIPO_COPIA_PRUEBA', ''),
            cfg.get('MODO_PRUEBA', ''),
            cfg.get('BATCH_PRUEBA', ''),
            cfg.get('BATCH_AP_DOCUMENTO_PRUEBA', ''),
            cfg.get('TABLA_ADJUNTOS', ''),
            cfg.get('USUARIO_MIGRACION', ''),
            cfg.get('SQL_USER', ''),
            None, None,
            0, 1
        ))
        conn.commit()
        print('[OK] Preset PRUEBA creado')
    else:
        print('[INFO] Preset PRUEBA ya existe')

    cur.execute("SELECT COUNT(*) FROM dbo.Entornos_Migracion WHERE Entorno = 'PRODUCCION'")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO dbo.Entornos_Migracion (
                Entorno, Descripcion, MODO_SERVICIO, SERVIDOR_MS_HASS, BD_MS_HASS,
                SERVIDOR_SPRING, BD_SPRING, RUTA_PRUEBA_LOCAL, RUTA_RAIZ,
                TIPO_COPIA_PRUEBA, MODO_PRUEBA, BATCH_PRUEBA, BATCH_AP_DOCUMENTO_PRUEBA,
                TABLA_ADJUNTOS, USUARIO_MIGRACION, SQL_USER, FECHA_MINIMA, FECHA_MAXIMA,
                ProduccionHabilitado, Activo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'PRODUCCION', 'Entorno de produccion HP_SPRING_PRD',
            'PRODUCCION',
            cfg.get('SERVIDOR_MS_HASS', ''),
            cfg.get('BD_MS_HASS', ''),
            cfg.get('SERVIDOR_SPRING', ''),
            'HP_SPRING_PRD',
            '',
            r'\\172.16.20.24\SpringGestionDoc\PROD',
            'COMPARTIDA',
            'ESCRITURA',
            '0', '0',
            'MS_Archivo',
            'MIGRACION',
            cfg.get('SQL_USER', ''),
            '2026-09-01', '2026-09-30',
            0, 1
        ))
        conn.commit()
        print('[OK] Preset PRODUCCION creado (bloqueado)')
    else:
        print('[INFO] Preset PRODUCCION ya existe')

    cur.execute("SELECT COUNT(*) FROM dbo.Config_Activo")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO dbo.Config_Activo (Id, Entorno) VALUES (1, 'PRUEBA')")
        conn.commit()
        print('[OK] Entorno activo: PRUEBA')
    else:
        print('[INFO] Config_Activo ya existe')

    cur.close()
    conn.close()
    print('[OK] Inicialización completa')


if __name__ == '__main__':
    main()
