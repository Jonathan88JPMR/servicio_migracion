# -*- coding: utf-8 -*-
"""
Dashboard web de pruebas para el servicio de migración de adjuntos.
Soporta cambio dinamico de entornos desde tabla Entornos_Migracion.
Produccion bloqueada por defecto. Nunca expone SQL_PASSWORD.
"""
import os
import re
import io
import mimetypes
import threading
import subprocess
from collections import OrderedDict
from datetime import datetime
from typing import Optional

import pyodbc
from flask import Flask, render_template, request, jsonify, send_file

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
CONFIG_PATH = os.path.join(PROJECT_DIR, 'config_modo.bat')
CONFIG_ENV_PATH = os.path.join(PROJECT_DIR, 'config.env')
LOG_PATH = os.path.join(PROJECT_DIR, 'migrar_adjuntos_spring_prueba.log')
BATCH_PATH = os.path.join(PROJECT_DIR, 'iniciar_servicio.bat')

ENV_KEYS = [
    'MODO_SERVICIO', 'SERVIDOR_MS_HASS', 'BD_MS_HASS', 'SERVIDOR_SPRING', 'BD_SPRING',
    'RUTA_PRUEBA_LOCAL', 'RUTA_RAIZ', 'TIPO_COPIA_PRUEBA', 'MODO_PRUEBA',
    'BATCH_PRUEBA', 'BATCH_AP_DOCUMENTO_PRUEBA', 'TABLA_ADJUNTOS', 'USUARIO_MIGRACION', 'SQL_USER',
]


def parse_config_modo() -> dict:
    cfg = OrderedDict()
    if not os.path.exists(CONFIG_PATH):
        return cfg
    with open(CONFIG_PATH, 'r', encoding='latin-1') as f:
        for line in f:
            line = line.rstrip('\n')
            m = re.match(r'^set\s+"([^"]+)=([^"]*)"$', line)
            if m:
                cfg[m.group(1)] = m.group(2)
    return cfg


def save_config_modo(cfg: dict) -> None:
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f'No existe {CONFIG_PATH}')
    with open(CONFIG_PATH, 'r', encoding='latin-1') as f:
        lines = f.readlines()
    out = []
    for raw in lines:
        line = raw.rstrip('\n')
        m = re.match(r'^(set\s+")([^"]+)(=)([^"]*)"$', line)
        if m:
            key = m.group(2)
            if key in cfg:
                out.append(f'set "{key}={cfg[key]}"\n')
                continue
        out.append(raw)
    with open(CONFIG_PATH, 'w', encoding='latin-1') as f:
        f.writelines(out)


def parse_config_env() -> dict:
    cfg = OrderedDict()
    if not os.path.exists(CONFIG_ENV_PATH):
        return cfg
    with open(CONFIG_ENV_PATH, 'r', encoding='latin-1') as f:
        for line in f:
            line = line.rstrip('\n').strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                cfg[k.strip()] = v.strip()
    return cfg


def sql_password() -> str:
    return os.environ.get('SQL_PASSWORD', '')


def _mime_preview(nombre: str, mime: Optional[str] = None) -> str:
    m = mime or mimetypes.guess_type(nombre)[0] or 'application/octet-stream'
    if m and ('/xml' in m or m.endswith('+xml')):
        return 'text/plain'
    return m


def validate_config(cfg: dict) -> list[str]:
    errs = []
    modo = cfg.get('MODO_SERVICIO', '').upper()
    if modo == 'PRUEBA':
        if cfg.get('BD_SPRING', '').upper() != 'HASS_SPRING_PRUEBA':
            errs.append('BD_SPRING debe ser HASS_SPRING_PRUEBA')
        if cfg.get('RUTA_RAIZ', '') != r'\\172.16.20.24\SpringGestionDoc\PRUEBAS':
            errs.append('RUTA_RAIZ debe ser la ruta de pruebas')
    elif modo == 'PRODUCCION':
        if cfg.get('BD_SPRING', '').upper() != 'HP_SPRING_PRD':
            errs.append('BD_SPRING debe ser HP_SPRING_PRD')
        if cfg.get('RUTA_RAIZ', '') != r'\\172.16.20.24\SpringGestionDoc\PROD':
            errs.append('RUTA_RAIZ debe ser la ruta de producción')
    else:
        errs.append('MODO_SERVICIO debe ser PRUEBA o PRODUCCION')
    if cfg.get('TIPO_COPIA_PRUEBA', '').upper() not in ('LOCAL', 'COMPARTIDA'):
        errs.append('TIPO_COPIA_PRUEBA debe ser LOCAL o COMPARTIDA')
    if cfg.get('MODO_PRUEBA', '').upper() not in ('SIMULACION', 'ESCRITURA'):
        errs.append('MODO_PRUEBA debe ser SIMULACION o ESCRITURA')
    for k in ('BATCH_PRUEBA', 'BATCH_AP_DOCUMENTO_PRUEBA'):
        if not str(cfg.get(k, '')).isdigit():
            errs.append(f'{k} debe ser numérico')
    return errs


def connect_ms(cfg: dict) -> pyodbc.Connection:
    server = cfg.get('SERVIDOR_MS_HASS', '')
    database = cfg.get('BD_MS_HASS', '')
    uid = cfg.get('SQL_USER', '')
    pwd = sql_password()
    if not all((server, database, uid, pwd)):
        raise ValueError('Faltan datos de conexión al portal')
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};"
        f"DATABASE={database};UID={uid};PWD={pwd};"
    )


