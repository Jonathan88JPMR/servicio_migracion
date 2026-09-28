import os
import re
import sys
import logging
from datetime import datetime

import pyodbc

# ---------------------------------------------------------------------------
# Script de PRODUCCION: migra adjuntos del portal de proveedores a Spring GD.
# Alineado con el patron real de GD_Grupo/GD_Archivo (ver docs/12_INFORME_CONFORMIDAD_GD.md):
#   - Nivel 6 = (numero de orden + proveedor), Fecha = fecha de la orden,
#     DescripcionLarga = razon social (PersonaMast), LastFlag='S', GrupoTipo=1.
#   - GD_Archivo: Codigo='WH', ValorTexto1 = tipo de orden (OC/SO).
#   - Control y reintentos: MS_ArchivoTraslado / MS_AP_DocumentoArchivoTraslado.
#   - Rango de fechas: solo se migran documentos con fecha de orden/documento
#     dentro de [FECHA_MINIMA, FECHA_MAXIMA] (env); los fuera de rango quedan
#     OMITIDO. 'TODOS'/'*' desactiva cada limite por separado.
#     FECHA_MINIMA vacia = 2026-01-01; FECHA_MAXIMA vacia = sin limite.
#     Ej. solo setiembre 2026: FECHA_MINIMA=2026-09-01 FECHA_MAXIMA=2026-09-30.
# ---------------------------------------------------------------------------


class FueraDeRango(Exception):
    """Documento con fecha de orden/documento fuera de [FECHA_MINIMA, FECHA_MAXIMA]."""


def _a_fecha(valor):
    """Normaliza datetime/date a date para comparar con el rango de migracion."""
    return valor.date() if isinstance(valor, datetime) else valor


_raw_fecha_min = os.environ.get("FECHA_MINIMA", "").strip()
if _raw_fecha_min.upper() in ("TODOS", "*"):
    FECHA_MINIMA = None