def connect_spring(cfg: dict) -> pyodbc.Connection:
    server = cfg.get('SERVIDOR_SPRING', '')
    database = cfg.get('BD_SPRING_PRUEBA', '') or cfg.get('BD_SPRING_PRODUCCION', '') or cfg.get('BD_SPRING', '')
    uid = cfg.get('SQL_USER', '')
    pwd = sql_password()
    if not all((server, database, uid, pwd)):
        raise ValueError('Faltan datos de conexión a Spring')
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};"
        f"DATABASE={database};UID={uid};PWD={pwd};"
    )


def _referencias_ap(cfg: dict, rows: list) -> None:
    """Agrega a cada fila el campo Referencias con las OC/OS relacionadas
    a la obligacion (factura) segun AP_Documentos en Spring."""
    claves = {
        (
            str(r.get('Proveedor') or '').strip(),
            str(r.get('ObligacionTipoDocumento') or '').strip(),
            str(r.get('ObligacionNumeroDocumento') or '').strip(),
        )
        for r in rows
    }
    claves.discard(('', '', ''))
    if not claves:
        return
    try:
        with connect_spring(cfg) as conn:
            cur = conn.cursor()
            conds = ' OR '.join(
                "(RTRIM(Proveedor) = ? AND RTRIM(ObligacionTipoDocumento) = ?"
                " AND RTRIM(ObligacionNumeroDocumento) = ?)"
                for _ in claves
            )
            params = [p for c in claves for p in c]
            cur.execute(f"""
                SELECT RTRIM(Proveedor) AS Proveedor,
                       RTRIM(ObligacionTipoDocumento) AS ObligacionTipoDocumento,
                       RTRIM(ObligacionNumeroDocumento) AS ObligacionNumeroDocumento,
                       RTRIM(ReferenciaTipoDocumento) AS ReferenciaTipoDocumento,
                       RTRIM(ReferenciaNumeroDocumento) AS ReferenciaNumeroDocumento
                FROM dbo.AP_Documentos
                WHERE {conds}
            """, params)
            ref_map = {}
            for prov, tipo_obl, num_obl, ref_tipo, ref_num in cur.fetchall():
                if ref_tipo and ref_num:
                    ref_map.setdefault((prov, tipo_obl, num_obl), set()).add(f'{ref_tipo} {ref_num}')
            for r in rows:
                key = (
                    str(r.get('Proveedor') or '').strip(),
                    str(r.get('ObligacionTipoDocumento') or '').strip(),
                    str(r.get('ObligacionNumeroDocumento') or '').strip(),
                )
                r['Referencias'] = ', '.join(sorted(ref_map.get(key, ())))
    except Exception:
        for r in rows:
            r.setdefault('Referencias', '')


def _claves_por_referencia(cfg: dict, claves: list, ref_tipo: str) -> Optional[set]:
    """Devuelve las claves (proveedor, tipo, numero) cuya obligacion tiene al
    menos un AP_Documentos con ReferenciaTipoDocumento = ref_tipo (OC/SO).
    Devuelve None si no se pudo consultar Spring."""
    encontradas = set()
    try:
        with connect_spring(cfg) as conn:
            cur = conn.cursor()
            chunk = 150
            for i in range(0, len(claves), chunk):
                grupo = claves[i:i + chunk]
                conds = ' OR '.join(
                    "(RTRIM(Proveedor) = ? AND RTRIM(ObligacionTipoDocumento) = ?"
                    " AND RTRIM(ObligacionNumeroDocumento) = ?)"
                    for _ in grupo
                )
                params = [ref_tipo] + [p for c in grupo for p in c]
                cur.execute(f"""
                    SELECT DISTINCT RTRIM(Proveedor), RTRIM(ObligacionTipoDocumento),
                           RTRIM(ObligacionNumeroDocumento)
                    FROM dbo.AP_Documentos
                    WHERE ReferenciaTipoDocumento = ? AND ({conds})
                """, params)
                for row in cur.fetchall():
                    encontradas.add((row[0], row[1], row[2]))
        return encontradas
    except Exception:
        return None


def _get_active_env(conn: pyodbc.Connection) -> str:
    cur = conn.cursor()
    try:
        cur.execute("SELECT TOP 1 Entorno FROM dbo.Config_Activo")
        row = cur.fetchone()
        return row[0] if row else 'PRUEBA'
    except Exception:
        return 'PRUEBA'


def _set_active_env(conn: pyodbc.Connection, entorno: str) -> None:
    cur = conn.cursor()
    cur.execute("""
        MERGE dbo.Config_Activo AS t
        USING (VALUES (1, ?)) AS s(Id, Entorno)
        ON t.Id = s.Id
        WHEN MATCHED THEN
            UPDATE SET Entorno = s.Entorno, FechaCambio = GETDATE()
        WHEN NOT MATCHED THEN
            INSERT (Id, Entorno) VALUES (s.Id, s.Entorno);
    """, (entorno,))
    conn.commit()


def _audit_entorno(conn: pyodbc.Connection, anterior: str, nuevo: str, ip: str) -> None:
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO dbo.Auditoria_Cambio_Entorno (EntornoAnterior, EntornoNuevo, Usuario, IP)
        VALUES (?, ?, ?, ?)
    """, (anterior, nuevo, 'dashboard', ip))
    conn.commit()


def _get_entornos(conn: pyodbc.Connection) -> list:
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT Entorno, Descripcion, ProduccionHabilitado
            FROM dbo.Entornos_Migracion
            WHERE Activo = 1
            ORDER BY Entorno
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        return [{'Entorno': 'PRUEBA', 'Descripcion': 'Pruebas (fallback)', 'ProduccionHabilitado': 0}]


def _get_env_config(conn: pyodbc.Connection, entorno: str) -> Optional[dict]:
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM dbo.Entornos_Migracion WHERE Entorno = ?", (entorno,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    except Exception:
        return None


def _update_env_config(conn: pyodbc.Connection, entorno: str, cfg: dict) -> None:
    cols = [k for k in ENV_KEYS if k in cfg and k != 'Entorno']
    if not cols:
        return
    set_clause = ', '.join(f'{c} = ?' for c in cols)
    vals = [str(cfg[c]) for c in cols] + [entorno]
    cur = conn.cursor()
    cur.execute(f"UPDATE dbo.Entornos_Migracion SET {set_clause} WHERE Entorno = ?", vals)
    conn.commit()


def _regenerar_archivos(conn: pyodbc.Connection, entorno: str) -> None:
    cfg = _get_env_config(conn, entorno) or {}
    if not cfg:
        return
    modo = cfg.get('MODO_SERVICIO', '').upper()
    if modo == 'PRUEBA':
        out = OrderedDict()
        for k in [
            'MODO_SERVICIO', 'TIPO_COPIA_PRUEBA', 'MODO_PRUEBA',
            'BATCH_PRUEBA', 'BATCH_AP_DOCUMENTO_PRUEBA',
            'SQL_USER', 'SERVIDOR_MS_HASS', 'BD_MS_HASS',
            'SERVIDOR_SPRING', 'TABLA_ADJUNTOS', 'USUARIO_MIGRACION',
        ]:
            out[k] = str(cfg.get(k, ''))
        out['BD_SPRING_PRUEBA'] = str(cfg.get('BD_SPRING', ''))
        out['RUTA_PRUEBA_LOCAL'] = str(cfg.get('RUTA_PRUEBA_LOCAL', ''))
        out['RUTA_RAIZ_PRUEBA'] = str(cfg.get('RUTA_RAIZ', ''))
        with open(CONFIG_PATH, 'w', encoding='latin-1') as f:
            f.write('@echo off\n')
            for k, v in out.items():
                f.write(f'set "{k}={v}"\n')
    elif modo == 'PRODUCCION':
        habilitado = 'SI_PRODUCCION' if cfg.get('ProduccionHabilitado') else 'NO'
        with open(CONFIG_ENV_PATH, 'w', encoding='latin-1') as f:
            f.write('# Configuracion de produccion generada por dashboard\n')
            f.write(f'MODO_SERVICIO=PRODUCCION\n')
            f.write(f'HABILITAR_PRODUCCION={habilitado}\n')
            f.write(f'SERVIDOR_MS_HASS={cfg.get("SERVIDOR_MS_HASS", "")}\n')
            f.write(f'BD_MS_HASS={cfg.get("BD_MS_HASS", "")}\n')
            f.write(f'SERVIDOR_SPRING={cfg.get("SERVIDOR_SPRING", "")}\n')
            f.write(f'BD_SPRING_PRODUCCION={cfg.get("BD_SPRING", "")}\n')
            f.write(f'RUTA_RAIZ_PRODUCCION={cfg.get("RUTA_RAIZ", "")}\n')
            f.write(f'SQL_USER={cfg.get("SQL_USER", "")}\n')


def get_activo_cfg() -> dict:
    base = parse_config_modo()
    base.setdefault('ENTORNO', 'PRUEBA')
    try:
        with connect_ms(base) as conn:
            entorno = _get_active_env(conn)
            db_cfg = _get_env_config(conn, entorno)
            if db_cfg:
                base = db_cfg.copy()
                base['ENTORNO'] = entorno
                modo = base.get('MODO_SERVICIO', '').upper()
                if modo == 'PRUEBA':
                    base['BD_SPRING_PRUEBA'] = base.get('BD_SPRING', '')
                    base['RUTA_RAIZ_PRUEBA'] = base.get('RUTA_RAIZ', '')
                elif modo == 'PRODUCCION':
                    base['BD_SPRING_PRODUCCION'] = base.get('BD_SPRING', '')
                    base['RUTA_RAIZ_PRODUCCION'] = base.get('RUTA_RAIZ', '')
    except Exception:
        pass
    return base


class RunManager:
    def __init__(self):
        self._runs = {}
        self._lock = threading.Lock()
        self._counter = 0

    def start(self, cmd: list, name: str, env=None, post_callback=None) -> str:
        with self._lock:
            self._counter += 1
            rid = f'run-{self._counter}'
            self._runs[rid] = {
                'id': rid,
                'name': name,
                'status': 'running',
                'exit_code': None,
                'output': [],
                'started': datetime.now().isoformat(),
                'finished': None,
            }

        def target():
            try:
                p = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    text=True,
                    encoding='latin-1',
                    errors='replace',
                    shell=False,
                )
                for line in iter(p.stdout.readline, ''):
                    if line:
                        self._runs[rid]['output'].append(line.rstrip('\n'))
                p.stdout.close()
                self._runs[rid]['exit_code'] = p.wait()
                self._runs[rid]['status'] = 'success' if self._runs[rid]['exit_code'] == 0 else 'error'
            except Exception as ex:
                self._runs[rid]['output'].append(f'[ERROR] {ex}')
                self._runs[rid]['status'] = 'error'
                self._runs[rid]['exit_code'] = -1
            finally:
                self._runs[rid]['finished'] = datetime.now().isoformat()
                if post_callback:
                    try:
                        post_callback()
                    except Exception as ex:
                        self._runs[rid]['output'].append(f'[POST_ERROR] {ex}')

        t = threading.Thread(target=target, daemon=True)
        t.start()
        return rid

    def get(self, rid: str) -> Optional[dict]:
        return self._runs.get(rid)


run_manager = RunManager()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/entornos', methods=['GET'])
def api_entornos():
    cfg = parse_config_modo()
    try:
        with connect_ms(cfg) as conn:
            return jsonify({'ok': True, 'entornos': _get_entornos(conn), 'activo': _get_active_env(conn)})
    except Exception as ex:
        return jsonify({'ok': True, 'entornos': [{'Entorno': 'PRUEBA', 'Descripcion': 'Pruebas (fallback)', 'ProduccionHabilitado': 0}], 'activo': 'PRUEBA'})


@app.route('/api/cambiar-entorno', methods=['POST'])
def api_cambiar_entorno():
    data = request.get_json(force=True, silent=True) or {}
    nuevo = data.get('entorno')
    if not nuevo:
        return jsonify({'ok': False, 'error': 'Falta entorno'}), 400
    cfg = parse_config_modo()
    try:
        with connect_ms(cfg) as conn:
            cfg_nuevo = _get_env_config(conn, nuevo)
            if not cfg_nuevo:
                return jsonify({'ok': False, 'error': f'Entorno {nuevo} no encontrado'}), 404
            if cfg_nuevo.get('MODO_SERVICIO', '').upper() == 'PRODUCCION' and not cfg_nuevo.get('ProduccionHabilitado'):
                return jsonify({'ok': False, 'error': 'Produccion no habilitada'}), 403
            anterior = _get_active_env(conn)
            _set_active_env(conn, nuevo)
            _regenerar_archivos(conn, nuevo)
            _audit_entorno(conn, anterior, nuevo, request.remote_addr or '')
            return jsonify({'ok': True, 'entorno_activo': nuevo})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/api/config', methods=['GET'])
def api_config():
    try:
        entornos = []
        activo = 'PRUEBA'
        with connect_ms(parse_config_modo()) as conn:
            entornos = _get_entornos(conn)
            activo = _get_active_env(conn)
    except Exception:
        pass
    cfg = get_activo_cfg()
    return jsonify({'ok': True, 'entorno_activo': activo, 'entornos': entornos, 'config': cfg})


@app.route('/api/config', methods=['POST'])
def api_config_post():
    updates = request.get_json(force=True, silent=True) or {}
    cfg = get_activo_cfg()
    entorno = cfg.get('ENTORNO', 'PRUEBA')
    for k, v in updates.items():
        if k in cfg:
            cfg[k] = str(v)
    errs = validate_config(cfg)
    if errs:
        return jsonify({'ok': False, 'errors': errs}), 400
    try:
        with connect_ms(parse_config_modo()) as conn:
            _update_env_config(conn, entorno, cfg)
            _regenerar_archivos(conn, entorno)
            return jsonify({'ok': True, 'entorno_activo': entorno})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/api/stats', methods=['GET'])
def api_stats():
    cfg = get_activo_cfg()
    try:
        with connect_ms(cfg) as conn_ms, connect_spring(cfg) as conn_spring:
            cur_ms = conn_ms.cursor()
            cur_sp = conn_spring.cursor()

            def q(cur, sql, params=None):
                if params is None:
                    params = ()
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

            def scalar(cur, sql, params=None):
                if params is None:
                    params = ()
                cur.execute(sql, params)
                row = cur.fetchone()
                return row[0] if row else 0

            ap_total = scalar(cur_ms, 'SELECT COUNT(*) FROM dbo.MS_AP_DocumentoArchivo')
            ap_gadatos = scalar(cur_ms, 'SELECT COUNT(*) FROM dbo.MS_AP_DocumentoArchivo WHERE Gadatos IS NOT NULL')
            ap_by_gatipo = q(cur_ms, """
                SELECT a.Gatipo, COUNT(*) as total,
                       ISNULL(SUM(CASE WHEN t.Estado = 'COMPLETADO' THEN 1 ELSE 0 END), 0) as completados
                FROM dbo.MS_AP_DocumentoArchivo a
                LEFT JOIN dbo.MS_AP_DocumentoArchivoTraslado t ON t.IdApDocumentoArchivo = a.IdApDocumentoArchivo
                GROUP BY a.Gatipo
                ORDER BY total DESC
            """)
            ap_by_estado = q(cur_ms, """
                SELECT Estado, COUNT(*) as total FROM dbo.MS_AP_DocumentoArchivoTraslado
                GROUP BY Estado ORDER BY total DESC
            """)
            ap_pending = scalar(cur_ms, """
                SELECT COUNT(*) FROM dbo.MS_AP_DocumentoArchivo a
                LEFT JOIN dbo.MS_AP_DocumentoArchivoTraslado t ON t.IdApDocumentoArchivo = a.IdApDocumentoArchivo
                WHERE a.Gadatos IS NOT NULL AND (t.IdApDocumentoArchivo IS NULL OR t.Estado IN ('PENDIENTE', 'ERROR'))
            """)
            ap_done = scalar(cur_ms, "SELECT COUNT(*) FROM dbo.MS_AP_DocumentoArchivoTraslado WHERE Estado = 'COMPLETADO'")

            ms_total = scalar(cur_ms, 'SELECT COUNT(*) FROM dbo.MS_Archivo')
            ms_by_estado = q(cur_ms, """
                SELECT ISNULL(t.Estado, 'SIN_CONTROL') as Estado, COUNT(*) as total
                FROM dbo.MS_Archivo a
                LEFT JOIN dbo.MS_ArchivoTraslado t ON t.IdArchivo = a.IdArchivo
                GROUP BY t.Estado
            """)
            ms_pending = scalar(cur_ms, """
                SELECT COUNT(*) FROM dbo.MS_Archivo a
                LEFT JOIN dbo.MS_ArchivoTraslado t ON t.IdArchivo = a.IdArchivo
                WHERE t.IdArchivo IS NULL OR t.Estado IN ('PENDIENTE', 'ERROR')
            """)
            ms_done = scalar(cur_ms, "SELECT COUNT(*) FROM dbo.MS_ArchivoTraslado WHERE Estado = 'COMPLETADO'")

            gd_count = scalar(cur_sp, """
                SELECT COUNT(*) FROM dbo.GD_Archivo
                WHERE RutaArchivo LIKE '%SpringGestionDoc\\PRUEBAS%'
            """)

            last_ap = q(cur_ms, "SELECT MAX(FechaTraslado) as fecha FROM dbo.MS_AP_DocumentoArchivoTraslado")[0]['fecha']
            last_ms = q(cur_ms, "SELECT MAX(FechaTraslado) as fecha FROM dbo.MS_ArchivoTraslado")[0]['fecha']

            return jsonify({
                'ok': True,
                'ap': {'total': ap_total, 'with_data': ap_gadatos, 'pending': ap_pending, 'done': ap_done,
                       'by_gatipo': ap_by_gatipo, 'by_estado': ap_by_estado},
                'ms': {'total': ms_total, 'pending': ms_pending, 'done': ms_done, 'by_estado': ms_by_estado},
                'gd_test': gd_count,
                'last_run': max(last_ap or '', last_ms or ''),
                'configured_batch': {
                    'BATCH_PRUEBA': int(cfg.get('BATCH_PRUEBA', 0)),
                    'BATCH_AP_DOCUMENTO_PRUEBA': int(cfg.get('BATCH_AP_DOCUMENTO_PRUEBA', 0)),
                },
            })
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/api/files', methods=['GET'])
def api_files():
    cfg = get_activo_cfg()
    tipo = request.args.get('tipo', 'ap').lower()
    estado = request.args.get('estado', '') or None
    gatipo = request.args.get('gatipo', '') or None
    ref = (request.args.get('ref', '') or '').strip().upper()
    if ref not in ('OC', 'SO'):
        ref = None
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(200, max(1, int(request.args.get('per_page', 25))))

    try:
        with connect_ms(cfg) as conn:
            cur = conn.cursor()
            if tipo == 'ap':
                where = "WHERE (t.Estado = ? OR ? IS NULL) AND (a.Gatipo = ? OR ? IS NULL)"
                if ref:
                    # El filtro OC/OS vive en AP_Documentos (Spring): se cruzan
                    # las claves de los candidatos antes de paginar.
                    cur.execute(f"""
                        SELECT t.IdApDocumentoArchivo,
                               RTRIM(a.Proveedor) AS Proveedor,
                               RTRIM(a.ObligacionTipoDocumento) AS ObligacionTipoDocumento,
                               RTRIM(a.ObligacionNumeroDocumento) AS ObligacionNumeroDocumento
                        FROM dbo.MS_AP_DocumentoArchivoTraslado t
                        JOIN dbo.MS_AP_DocumentoArchivo a ON a.IdApDocumentoArchivo = t.IdApDocumentoArchivo
                        {where}
                    """, [estado, estado, gatipo, gatipo])
                    candidatos = cur.fetchall()
                    claves = {
                        (str(r[1] or '').strip(), str(r[2] or '').strip(), str(r[3] or '').strip())
                        for r in candidatos
                    }
                    claves.discard(('', '', ''))
                    claves_ok = _claves_por_referencia(cfg, sorted(claves), ref)
                    if claves_ok is None:
                        return jsonify({'ok': False, 'error': 'No se pudo resolver el filtro OC/OS en AP_Documentos'}), 502
                    ids = sorted(
                        (r[0] for r in candidatos
                         if (str(r[1] or '').strip(), str(r[2] or '').strip(), str(r[3] or '').strip()) in claves_ok),
                        reverse=True)
                    total = len(ids)
                    page_ids = ids[(page - 1) * per_page: page * per_page]
                    rows = []
                    if page_ids:
                        marks = ','.join('?' * len(page_ids))
                        cur.execute(f"""
                            SELECT t.IdApDocumentoArchivo, a.Gatipo, a.Ganombre, a.Proveedor,
                                   a.ObligacionTipoDocumento,
                                   RTRIM(a.ObligacionNumeroDocumento) AS ObligacionNumeroDocumento,
                                   t.Estado, t.Intentos, t.Etapa, t.FechaPrimerIntento,
                                   t.FechaUltimoIntento, t.FechaTraslado, t.RutaDestino,
                                   t.IdGrupo, t.ArchivoId, t.MensajeError
                            FROM dbo.MS_AP_DocumentoArchivoTraslado t
                            JOIN dbo.MS_AP_DocumentoArchivo a ON a.IdApDocumentoArchivo = t.IdApDocumentoArchivo
                            WHERE t.IdApDocumentoArchivo IN ({marks})
                            ORDER BY t.IdApDocumentoArchivo DESC
                        """, page_ids)
                        cols = [d[0] for d in cur.description]
                        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                    _referencias_ap(cfg, rows)
                    return jsonify({'ok': True, 'rows': rows, 'total': total, 'page': page, 'per_page': per_page})
                count_sql = f"""
                    SELECT COUNT(*) FROM dbo.MS_AP_DocumentoArchivoTraslado t
                    JOIN dbo.MS_AP_DocumentoArchivo a ON a.IdApDocumentoArchivo = t.IdApDocumentoArchivo
                    {where}
                """
                cur.execute(count_sql, [estado, estado, gatipo, gatipo])
                total = cur.fetchone()[0]

                data_sql = f"""
                    WITH base AS (
                        SELECT
                            t.IdApDocumentoArchivo,
                            a.Gatipo,
                            a.Ganombre,
                            a.Proveedor,
                            a.ObligacionTipoDocumento,
                            RTRIM(a.ObligacionNumeroDocumento) as ObligacionNumeroDocumento,
                            t.Estado,
                            t.Intentos,
                            t.Etapa,
                            t.FechaPrimerIntento,
                            t.FechaUltimoIntento,
                            t.FechaTraslado,
                            t.RutaDestino,
                            t.IdGrupo,
                            t.ArchivoId,
                            t.MensajeError,
                            ROW_NUMBER() OVER (ORDER BY t.IdApDocumentoArchivo DESC) as rn
                        FROM dbo.MS_AP_DocumentoArchivoTraslado t
                        JOIN dbo.MS_AP_DocumentoArchivo a ON a.IdApDocumentoArchivo = t.IdApDocumentoArchivo
                        {where}
                    )
                    SELECT * FROM base WHERE rn BETWEEN ? AND ? ORDER BY rn
                """
                start = (page - 1) * per_page + 1
                end = start + per_page - 1
                cur.execute(data_sql, [estado, estado, gatipo, gatipo, start, end])
            else:
                where = "WHERE (t.Estado = ? OR ? IS NULL)"
                count_sql = f"""
                    SELECT COUNT(*) FROM dbo.MS_ArchivoTraslado t
                    JOIN dbo.MS_Archivo a ON a.IdArchivo = t.IdArchivo
                    {where}
                """
                cur.execute(count_sql, [estado, estado])
                total = cur.fetchone()[0]

                data_sql = f"""
                    WITH base AS (
                        SELECT
                            t.IdArchivo,
                            a.Tabla,
                            a.Id as IdRegistro,
                            a.Nombre,
                            a.Tipo as Mime,
                            t.Estado,
                            t.Intentos,
                            t.Etapa,
                            t.FechaTraslado,
                            t.RutaDestino,
                            t.ArchivoId,
                            t.MensajeError,
                            ROW_NUMBER() OVER (ORDER BY t.FechaTraslado DESC) as rn
                        FROM dbo.MS_ArchivoTraslado t
                        JOIN dbo.MS_Archivo a ON a.IdArchivo = t.IdArchivo
                        {where}
                    )
                    SELECT * FROM base WHERE rn BETWEEN ? AND ? ORDER BY rn
                """
                start = (page - 1) * per_page + 1
                end = start + per_page - 1
                cur.execute(data_sql, [estado, estado, start, end])

            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            if tipo == 'ap' and rows:
                _referencias_ap(cfg, rows)
            return jsonify({'ok': True, 'rows': rows, 'total': total, 'page': page, 'per_page': per_page})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/api/preview/ap/<int:id_ap>', methods=['GET'])
def api_preview_ap(id_ap: int):
    cfg = get_activo_cfg()
    try:
        with connect_ms(cfg) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT Ganombre, Gadatos FROM dbo.MS_AP_DocumentoArchivo WHERE IdApDocumentoArchivo = ?",
                (id_ap,)
            )
            row = cur.fetchone()
            if not row:
                return jsonify({'ok': False, 'error': 'No encontrado'}), 404
            nombre = row[0] or 'archivo.bin'
            datos = row[1]
            if isinstance(datos, bytearray):
                datos = bytes(datos)
            elif not isinstance(datos, bytes):
                datos = bytes(datos) if datos is not None else b''
            mime = _mime_preview(nombre)
            return send_file(
                io.BytesIO(datos),
                mimetype=mime,
                download_name=nombre,
                as_attachment=False,
            )
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/api/preview/ms/<id_archivo>', methods=['GET'])
def api_preview_ms(id_archivo: str):
    cfg = get_activo_cfg()
    try:
        with connect_ms(cfg) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT a.Nombre, a.Contenido, a.Tipo, t.Estado, t.RutaDestino
                FROM dbo.MS_Archivo a
                LEFT JOIN dbo.MS_ArchivoTraslado t ON t.IdArchivo = a.IdArchivo
                WHERE a.IdArchivo = ?
            """, (id_archivo,))
            row = cur.fetchone()
            if not row:
                return jsonify({'ok': False, 'error': 'No encontrado'}), 404
            nombre = row[0] or 'archivo.bin'
            datos = row[1]
            estado = row[3]
            ruta_destino = row[4]
            # Si ya fue copiado a pruebas, servir el archivo del disco para asegurar que el binario es correcto
            if estado == 'COMPLETADO' and ruta_destino and os.path.exists(ruta_destino):
                try:
                    with open(ruta_destino, 'rb') as f:
                        datos = f.read()
                except Exception:
                    datos = None
            if datos is None:
                if isinstance(row[1], bytearray):
                    datos = bytes(row[1])
                elif not isinstance(row[1], bytes):
                    datos = bytes(row[1]) if row[1] is not None else b''
            if not datos:
                return jsonify({'ok': False, 'error': 'El archivo no tiene contenido'}), 404
            if isinstance(datos, bytearray):
                datos = bytes(datos)
            mime = _mime_preview(nombre, row[2])
            return send_file(
                io.BytesIO(datos),
                mimetype=mime,
                download_name=nombre,
                as_attachment=False,
            )
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/api/log', methods=['GET'])
def api_log():
    tail = min(500, max(1, int(request.args.get('tail', 200))))
    if not os.path.exists(LOG_PATH):
        return jsonify({'ok': True, 'lines': []})
    try:
        with open(LOG_PATH, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 256 * 1024), os.SEEK_SET)
            chunk = f.read()
        text = chunk.decode('latin-1', errors='replace')
        lines = text.splitlines()
        return jsonify({'ok': True, 'lines': lines[-tail:]})
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500