else:
    try:
        FECHA_MINIMA = datetime.strptime(_raw_fecha_min or "2026-01-01", "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit("FECHA_MINIMA debe tener formato YYYY-MM-DD o TODOS")

_raw_fecha_max = os.environ.get("FECHA_MAXIMA", "").strip()
if _raw_fecha_max.upper() in ("TODOS", "*", ""):
    FECHA_MAXIMA = None
else:
    try:
        FECHA_MAXIMA = datetime.strptime(_raw_fecha_max, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit("FECHA_MAXIMA debe tener formato YYYY-MM-DD o TODOS")

# Override por corrida: la API puede pasar SOLO_FECHA_MINIMA/SOLO_FECHA_MAXIMA
# (YYYY-MM-DD o TODOS) para ejecutar un rango sin tocar la config del entorno;
# el bat recarga FECHA_* desde el config, por eso se usan claves aparte.
_solo_min = os.environ.get("SOLO_FECHA_MINIMA", "").strip()
if _solo_min:
    if _solo_min.upper() in ("TODOS", "*"):
        FECHA_MINIMA = None
    else:
        try:
            FECHA_MINIMA = datetime.strptime(_solo_min, "%Y-%m-%d").date()
        except ValueError:
            raise SystemExit("SOLO_FECHA_MINIMA debe tener formato YYYY-MM-DD o TODOS")
_solo_max = os.environ.get("SOLO_FECHA_MAXIMA", "").strip()
if _solo_max:
    if _solo_max.upper() in ("TODOS", "*"):
        FECHA_MAXIMA = None
    else:
        try:
            FECHA_MAXIMA = datetime.strptime(_solo_max, "%Y-%m-%d").date()
        except ValueError:
            raise SystemExit("SOLO_FECHA_MAXIMA debe tener formato YYYY-MM-DD o TODOS")

PLANTILLAS_CACHE: dict[tuple[str, str | None], list[str] | None] = {}
MESES_ES = {
    1: "01-Enero", 2: "02-Febrero", 3: "03-Marzo", 4: "04-Abril",
    5: "05-Mayo", 6: "06-Junio", 7: "07-Julio", 8: "08-Agosto",
    9: "09-Setiembre", 10: "10-Octubre", 11: "11-Noviembre", 12: "12-Diciembre"
}
# Clasificacion funcional de GD_Archivo.Descripcion por Gatipo del portal.
# Pendiente de aprobacion funcional (ver docs/12_INFORME_CONFORMIDAD_GD.md).
CLASIFICACION_GATIPO = {
    "FAC": "FACTURA",
    "XML": "XML",
    "CDR": "CDR",
    "DIM": "SUSTENTO",
    "OTR": "SUSTENTO",
}
# GD_Archivo.ValorTexto1: OS para orden de servicio, OC para orden de compra.
# AP_Documentos registra el servicio como 'SO'; Spring GD lo muestra como 'OS'.
TIPO_ORDEN_GD = {"OC": "OC", "SO": "OS", "OS": "OS"}

BASE_DIR = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
LOG_PATH = os.path.join(BASE_DIR, "migrar_adjuntos_spring.log")


def _handlers_log(log_path: str) -> list:
    """FileHandler con fallback: si la cuenta que ejecuta (tarea, IIS, etc.) no
    tiene permiso en la carpeta del servicio, el log va a ProgramData o TEMP
    y nunca se pierde la salida por consola (la captura el dashboard)."""
    handlers = [logging.StreamHandler()]
    candidatos = [
        log_path,
        os.path.join(os.environ.get("ProgramData", BASE_DIR), "servicio_documentos", os.path.basename(log_path)),
        os.path.join(os.environ.get("TEMP", BASE_DIR), os.path.basename(log_path)),
    ]
    for candidato in candidatos:
        try:
            os.makedirs(os.path.dirname(candidato), exist_ok=True)
            handlers.insert(0, logging.FileHandler(candidato, encoding="utf-8"))
            if candidato != log_path:
                print(f"[WARN] Sin permiso en {log_path}; log redirigido a {candidato}")
            break
        except OSError:
            continue
    else:
        print(f"[WARN] No se pudo crear archivo de log; solo consola")
    return handlers


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=_handlers_log(LOG_PATH)
)


def conectar(connection_string: str) -> pyodbc.Connection:
    return pyodbc.connect(connection_string, timeout=30)


def adquirir_bloqueo_instancia(conn: pyodbc.Connection,
                               nombre: str = "MIGRACION_ADJUNTOS") -> bool:
    """Bloqueo de aplicacion por sesion (sp_getapplock): evita que dos
    instancias del servicio corran en paralelo y dupliquen GD_Archivo.
    Se libera al cerrar la conexion o al terminar el proceso."""
    row = conn.cursor().execute(
        "DECLARE @rc INT; EXEC @rc = sp_getapplock @Resource=?,"
        " @LockMode='Exclusive', @LockOwner='Session', @LockTimeout=0;"
        " SELECT @rc AS rc", nombre
    ).fetchone()
    return bool(row and row[0] >= 0)


# ---------------------------------------------------------------------------
# Lectura de adjuntos pendientes (tabla de control = "flag traslado en 0")
# ---------------------------------------------------------------------------
def obtener_adjuntos_pendientes(conn: pyodbc.Connection, tabla_adjuntos: str,
                                batch: int = 100, solo: dict | None = None):
    """Adjuntos sin traslado completado: sin registro de control o en
    PENDIENTE/ERROR. 'solo' limita a los adjuntos de una OC/OS."""
    params: list = []
    extra = ""
    if solo is not None:
        conds = []
        if solo["tipo"] in (None, "OC"):
            conds.append("(a.Tabla = 'WH_OrdenCompra' AND a.Id = ?)")
            params.append(solo["numero"])
        if solo["tipo"] in (None, "SO"):
            conds.append("(a.Tabla = 'Compromiso' AND a.Id = ?)")
            params.append(solo["numero"])
        ids_obl = sorted(f"{p}|{t}|{n}" for p, t, n in solo["obligaciones"])
        if ids_obl:
            marks = ",".join("?" * len(ids_obl))
            conds.append(f"(a.Tabla = 'Obligaciones' AND a.Id IN ({marks}))")
            params.extend(ids_obl)
        if not conds:
            return []
        extra = " AND (" + " OR ".join(conds) + ")"
        batch = max(batch, 100000)
    sql = f"""
        SELECT TOP {batch}
            a.IdArchivo, a.Id, a.Tabla, a.Nombre, a.Tipo, a.Contenido, a.Empresa,
            t.Estado, t.Intentos, t.Etapa, t.MensajeError
        FROM {tabla_adjuntos} AS a
        LEFT JOIN dbo.MS_ArchivoTraslado AS t ON t.IdArchivo = a.IdArchivo
        WHERE a.Contenido IS NOT NULL
          AND (t.IdArchivo IS NULL OR t.Estado IN ('PENDIENTE', 'ERROR')
               OR (t.Estado = 'SIN_AP' AND t.FechaUltimoIntento < DATEADD(hour, -24, GETDATE())))
          {extra}
        ORDER BY a.FechaCreacion DESC, a.IdArchivo DESC
    """
    return conn.cursor().execute(sql, params).fetchall()


def obtener_adjuntos_ap_pendientes(conn: pyodbc.Connection, batch: int = 100,
                                   obligaciones: set | None = None):
    """Archivos MS_AP_DocumentoArchivo sin traslado completado."""
    params: list = []
    extra = ""
    if obligaciones is not None:
        if not obligaciones:
            return []
        conds = " OR ".join(
            "(RTRIM(a.Proveedor) = ? AND RTRIM(a.ObligacionTipoDocumento) = ?"
            " AND RTRIM(a.ObligacionNumeroDocumento) = ?)"
            for _ in obligaciones
        )
        extra = f" AND ({conds})"
        params = [p for c in sorted(obligaciones) for p in c]
        batch = max(batch, 100000)
    sql = f"""
        SELECT TOP {batch}
            a.IdApDocumentoArchivo, a.Proveedor, a.ObligacionTipoDocumento,
            a.ObligacionNumeroDocumento, a.Gatipo, a.Ganombre, a.Gadatos,
            t.Estado, t.Intentos, t.Etapa, t.MensajeError
        FROM dbo.MS_AP_DocumentoArchivo AS a
        LEFT JOIN dbo.MS_AP_DocumentoArchivoTraslado AS t
          ON t.IdApDocumentoArchivo = a.IdApDocumentoArchivo
        WHERE a.Gadatos IS NOT NULL
          AND (t.IdApDocumentoArchivo IS NULL OR t.Estado IN ('PENDIENTE', 'ERROR')
               OR (t.Estado = 'SIN_AP' AND t.FechaUltimoIntento < DATEADD(hour, -24, GETDATE())))
          {extra}
        ORDER BY a.IdApDocumentoArchivo DESC
    """
    return conn.cursor().execute(sql, params).fetchall()


def obtener_obligaciones_por_referencia(conn_spring: pyodbc.Connection,
                                        numero_referencia: str,
                                        tipo_referencia: str | None = None) -> set:
    sql = """
        SELECT DISTINCT CAST(Proveedor AS VARCHAR(20)),
               RTRIM(ObligacionTipoDocumento),
               RTRIM(ObligacionNumeroDocumento)
        FROM AP_Documentos
        WHERE RTRIM(ReferenciaNumeroDocumento) = ?
    """
    params = [numero_referencia]
    if tipo_referencia:
        sql += " AND RTRIM(ReferenciaTipoDocumento) = ?"
        params.append(tipo_referencia)
    rows = conn_spring.cursor().execute(sql, params).fetchall()
    return {
        (str(r[0]).strip(), str(r[1]).strip(), str(r[2]).strip())
        for r in rows if all(x is not None for x in r)
    }


# ---------------------------------------------------------------------------
# Resolucion OC/OS + proveedor (orden + proveedor = clave del nivel 6)
# ---------------------------------------------------------------------------
def obtener_ap_documento_por_obligacion(conn_spring, proveedor, tipo_obligacion, numero_obligacion):
    sql = """
        SELECT TOP 1
            ReferenciaTipoDocumento, ReferenciaNumeroDocumento, RutaArchivo,
            Proveedor, CompaniaSocio, Fecha, DocumentoClasificacion, DocumentoReferencia
        FROM AP_Documentos
        WHERE CAST(Proveedor AS VARCHAR(20)) = ?
          AND RTRIM(ObligacionTipoDocumento) = ?
          AND RTRIM(ObligacionNumeroDocumento) = ?
    """
    return conn_spring.cursor().execute(sql, proveedor, tipo_obligacion, numero_obligacion).fetchone()


def obtener_ap_documento_por_referencia(conn_spring, tipo_doc: str, numero_doc: str):
    sql = """
        SELECT TOP 1
            ReferenciaTipoDocumento, ReferenciaNumeroDocumento, RutaArchivo,
            Proveedor, CompaniaSocio, Fecha, DocumentoClasificacion, DocumentoReferencia
        FROM AP_Documentos
        WHERE RTRIM(ReferenciaTipoDocumento) = ? AND RTRIM(ReferenciaNumeroDocumento) = ?
    """
    return conn_spring.cursor().execute(sql, tipo_doc, numero_doc).fetchone()


def _info_desde_ap(ap) -> dict:
    return {
        "tipo": ap.ReferenciaTipoDocumento.strip() if ap.ReferenciaTipoDocumento else None,
        "numero": ap.ReferenciaNumeroDocumento.strip() if ap.ReferenciaNumeroDocumento else None,
        "ruta_unc": ap.RutaArchivo.strip() if ap.RutaArchivo else None,
        "proveedor": ap.Proveedor,
        "compania": ap.CompaniaSocio.strip() if ap.CompaniaSocio else None,
        "fecha": ap.Fecha,
        "clasificacion": ap.DocumentoClasificacion.strip() if ap.DocumentoClasificacion else None,
        "referencia": ap.DocumentoReferencia.strip() if ap.DocumentoReferencia else None
    }


def resolver_oc_os(conn_spring: pyodbc.Connection, tabla: str, id_registro: str):
    """Devuelve dict con tipo/numero/ruta_unc/proveedor/compania/fecha o None."""
    if tabla == "Obligaciones":
        partes = id_registro.split("|")
        if len(partes) != 3:
            logging.warning(f"Id de Obligaciones no tiene formato esperado: {id_registro}")
            return None
        proveedor, tipo_obligacion, numero_obligacion = partes
        ap = obtener_ap_documento_por_obligacion(conn_spring, proveedor, tipo_obligacion, numero_obligacion)
        return _info_desde_ap(ap) if ap else None

    if tabla == "WH_OrdenCompra":
        ap = obtener_ap_documento_por_referencia(conn_spring, "OC", id_registro)
        if ap:
            return _info_desde_ap(ap)
        return {"tipo": "OC", "numero": id_registro, "ruta_unc": None, "proveedor": None, "compania": None}

    if tabla == "Compromiso":
        ap = obtener_ap_documento_por_referencia(conn_spring, "SO", id_registro)
        if ap:
            return _info_desde_ap(ap)
        return {"tipo": "SO", "numero": id_registro, "ruta_unc": None, "proveedor": None, "compania": None}

    return None


def _a_int(valor) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def obtener_datos_orden(conn_spring: pyodbc.Connection, tipo: str | None,
                        numero: str | None, proveedor: int | None):
    """(proveedor, fecha_orden) desde la tabla de la orden.
    OC -> WH_OrdenCompra.FechaPreparacion; SO -> Compromiso.FechaDocumento.
    El NumeroOrden se reutiliza entre proveedores: se filtra por Proveedor."""
    if not numero:
        return proveedor, None
    if tipo == "OC":
        sql = "SELECT TOP 1 Proveedor, FechaPreparacion FROM dbo.WH_OrdenCompra WHERE RTRIM(NumeroOrden) = ?"
    elif tipo in ("SO", "OS"):
        sql = "SELECT TOP 1 Proveedor, FechaDocumento FROM dbo.Compromiso WHERE RTRIM(NumeroCompromiso) = ?"
    else:
        return proveedor, None
    params: list = [numero]
    if proveedor is not None:
        sql += " AND Proveedor = ?"
        params.append(proveedor)
    row = conn_spring.cursor().execute(sql, params).fetchone()
    if not row:
        return proveedor, None
    return row[0], row[1]


def obtener_razon_social(conn_spring: pyodbc.Connection, proveedor: int | None) -> str | None:
    if proveedor is None:
        return None
    row = conn_spring.cursor().execute(
        "SELECT TOP 1 NombreCompleto FROM dbo.PersonaMast WHERE Persona = ?", proveedor
    ).fetchone()
    return row[0].strip() if row and row[0] else None


def enriquecer_info_orden(conn_spring: pyodbc.Connection, info: dict) -> dict:
    """proveedor_id / fecha_orden / razon_social para el nivel 6."""
    proveedor = _a_int(info.get("proveedor"))
    prov_orden, fecha_orden = obtener_datos_orden(
        conn_spring, info.get("tipo"), info.get("numero"), proveedor
    )
    if prov_orden is not None:
        proveedor = prov_orden
    info["proveedor_id"] = proveedor
    info["fecha_orden"] = fecha_orden or info.get("fecha")
    info["razon_social"] = obtener_razon_social(conn_spring, proveedor)
    return info


# ---------------------------------------------------------------------------
# Jerarquia de ruta UNC -> 6 niveles
# ---------------------------------------------------------------------------
def descomponer_ruta_spring(ruta_unc: str, segmento_raiz: str) -> list[str]:
    partes = [p for p in ruta_unc.replace("/", "\\").split("\\") if p]
    try:
        indice = next(i for i, p in enumerate(partes) if p.upper() == segmento_raiz.upper())
    except StopIteration as ex:
        raise ValueError(f"La ruta de Spring no contiene el segmento {segmento_raiz}: {ruta_unc}") from ex
    jerarquia = partes[indice + 1:indice + 7]
    if len(jerarquia) != 6:
        raise ValueError(f"La ruta de Spring no tiene los 6 niveles esperados: {ruta_unc}")
    if not jerarquia[2].upper().startswith("ORDEN"):
        logging.warning(f"[VALIDAR_RUTA] Nivel 3 no parece ser una orden: {jerarquia[2]}")
    if not any(p.isdigit() for p in jerarquia[4]) or not re.fullmatch(r"[0-9A-Za-z\-]+", jerarquia[5]):
        logging.warning(f"[VALIDAR_RUTA] Niveles 5/6 sin formato esperado: {jerarquia}")
    return jerarquia


def plantilla_ruta_por_compania(conn_spring: pyodbc.Connection, compania_socio: str,
                                referencia_tipo: str | None, segmento_raiz: str) -> list[str] | None:
    cache_key = (compania_socio, referencia_tipo)
    if cache_key in PLANTILLAS_CACHE:
        return PLANTILLAS_CACHE[cache_key]
    sql_tipo = """
        SELECT TOP 1 RutaArchivo FROM AP_Documentos
        WHERE RTRIM(CompaniaSocio) = ? AND RutaArchivo IS NOT NULL AND RTRIM(ReferenciaTipoDocumento) = ?
    """
    row = conn_spring.cursor().execute(sql_tipo, compania_socio, referencia_tipo).fetchone()
    if not row and referencia_tipo is not None:
        row = conn_spring.cursor().execute(
            "SELECT TOP 1 RutaArchivo FROM AP_Documentos WHERE CompaniaSocio = ? AND RutaArchivo IS NOT NULL",
            compania_socio
        ).fetchone()
    if not row:
        PLANTILLAS_CACHE[cache_key] = None
        return None
    try:
        jerarquia = descomponer_ruta_spring(row[0], segmento_raiz)
        PLANTILLAS_CACHE[cache_key] = jerarquia
        return jerarquia
    except Exception:
        PLANTILLAS_CACHE[cache_key] = None
        return None


def construir_ruta_dinamica(conn_spring: pyodbc.Connection, compania_socio: str,
                            referencia_tipo: str, numero_referencia: str,
                            fecha: datetime, segmento_raiz: str) -> list[str]:
    if not compania_socio or not referencia_tipo or not numero_referencia or not fecha:
        raise ValueError("Faltan datos para construir la ruta: compania, tipo, numero o fecha")
    plantilla = plantilla_ruta_por_compania(conn_spring, compania_socio, referencia_tipo, segmento_raiz) \
        or plantilla_ruta_por_compania(conn_spring, compania_socio, None, segmento_raiz)
    if not plantilla:
        raise ValueError(f"No existe una RutaArchivo de referencia para la compania {compania_socio}")
    if referencia_tipo == "OC":
        orden_tipo = "Orden Compra"
    elif referencia_tipo in ("SO", "OS"):
        orden_tipo = "Orden Servicio"
    else:
        orden_tipo = plantilla[2]
    mes = MESES_ES.get(fecha.month, f"{fecha.month:02d}")
    return [plantilla[0], plantilla[1], orden_tipo, str(fecha.year), mes, numero_referencia]


# ---------------------------------------------------------------------------
# GD_Grupo: busqueda/creacion de los 6 niveles (patron real de Spring)
# ---------------------------------------------------------------------------
def buscar_grupo_ruta(conn_gestion: pyodbc.Connection, jerarquia: list[str],
                      persona: int | None = None):
    """Recorre por (IdGrupoPadre, NivelGrupo, Descripcion); el nivel 6 valida
    tambien Persona (orden + proveedor). Devuelve (id_hoja, recorrido)."""
    padre = None
    recorrido = []
    for nivel, descripcion in enumerate(jerarquia, start=1):
        es_ultimo = nivel == len(jerarquia)
        if padre is None:
            sql = """
                SELECT TOP 1 IdGrupo, Orden FROM dbo.GD_Grupo
                WHERE IdGrupoPadre IS NULL AND NivelGrupo = ? AND Descripcion = ? AND Estado = 'A'
            """
            row = conn_gestion.cursor().execute(sql, nivel, descripcion).fetchone()
        elif es_ultimo and persona is not None:
            sql = """
                SELECT TOP 1 IdGrupo, Orden FROM dbo.GD_Grupo
                WHERE IdGrupoPadre = ? AND NivelGrupo = ? AND Descripcion = ? AND Estado = 'A'
                  AND (Persona = ? OR Persona IS NULL OR Persona = 0)
                ORDER BY CASE WHEN Persona = ? THEN 0 ELSE 1 END
            """
            row = conn_gestion.cursor().execute(sql, padre, nivel, descripcion, persona, persona).fetchone()
        else:
            sql = """
                SELECT TOP 1 IdGrupo, Orden FROM dbo.GD_Grupo
                WHERE IdGrupoPadre = ? AND NivelGrupo = ? AND Descripcion = ? AND Estado = 'A'
            """
            row = conn_gestion.cursor().execute(sql, padre, nivel, descripcion).fetchone()
        recorrido.append((nivel, descripcion, row[0] if row else None, row[1] if row else None))
        if not row:
            return None, recorrido
        padre = row[0]
    return padre, recorrido


def _siguiente_orden(cursor: pyodbc.Cursor, id_padre: int | None, orden_padre: str | None) -> str:
    """Orden = Orden del padre + posicion (4 digitos) entre hermanos."""
    if id_padre is None:
        row = cursor.execute(
            "SELECT MAX(TRY_CAST(RIGHT(Orden, 4) AS int)) FROM dbo.GD_Grupo WHERE IdGrupoPadre IS NULL"
        ).fetchone()
    else:
        row = cursor.execute(
            "SELECT MAX(TRY_CAST(RIGHT(Orden, 4) AS int)) FROM dbo.GD_Grupo WHERE IdGrupoPadre = ?",
            id_padre
        ).fetchone()
    posicion = (row[0] or 0) + 1
    return f"{posicion:04d}" if not orden_padre else f"{orden_padre}.{posicion:04d}"


def buscar_o_crear_jerarquia_gd_grupo(conn_gestion: pyodbc.Connection,
                                    jerarquia: list[str],
                                    usuario: str = "MIGRACION",
                                    meta: dict | None = None) -> int:
    """Busca la jerarquia; crea los niveles faltantes. meta lleva
    proveedor_id, razon_social y fecha_orden para el nivel 6."""
    meta = meta or {}
    persona = meta.get("proveedor_id")
    razon_social = meta.get("razon_social")
    fecha_orden = meta.get("fecha_orden")

    id_grupo, recorrido = buscar_grupo_ruta(conn_gestion, jerarquia, persona)
    if id_grupo:
        return id_grupo

    padre = None
    orden_padre = None
    nivel_inicial = 1
    for nivel, _, encontrado, orden in recorrido:
        if encontrado:
            padre = encontrado
            orden_padre = orden
            nivel_inicial = nivel + 1
        else:
            break

    if padre is None and nivel_inicial == 1:
        cursor = conn_gestion.cursor()
        raiz = cursor.execute(
            "SELECT TOP 1 IdGrupo, Orden FROM dbo.GD_Grupo WHERE IdGrupoPadre IS NULL AND NivelGrupo = 1 AND Descripcion = ? AND Estado = 'A'",
            jerarquia[0]
        ).fetchone()
        if raiz:
            padre, orden_padre, nivel_inicial = raiz[0], raiz[1], 2

    cursor = conn_gestion.cursor()
    next_id = cursor.execute(
        "SELECT COALESCE(MAX(IdGrupo), 0) + 1 FROM dbo.GD_Grupo WITH (TABLOCKX, HOLDLOCK)"
    ).fetchone()[0]

    for nivel in range(nivel_inicial, len(jerarquia) + 1):
        descripcion = jerarquia[nivel - 1]
        nuevo_id = next_id
        next_id += 1
        es_raiz = (padre is None and nivel == 1)
        es_hoja = (nivel == len(jerarquia))
        nuevo_orden = _siguiente_orden(cursor, padre, orden_padre)
        cursor.execute(
            """
            INSERT INTO dbo.GD_Grupo
            (IdGrupo, IdGrupoPadre, NivelGrupo, Descripcion, GrupoTipo, Orden,
             Raiz, EsPrincipal, Estado, UltimoUsuario, UltimaFechaModif,
             DescripcionLarga, ValorTexto, LastFlag, Persona, Fecha)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, 'A', ?, GETDATE(), ?, NULL, ?, ?, ?)
            """,
            nuevo_id, padre, nivel, descripcion, nuevo_orden,
            'S' if es_raiz else 'N', 'N' if es_raiz else None,
            usuario,
            razon_social if es_hoja else None,
            'S' if es_hoja else None,
            persona if es_hoja else None,
            fecha_orden if es_hoja else None
        )
        conn_gestion.commit()
        padre = nuevo_id
        orden_padre = nuevo_orden

    return padre


# ---------------------------------------------------------------------------
# Copia fisica e insercion en GD_Archivo
# ---------------------------------------------------------------------------
def _generar_nombre_unico(destino: str, contenido: bytes) -> str:
    carpeta, nombre = os.path.split(destino)
    base, ext = os.path.splitext(nombre)
    contador = 1
    while True:
        candidato = os.path.join(carpeta, f"{base}_{contador:03d}{ext}")
        if not os.path.exists(candidato):
            return candidato
        with open(candidato, "rb") as f:
            if f.read() == contenido:
                return candidato
        contador += 1


def guardar_archivo_unc(destino: str, contenido: bytes) -> tuple[str, int, bool]:
    """Crea carpetas, escribe y verifica. Devuelve (ruta_final, bytes, escrito)."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if os.path.exists(destino):
        with open(destino, "rb") as f:
            if f.read() == contenido:
                return destino, len(contenido), False
        destino = _generar_nombre_unico(destino, contenido)
    with open(destino, "wb") as f:
        f.write(contenido)
    tamano = os.path.getsize(destino)
    if tamano != len(contenido):
        raise IOError(f"Tamano diferente despues de copiar: origen={len(contenido)}, destino={tamano}")
    return destino, tamano, True


def insertar_gd_archivo(conn_gestion: pyodbc.Connection, id_grupo: int, codigo: str,
                        ruta_archivo: str, usuario: str,
                        valor_texto1: str | None = None,
                        descripcion: str | None = None) -> int:
    cursor = conn_gestion.cursor()
    # ArchivoId es PK manual (no IDENTITY).
    archivo_id = cursor.execute(
        "SELECT COALESCE(MAX(ArchivoId), 0) + 1 FROM dbo.GD_Archivo WITH (TABLOCKX, HOLDLOCK)"
    ).fetchone()[0]
    sql = """
        INSERT INTO dbo.GD_Archivo
        (ArchivoId, Codigo, Nombre, RutaArchivo, IdGrupo, ValorTexto1, ValorTexto2, ValorTexto3,
         Estado, UltimoUsuario, UltimaFechaModif, Archivo, Descripcion)
        OUTPUT INSERTED.ArchivoId
        VALUES (?, ?, NULL, ?, ?, ?, NULL, NULL, 'A', ?, GETDATE(), NULL, ?)
    """
    cursor.execute(sql, (archivo_id, codigo, ruta_archivo, id_grupo, valor_texto1, usuario, descripcion))
    return cursor.fetchone()[0]


# ---------------------------------------------------------------------------
# Tabla de control (portal): MS_ArchivoTraslado / MS_AP_DocumentoArchivoTraslado
# ---------------------------------------------------------------------------
def upsert_control_inicio(conn_ms: pyodbc.Connection, id_archivo: str, estado: str, etapa: str):
    sql = """
        MERGE dbo.MS_ArchivoTraslado AS t
        USING (VALUES (?)) AS s (IdArchivo)
        ON t.IdArchivo = s.IdArchivo
        WHEN MATCHED THEN UPDATE SET
            Estado = ?, Etapa = ?, MensajeError = NULL,
            FechaUltimoIntento = GETDATE(), Intentos = t.Intentos + 1
        WHEN NOT MATCHED THEN
            INSERT (IdArchivo, Estado, Intentos, Etapa, MensajeError,
                    RutaDestino, IdGrupo, ArchivoId, FechaPrimerIntento, FechaUltimoIntento)
            VALUES (?, ?, 1, ?, NULL, NULL, NULL, NULL, GETDATE(), GETDATE());
    """
    conn_ms.cursor().execute(sql, id_archivo, estado, etapa, id_archivo, estado, etapa)
    conn_ms.commit()


def actualizar_control(conn_ms: pyodbc.Connection, id_archivo: str, estado: str, etapa: str,
                       mensaje: str, ruta: str, id_grupo: int, archivo_id: int):
    if mensaje and len(mensaje) > 3900:
        mensaje = mensaje[:3900]
    sql = """
        UPDATE dbo.MS_ArchivoTraslado
        SET Estado = ?, Etapa = ?, MensajeError = ?, RutaDestino = ?,
            IdGrupo = ?, ArchivoId = ?, FechaUltimoIntento = GETDATE(),
            FechaTraslado = CASE WHEN ? = 'COMPLETADO' THEN GETDATE() ELSE FechaTraslado END
        WHERE IdArchivo = ?
    """
    conn_ms.cursor().execute(sql, estado, etapa, mensaje, ruta, id_grupo, archivo_id, estado, id_archivo)
    conn_ms.commit()


def upsert_control_inicio_ap(conn_ms: pyodbc.Connection, id_ap: int, gatipo: str, estado: str, etapa: str):
    sql = """
        MERGE dbo.MS_AP_DocumentoArchivoTraslado AS t
        USING (VALUES (?)) AS s (IdApDocumentoArchivo)
        ON t.IdApDocumentoArchivo = s.IdApDocumentoArchivo
        WHEN MATCHED THEN UPDATE SET
            Gatipo = ?, Estado = ?, Etapa = ?, MensajeError = NULL,
            FechaUltimoIntento = GETDATE(), Intentos = t.Intentos + 1
        WHEN NOT MATCHED THEN
            INSERT (IdApDocumentoArchivo, Gatipo, Estado, Intentos, Etapa, MensajeError,
                    RutaDestino, IdGrupo, ArchivoId, FechaPrimerIntento, FechaUltimoIntento)
            VALUES (?, ?, ?, 1, ?, NULL, NULL, NULL, NULL, GETDATE(), GETDATE());
    """
    conn_ms.cursor().execute(sql, id_ap, gatipo, estado, etapa, id_ap, gatipo, estado, etapa)
    conn_ms.commit()


def actualizar_control_ap(conn_ms: pyodbc.Connection, id_ap: int, gatipo: str, estado: str, etapa: str,
                          mensaje: str, ruta: str, id_grupo: int, archivo_id: int):
    if mensaje and len(mensaje) > 3900:
        mensaje = mensaje[:3900]
    sql = """
        UPDATE dbo.MS_AP_DocumentoArchivoTraslado
        SET Estado = ?, Etapa = ?, MensajeError = ?, RutaDestino = ?,
            IdGrupo = ?, ArchivoId = ?, FechaUltimoIntento = GETDATE(),
            FechaTraslado = CASE WHEN ? = 'COMPLETADO' THEN GETDATE() ELSE FechaTraslado END
        WHERE IdApDocumentoArchivo = ?
    """
    conn_ms.cursor().execute(sql, estado, etapa, mensaje, ruta, id_grupo, archivo_id, estado, id_ap)
    conn_ms.commit()


# ---------------------------------------------------------------------------
# Nucleo comun: resolver -> jerarquia -> copiar -> insertar -> control
# ---------------------------------------------------------------------------
def _procesar_adjunto(conn_ms, conn_spring, conn_gestion, ruta_raiz_prod: str,
                      segmento_raiz: str, info: dict, nombre: str, contenido: bytes,
                      usuario: str, clasificacion: str | None):
    """Ejecuta el flujo completo. Devuelve (id_grupo, ruta_destino, archivo_id)."""
    info = enriquecer_info_orden(conn_spring, info)
    if FECHA_MINIMA is not None or FECHA_MAXIMA is not None:
        fecha_ref = _a_fecha(info.get("fecha_orden") or info.get("fecha"))
        if fecha_ref is None:
            raise ValueError("Sin fecha de orden/documento para validar el rango de migracion")
        if FECHA_MINIMA is not None and fecha_ref < FECHA_MINIMA:
            raise FueraDeRango(f"Fecha {fecha_ref} anterior al corte {FECHA_MINIMA}")
        if FECHA_MAXIMA is not None and fecha_ref > FECHA_MAXIMA:
            raise FueraDeRango(f"Fecha {fecha_ref} posterior al limite {FECHA_MAXIMA}")
    logging.info("[RESOLVER] Tipo=%s Numero=%s Proveedor=%s FechaOrden=%s RazonSocial=%s",
                 info["tipo"], info["numero"], info.get("proveedor_id"),
                 info.get("fecha_orden"), info.get("razon_social"))

    if info["ruta_unc"]:
        jerarquia = descomponer_ruta_spring(info["ruta_unc"], segmento_raiz)
        ruta_final = os.path.normpath(os.path.join(info["ruta_unc"], nombre))
    else:
        fecha_jerarquia = info.get("fecha_orden") or info.get("fecha")
        jerarquia = construir_ruta_dinamica(
            conn_spring, info["compania"], info["tipo"], info["numero"], fecha_jerarquia, segmento_raiz
        )
        ruta_final = os.path.normpath(os.path.join(ruta_raiz_prod, *jerarquia, nombre))
    logging.info("[RUTA] %s", " > ".join(jerarquia))

    id_grupo = buscar_o_crear_jerarquia_gd_grupo(conn_gestion, jerarquia, usuario, meta=info)
    logging.info("[GD_GRUPO] IdGrupo=%s", id_grupo)

    ruta_destino, tamano, escrito = guardar_archivo_unc(ruta_final, contenido)
    logging.info("[COPIA] %s Bytes=%s Escrito=%s", ruta_destino, tamano, escrito)

    duplicado = conn_gestion.cursor().execute(
        "SELECT TOP 1 ArchivoId FROM dbo.GD_Archivo WITH (UPDLOCK, HOLDLOCK)"
        " WHERE IdGrupo = ? AND RutaArchivo = ?",
        id_grupo, ruta_destino
    ).fetchone()
    if duplicado:
        logging.info("[DUPLICADO] ArchivoId=%s ya existe; no se duplica", duplicado[0])
        return id_grupo, ruta_destino, duplicado[0]

    valor_texto1 = TIPO_ORDEN_GD.get(info.get("tipo"), info.get("tipo"))
    archivo_id = insertar_gd_archivo(
        conn_gestion, id_grupo, "WH", ruta_destino, usuario,
        valor_texto1=valor_texto1, descripcion=clasificacion
    )
    conn_gestion.commit()
    logging.info("[GD_ARCHIVO] ArchivoId=%s Codigo=WH ValorTexto1=%s Descripcion=%s",
                 archivo_id, valor_texto1, clasificacion)
    return id_grupo, ruta_destino, archivo_id


# ---------------------------------------------------------------------------
# Servicio principal
# ---------------------------------------------------------------------------
def migrar(conn_ms, conn_spring, conn_gestion, tabla_adjuntos: str,
           usuario: str, ruta_raiz_prod: str, batch: int = 100,
           solo: dict | None = None):
    segmento_raiz = os.path.normpath(ruta_raiz_prod).split(os.sep)[-1]
    adjuntos = obtener_adjuntos_pendientes(conn_ms, tabla_adjuntos, batch, solo)
    logging.info(f"[MS_Archivo] {len(adjuntos)} adjuntos pendientes de migrar")

    exitosos = fallidos = omitidos = 0
    for adjunto in adjuntos:
        id_archivo, id_registro, tabla, nombre, tipo, contenido, empresa, estado, intentos, etapa_prev, _err = adjunto
        etapa_actual = "INICIO"
        try:
            logging.info("[INICIO] IdArchivo=%s Tabla=%s Id=%s Nombre=%s", id_archivo, tabla, id_registro, nombre)
            upsert_control_inicio(conn_ms, id_archivo, "PROCESANDO", etapa_actual)

            etapa_actual = "RESOLVER_AP_DOCUMENTOS"
            info = resolver_oc_os(conn_spring, tabla.strip() if tabla else tabla,
                                  id_registro.strip() if id_registro else id_registro)
            if not info or not info["numero"]:
                sin_ap = (tabla == "Obligaciones"
                          and len(str(id_registro or "").split("|")) == 3)
                estado = "SIN_AP" if sin_ap else "ERROR"
                msg = ("Obligacion sin AP_Documentos en Spring (reintento en 24h)"
                       if sin_ap else "No se pudo resolver OC/OS")
                actualizar_control(conn_ms, id_archivo, estado, etapa_actual, msg, None, None, None)
                omitidos += 1
                logging.warning("[%s][%s] %s IdArchivo=%s", etapa_actual, estado, msg, id_archivo)
                continue

            id_grupo, ruta_destino, archivo_id = _procesar_adjunto(
                conn_ms, conn_spring, conn_gestion, ruta_raiz_prod, segmento_raiz,
                info, nombre, contenido, usuario, clasificacion=None
            )
            actualizar_control(conn_ms, id_archivo, "COMPLETADO", "COMPLETADO", None, ruta_destino, id_grupo, archivo_id)
            exitosos += 1
            logging.info("[EXITOSO] IdArchivo=%s -> %s (IdGrupo=%s, ArchivoId=%s)", id_archivo, ruta_destino, id_grupo, archivo_id)
        except FueraDeRango as ex:
            omitidos += 1
            logging.info("[OMITIDO] IdArchivo=%s %s", id_archivo, ex)
            try:
                actualizar_control(conn_ms, id_archivo, "OMITIDO", "VALIDAR_RANGO", str(ex), None, None, None)
            except Exception:
                actualizar_control(conn_ms, id_archivo, "ERROR", "VALIDAR_RANGO", str(ex), None, None, None)
        except Exception as ex:
            fallidos += 1
            msg = str(ex)
            logging.error("[FALLIDO][%s] IdArchivo=%s Error=%s", etapa_actual, id_archivo, ex, exc_info=True)
            try:
                conn_ms.rollback()
                conn_gestion.rollback()
            except Exception as rb:
                logging.error("[ROLLBACK][FALLIDO] %s", rb)
            actualizar_control(conn_ms, id_archivo, "ERROR", etapa_actual, msg, None, None, None)

    logging.info("[RESUMEN][MS_Archivo] total=%s exitosos=%s omitidos=%s fallidos=%s",
                 len(adjuntos), exitosos, omitidos, fallidos)


def migrar_ap_documento_archivo(conn_ms, conn_spring, conn_gestion,
                                usuario: str, ruta_raiz_prod: str, batch: int = 100,
                                solo_obligaciones: set | None = None):
    segmento_raiz = os.path.normpath(ruta_raiz_prod).split(os.sep)[-1]
    try:
        adjuntos = obtener_adjuntos_ap_pendientes(conn_ms, batch, solo_obligaciones)
    except pyodbc.ProgrammingError as ex:
        logging.error("[AP] No se encontro la tabla de control MS_AP_DocumentoArchivoTraslado: %s", ex)
        return
    logging.info("[AP] %s archivos pendientes de migrar", len(adjuntos))

    exitosos = fallidos = omitidos = 0
    for adjunto in adjuntos:
        id_ap, proveedor, tipo_obligacion, numero_obligacion, gatipo, ganombre, gadatos, estado, intentos, etapa_prev, _err = adjunto
        etapa_actual = "INICIO"
        try:
            logging.info("[AP][INICIO] IdAp=%s Proveedor=%s Obligacion=%s|%s Gatipo=%s Nombre=%s",
                         id_ap, proveedor, tipo_obligacion, numero_obligacion, gatipo, ganombre)
            upsert_control_inicio_ap(conn_ms, id_ap, gatipo, "PROCESANDO", etapa_actual)

            etapa_actual = "RESOLVER_AP_DOCUMENTOS"
            ap = obtener_ap_documento_por_obligacion(conn_spring, proveedor, tipo_obligacion, numero_obligacion)
            if not ap:
                actualizar_control_ap(conn_ms, id_ap, gatipo, "SIN_AP", etapa_actual,
                                      "Obligacion sin AP_Documentos en Spring (reintento en 24h)", None, None, None)
                omitidos += 1
                logging.warning("[AP][SIN_AP] Sin AP_Documentos para IdAp=%s", id_ap)
                continue
            info = _info_desde_ap(ap)
            clasificacion = CLASIFICACION_GATIPO.get((gatipo or "").strip().upper())

            id_grupo, ruta_destino, archivo_id = _procesar_adjunto(
                conn_ms, conn_spring, conn_gestion, ruta_raiz_prod, segmento_raiz,
                info, ganombre, gadatos, usuario, clasificacion
            )
            actualizar_control_ap(conn_ms, id_ap, gatipo, "COMPLETADO", "COMPLETADO", None, ruta_destino, id_grupo, archivo_id)
            exitosos += 1
            logging.info("[AP][EXITOSO] IdAp=%s -> %s (IdGrupo=%s, ArchivoId=%s)", id_ap, ruta_destino, id_grupo, archivo_id)
        except FueraDeRango as ex:
            omitidos += 1
            logging.info("[AP][OMITIDO] IdAp=%s %s", id_ap, ex)
            try:
                actualizar_control_ap(conn_ms, id_ap, gatipo, "OMITIDO", "VALIDAR_RANGO", str(ex), None, None, None)
            except Exception:
                actualizar_control_ap(conn_ms, id_ap, gatipo, "ERROR", "VALIDAR_RANGO", str(ex), None, None, None)
        except Exception as ex:
            fallidos += 1
            msg = str(ex)
            logging.error("[AP][FALLIDO][%s] IdAp=%s Error=%s", etapa_actual, id_ap, ex, exc_info=True)
            try:
                conn_ms.rollback()
                conn_gestion.rollback()
            except Exception as rb:
                logging.error("[AP][ROLLBACK][FALLIDO] %s", rb)
            actualizar_control_ap(conn_ms, id_ap, gatipo, "ERROR", etapa_actual, msg, None, None, None)

    logging.info("[RESUMEN][AP] total=%s exitosos=%s omitidos=%s fallidos=%s",
                 len(adjuntos), exitosos, omitidos, fallidos)


def _mask_connection_string(conn_str: str) -> str:
    return re.sub(r"(PWD|Password)=([^;]+)", r"\1=***", conn_str, flags=re.IGNORECASE)


if __name__ == "__main__":
    CONN_MS = os.environ.get(
        "CONN_MS_HASS",
        "DRIVER={ODBC Driver 17 for SQL Server};SERVER=172.16.20.25;DATABASE=MS_HASS_PROVEEDOR;Trusted_Connection=yes;"
    )
    CONN_SPRING = os.environ.get(
        "CONN_SPRING_PRODUCCION",
        "DRIVER={ODBC Driver 17 for SQL Server};SERVER=172.16.20.24;DATABASE=HP_SPRING_PRD;Trusted_Connection=yes;"
    )
    TABLA_ADJUNTOS = os.environ.get("TABLA_ADJUNTOS", "MS_Archivo")
    USUARIO = os.environ.get("USUARIO_MIGRACION", "MIGRACION")
    RUTA_RAIZ_PROD = os.environ.get("RUTA_RAIZ_PROD", r"\\172.16.20.24\SpringGestionDoc\PROD")
    BATCH = int(os.environ.get("BATCH_PRODUCCION", "100"))
    HABILITAR = os.environ.get("HABILITAR_PRODUCCION", "NO").strip().upper()

    if HABILITAR != "SI_PRODUCCION":
        raise SystemExit("Produccion deshabilitada. Definir HABILITAR_PRODUCCION=SI_PRODUCCION tras aprobar pruebas.")

    logging.info("=" * 60)
    logging.info("INICIO DE MIGRACION DE ADJUNTOS - PRODUCCION")
    logging.info(f"Rango de migracion: {FECHA_MINIMA or 'sin minimo'} .. "
                 f"{FECHA_MAXIMA or 'sin limite'} (fuera de rango -> OMITIDO)")
    logging.info(f"Tabla de adjuntos: {TABLA_ADJUNTOS}")
    logging.info(f"Usuario migracion: {USUARIO}")
    logging.info(f"Ruta raiz: {RUTA_RAIZ_PROD}")
    logging.info(f"Conexion MS_HASS: {_mask_connection_string(CONN_MS)}")
    logging.info(f"Conexion Spring: {_mask_connection_string(CONN_SPRING)}")
    logging.info("=" * 60)

    SOLO_REFERENCIA = os.environ.get("SOLO_REFERENCIA", "").strip()
    SOLO_TIPO = os.environ.get("SOLO_REFERENCIA_TIPO", "").strip().upper() or None
    if SOLO_TIPO not in (None, "OC", "SO"):
        raise SystemExit("SOLO_REFERENCIA_TIPO debe ser OC, SO o vacio")

    try:
        with conectar(CONN_MS) as conn_ms, \
             conectar(CONN_SPRING) as conn_spring:
            if not adquirir_bloqueo_instancia(conn_ms):
                logging.warning("Otra instancia de migracion esta en ejecucion; esta se omite.")
                raise SystemExit(0)
            solo = None
            if SOLO_REFERENCIA:
                obligaciones = obtener_obligaciones_por_referencia(conn_spring, SOLO_REFERENCIA, SOLO_TIPO)
                solo = {"numero": SOLO_REFERENCIA, "tipo": SOLO_TIPO, "obligaciones": obligaciones}
                logging.info("[FILTRO] Solo orden %s %s: %s obligaciones",
                             SOLO_TIPO or "OC/SO", SOLO_REFERENCIA, len(obligaciones))
            migrar(conn_ms, conn_spring, conn_spring, TABLA_ADJUNTOS, USUARIO, RUTA_RAIZ_PROD, BATCH, solo)
            migrar_ap_documento_archivo(conn_ms, conn_spring, conn_spring, USUARIO, RUTA_RAIZ_PROD, BATCH,
                                        solo_obligaciones=solo["obligaciones"] if solo else None)
        logging.info("Migracion finalizada correctamente.")
    except Exception as ex:
        logging.error(f"La migracion fallo de forma general: {ex}", exc_info=True)
        raise