@app.route('/api/run', methods=['POST'])
def api_run():
    cfg = get_activo_cfg()
    if cfg.get('MODO_SERVICIO', '').upper() != 'PRUEBA':
        return jsonify({'ok': False, 'error': 'Solo se puede ejecutar en modo PRUEBA desde el dashboard'}), 403
    errs = validate_config(cfg)
    if errs:
        return jsonify({'ok': False, 'errors': errs}), 400
    cmd = ['cmd', '/c', BATCH_PATH, 'PRUEBA']
    rid = run_manager.start(cmd, 'Ejecución manual', env=os.environ.copy())
    return jsonify({'ok': True, 'run_id': rid, 'name': 'Ejecución manual'})


@app.route('/api/run/all', methods=['POST'])
def api_run_all():
    cfg = get_activo_cfg()
    entorno = cfg.get('ENTORNO', 'PRUEBA')
    if cfg.get('MODO_SERVICIO', '').upper() != 'PRUEBA':
        return jsonify({'ok': False, 'error': 'Solo se puede ejecutar en modo PRUEBA desde el dashboard'}), 403
    try:
        with connect_ms(cfg) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM dbo.MS_Archivo a
                LEFT JOIN dbo.MS_ArchivoTraslado t ON t.IdArchivo = a.IdArchivo
                WHERE t.IdArchivo IS NULL OR t.Estado IN ('PENDIENTE', 'ERROR')
            """)
            ms_pending = int(cur.fetchone()[0])

            cur.execute("""
                SELECT COUNT(*) FROM dbo.MS_AP_DocumentoArchivo a
                LEFT JOIN dbo.MS_AP_DocumentoArchivoTraslado t ON t.IdApDocumentoArchivo = a.IdApDocumentoArchivo
                WHERE a.Gadatos IS NOT NULL AND (t.IdApDocumentoArchivo IS NULL OR t.Estado IN ('PENDIENTE', 'ERROR'))
            """)
            ap_pending = int(cur.fetchone()[0])

            # Actualizar lotes del entorno activo y regenerar config_modo.bat
            _update_env_config(conn, entorno, {
                'BATCH_PRUEBA': str(max(1, ms_pending)),
                'BATCH_AP_DOCUMENTO_PRUEBA': str(max(1, ap_pending)),
            })
            _regenerar_archivos(conn, entorno)
    except Exception as ex:
        return jsonify({'ok': False, 'error': f'No se pudo contar pendientes: {ex}'}), 500

    cmd = ['cmd', '/c', BATCH_PATH, 'PRUEBA']
    rid = run_manager.start(cmd, 'Procesar todo lo faltante', env=os.environ.copy())
    return jsonify({
        'ok': True,
        'run_id': rid,
        'name': 'Procesar todo lo faltante',
        'pending_ms': ms_pending,
        'pending_ap': ap_pending,
    })


def _obligaciones_por_referencia(conn_sp: pyodbc.Connection, numero: str, tipo: Optional[str]) -> set:
    sql = """
        SELECT DISTINCT RTRIM(Proveedor), RTRIM(ObligacionTipoDocumento),
               RTRIM(ObligacionNumeroDocumento)
        FROM dbo.AP_Documentos
        WHERE ReferenciaNumeroDocumento = ?
    """
    params = [numero]
    if tipo:
        sql += " AND ReferenciaTipoDocumento = ?"
        params.append(tipo)
    rows = conn_sp.cursor().execute(sql, params).fetchall()
    return {
        (str(r[0]).strip(), str(r[1]).strip(), str(r[2]).strip())
        for r in rows
        if all(x is not None for x in r)
    }


def _contar_pendientes_orden(conn_ms: pyodbc.Connection, numero: str, tipo: Optional[str], obligaciones: set) -> dict:
    cur = conn_ms.cursor()
    total_ap = 0
    lista = sorted(obligaciones)
    for i in range(0, len(lista), 150):
        grupo = lista[i:i + 150]
        conds = ' OR '.join(
            "(RTRIM(a.Proveedor) = ? AND RTRIM(a.ObligacionTipoDocumento) = ?"
            " AND RTRIM(a.ObligacionNumeroDocumento) = ?)"
            for _ in grupo
        )
        cur.execute(f"""
            SELECT COUNT(*) FROM dbo.MS_AP_DocumentoArchivo a
            LEFT JOIN dbo.MS_AP_DocumentoArchivoTraslado t ON t.IdApDocumentoArchivo = a.IdApDocumentoArchivo
            WHERE a.Gadatos IS NOT NULL
              AND (t.IdApDocumentoArchivo IS NULL OR t.Estado IN ('PENDIENTE', 'ERROR'))
              AND ({conds})
        """, [p for c in grupo for p in c])
        total_ap += cur.fetchone()[0]

    conds, params = [], []
    if tipo in (None, 'OC'):
        conds.append("(a.Tabla = 'WH_OrdenCompra' AND a.Id = ?)")
        params.append(numero)
    if tipo in (None, 'SO'):
        conds.append("(a.Tabla = 'Compromiso' AND a.Id = ?)")
        params.append(numero)
    ids_obl = [f'{p}|{t}|{n}' for p, t, n in lista]
    if ids_obl:
        marks = ','.join('?' * len(ids_obl))
        conds.append(f"(a.Tabla = 'Obligaciones' AND a.Id IN ({marks}))")
        params.extend(ids_obl)
    total_ms = 0
    if conds:
        cur.execute(f"""
            SELECT COUNT(*) FROM dbo.MS_Archivo a
            LEFT JOIN dbo.MS_ArchivoTraslado t ON t.IdArchivo = a.IdArchivo
            WHERE a.Contenido IS NOT NULL
              AND (t.IdArchivo IS NULL OR t.Estado IN ('PENDIENTE', 'ERROR'))
              AND ({' OR '.join(conds)})
        """, params)
        total_ms = cur.fetchone()[0]
    return {'ap': total_ap, 'ms': total_ms, 'total': total_ap + total_ms}


@app.route('/api/run/orden', methods=['POST'])
def api_run_orden():
    cfg = get_activo_cfg()
    if cfg.get('MODO_SERVICIO', '').upper() != 'PRUEBA':
        return jsonify({'ok': False, 'error': 'Solo se puede ejecutar en modo PRUEBA desde el dashboard'}), 403
    data = request.get_json(force=True, silent=True) or {}
    numero = (data.get('numero') or '').strip()
    tipo = (data.get('tipo') or '').strip().upper() or None
    if not re.fullmatch(r'[0-9A-Za-z\-]{1,30}', numero):
        return jsonify({'ok': False, 'error': 'Número de orden inválido (use dígitos, letras o guiones)'}), 400
    if tipo not in (None, 'OC', 'SO'):
        return jsonify({'ok': False, 'error': 'Tipo debe ser OC u OS'}), 400
    try:
        with connect_spring(cfg) as conn_sp, connect_ms(cfg) as conn_ms:
            obligaciones = _obligaciones_por_referencia(conn_sp, numero, tipo)
            pendientes = _contar_pendientes_orden(conn_ms, numero, tipo, obligaciones)
    except Exception as ex:
        return jsonify({'ok': False, 'error': str(ex)}), 500
    if not pendientes['total']:
        return jsonify({
            'ok': False,
            'error': f'No hay archivos pendientes para la orden {numero} '
                     f'(ya migrados o sin adjuntos nuevos). Obligaciones relacionadas: {len(obligaciones)}'
        }), 404
    env = os.environ.copy()
    env['SOLO_REFERENCIA'] = numero
    if tipo:
        env['SOLO_REFERENCIA_TIPO'] = tipo
    else:
        env.pop('SOLO_REFERENCIA_TIPO', None)
    rid = run_manager.start(['cmd', '/c', BATCH_PATH, 'PRUEBA'],
                            f'Procesar orden {tipo or "OC/OS"} {numero}', env=env)
    return jsonify({
        'ok': True,
        'run_id': rid,
        'name': f'Orden {numero}',
        'obligaciones': len(obligaciones),
        'pending_ap': pendientes['ap'],
        'pending_ms': pendientes['ms'],
    })


@app.route('/api/run/<rid>', methods=['GET'])
def api_run_status(rid: str):
    info = run_manager.get(rid)
    if not info:
        return jsonify({'ok': False, 'error': 'Ejecución no encontrada'}), 404
    return jsonify({'ok': True, **info})


if __name__ == '__main__':
    print('Dashboard de pruebas: http://127.0.0.1:5000')
    app.run(host='127.0.0.1', port=5000, debug=False)
