import os
import re
import sys
import logging
from datetime import datetime
from pathlib import Path

import pyodbc

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

# ---------------------------------------------------------------------------
# Script de PRUEBA para validar el flujo de migracion de adjuntos del portal.
# No marca FlagTraslado ni escribe en GD_Grupo/GD_Archivo a menos que se fuerce.
# Copia los archivos a una ruta local de prueba para validar lectura y resolucion.
# ---------------------------------------------------------------------------

BASE_DIR = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
LOG_PATH = os.path.join(BASE_DIR, "migrar_adjuntos_spring_prueba.log")


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


def obtener_adjuntos_pendientes(conn: pyodbc.Connection, tabla_adjuntos: str, batch: int = 3,
                                solo: dict | None = None):
    """Devuelve adjuntos sin traslado completado. Batch pequeno para pruebas.
    Con 'solo' se limita a los adjuntos relacionados a una OC/OS."""
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
        ORDER BY a.FechaCreacion, a.IdArchivo
    """
    return conn.cursor().execute(sql, params).fetchall()


def obtener_obligaciones_por_referencia(
    conn_spring: pyodbc.Connection,
    numero_referencia: str,
    tipo_referencia: str | None = None
) -> set:
    """Devuelve las obligaciones (proveedor, tipo, numero) relacionadas a una OC/OS."""
    sql = """
        SELECT DISTINCT RTRIM(Proveedor), RTRIM(ObligacionTipoDocumento),
               RTRIM(ObligacionNumeroDocumento)
        FROM AP_Documentos
        WHERE ReferenciaNumeroDocumento = ?
    """
    params = [numero_referencia]
    if tipo_referencia:
        sql += " AND ReferenciaTipoDocumento = ?"
        params.append(tipo_referencia)
    rows = conn_spring.cursor().execute(sql, params).fetchall()
    return {
        (str(r[0]).strip(), str(r[1]).strip(), str(r[2]).strip())
        for r in rows
        if all(x is not None for x in r)
    }


def obtener_ap_documento_por_obligacion(
    conn_spring: pyodbc.Connection,
    proveedor: str,
    tipo_obligacion: str,
    numero_obligacion: str
):
    sql = """
        SELECT TOP 1
            ReferenciaTipoDocumento,
            ReferenciaNumeroDocumento,
            RutaArchivo,
            Proveedor,
            CompaniaSocio,
            Fecha,
            DocumentoClasificacion,
            DocumentoReferencia
        FROM AP_Documentos
        WHERE Proveedor = ?
          AND ObligacionTipoDocumento = ?
          AND ObligacionNumeroDocumento = ?
    """
    return conn_spring.cursor().execute(sql, proveedor, tipo_obligacion, numero_obligacion).fetchone()


def obtener_ap_documento_por_referencia(
    conn_spring: pyodbc.Connection,
    tipo_doc: str,
    numero_doc: str
):
    sql = """
        SELECT TOP 1
            ReferenciaTipoDocumento,
            ReferenciaNumeroDocumento,
            RutaArchivo,
            Proveedor,
            CompaniaSocio,
            Fecha,
            DocumentoClasificacion,
            DocumentoReferencia
        FROM AP_Documentos
        WHERE ReferenciaTipoDocumento = ?
          AND ReferenciaNumeroDocumento = ?
    """
    return conn_spring.cursor().execute(sql, tipo_doc, numero_doc).fetchone()


def resolver_oc_os(conn_spring: pyodbc.Connection, tabla: str, id_registro: str):
    """Devuelve (tipo, numero, ruta_unc, proveedor, compania) o None."""

    if tabla == "Obligaciones":
        partes = id_registro.split("|")
        if len(partes) != 3:
            logging.warning(f"Id de Obligaciones no tiene formato esperado: {id_registro}")
            return None
        proveedor, tipo_obligacion, numero_obligacion = partes
        ap = obtener_ap_documento_por_obligacion(
            conn_spring, proveedor, tipo_obligacion, numero_obligacion
        )
        if not ap:
            return None
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

    if tabla == "WH_OrdenCompra":
        ap = obtener_ap_documento_por_referencia(conn_spring, "OC", id_registro)
        if ap:
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
        return {"tipo": "OC", "numero": id_registro, "ruta_unc": None, "proveedor": None, "compania": None}

    if tabla == "Compromiso":
        ap = obtener_ap_documento_por_referencia(conn_spring, "SO", id_registro)
        if ap:
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
        return {"tipo": "SO", "numero": id_registro, "ruta_unc": None, "proveedor": None, "compania": None}

    return None


def _a_int(valor) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def obtener_datos_orden(conn_spring: pyodbc.Connection, tipo: str | None,
                        numero: str | None, proveedor: int | None):
    """Devuelve (proveedor, fecha_orden) desde la tabla de la orden.

    OC -> WH_OrdenCompra (Proveedor, FechaPreparacion)
    SO -> Compromiso (Proveedor, FechaDocumento)

    La clave real de la orden es (numero, proveedor): el mismo NumeroOrden
    se reutiliza entre proveedores, por eso se filtra por proveedor cuando
    se conoce. Verificado contra GD_Grupo nivel 6 (ver docs/12)."""
    if not numero:
        return proveedor, None
    if tipo == "OC":
        sql = "SELECT TOP 1 Proveedor, FechaPreparacion FROM dbo.WH_OrdenCompra WHERE NumeroOrden = ?"
    elif tipo in ("SO", "OS"):
        sql = "SELECT TOP 1 Proveedor, FechaDocumento FROM dbo.Compromiso WHERE NumeroCompromiso = ?"
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
    """NombreCompleto de PersonaMast para GD_Grupo.DescripcionLarga del nivel 6."""
    if proveedor is None:
        return None
    row = conn_spring.cursor().execute(
        "SELECT TOP 1 NombreCompleto FROM dbo.PersonaMast WHERE Persona = ?", proveedor
    ).fetchone()
    return row[0].strip() if row and row[0] else None


def enriquecer_info_orden(conn_spring: pyodbc.Connection, info: dict) -> dict:
    """Completa proveedor_id, fecha_orden y razon_social del nivel 6.

    Prioriza la tabla de la orden (WH_OrdenCompra/Compromiso) sobre
    AP_Documentos: GD_Grupo.Persona/Fecha replican la orden, no el comprobante."""
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


def descomponer_ruta_spring(ruta_unc: str) -> list[str]:
    partes = [parte for parte in ruta_unc.replace("/", "\\").split("\\") if parte]
    try:
        indice = next(i for i, parte in enumerate(partes) if parte.upper() == "PROD")
    except StopIteration as ex:
        raise ValueError(f"La ruta de Spring no contiene el segmento PROD: {ruta_unc}") from ex
    jerarquia = partes[indice + 1:indice + 7]
    if len(jerarquia) != 6:
        raise ValueError(f"La ruta de Spring no tiene los 6 niveles esperados despues de PROD: {ruta_unc}")

    # Validaciones flexibles: nombres de carpetas pueden variar (Expediente Compras,
    # Expediente de Compras, Orden Compra, Orden Servicio, etc.).
    if not jerarquia[2].upper().startswith("ORDEN"):
        logging.warning(f"[PRUEBA][VALIDAR_RUTA] Nivel 3 no parece ser una orden: {jerarquia[2]}")
    if not any(p.isdigit() for p in jerarquia[4]) or not re.fullmatch(r"[0-9A-Za-z\-]+", jerarquia[5]):
        logging.warning(f"[PRUEBA][VALIDAR_RUTA] Niveles 5 (periodo) o 6 (numero de orden) no tienen formato esperado: {jerarquia}")

    return jerarquia


def buscar_grupo_ruta(conn_gestion: pyodbc.Connection, jerarquia: list[str],
                      persona: int | None = None):
    """Recorre GD_Grupo nivel a nivel por (IdGrupoPadre, NivelGrupo, Descripcion).
    El ultimo nivel (orden) se valida tambien por Persona: el mismo numero de
    orden puede existir para distintos proveedores (regla: orden + proveedor).
    Devuelve (id_grupo_hoja, recorrido[(nivel, descripcion, id, orden)])."""
    padre = None
    recorrido = []
    for nivel, descripcion in enumerate(jerarquia, start=1):
        es_ultimo = nivel == len(jerarquia)
        if padre is None:
            sql = """
                SELECT TOP 1 IdGrupo, Orden
                FROM dbo.GD_Grupo
                WHERE IdGrupoPadre IS NULL AND NivelGrupo = ? AND Descripcion = ? AND Estado = 'A'
            """
            row = conn_gestion.cursor().execute(sql, nivel, descripcion).fetchone()
        elif es_ultimo and persona is not None:
            sql = """
                SELECT TOP 1 IdGrupo, Orden
                FROM dbo.GD_Grupo
                WHERE IdGrupoPadre = ? AND NivelGrupo = ? AND Descripcion = ? AND Estado = 'A'
                  AND (Persona = ? OR Persona IS NULL OR Persona = 0)
                ORDER BY CASE WHEN Persona = ? THEN 0 ELSE 1 END
            """
            row = conn_gestion.cursor().execute(sql, padre, nivel, descripcion, persona, persona).fetchone()
        else:
            sql = """
                SELECT TOP 1 IdGrupo, Orden
                FROM dbo.GD_Grupo
                WHERE IdGrupoPadre = ? AND NivelGrupo = ? AND Descripcion = ? AND Estado = 'A'
            """
            row = conn_gestion.cursor().execute(sql, padre, nivel, descripcion).fetchone()
        recorrido.append((nivel, descripcion, row[0] if row else None, row[1] if row else None))
        if not row:
            return None, recorrido
        padre = row[0]
    return padre, recorrido


def construir_destino_prueba(ruta_prueba: str, jerarquia: list[str], nombre: str, tipo_copia: str) -> str:
    destino = os.path.normpath(os.path.join(ruta_prueba, *jerarquia, nombre))
    if tipo_copia == "COMPARTIDA":
        raiz = os.path.normpath(ruta_prueba)
        raiz_mayuscula = raiz.upper().rstrip("\\")
        destino_mayuscula = destino.upper()
        if not raiz_mayuscula.endswith("\\SPRINGGESTIONDOC\\PRUEBAS"):
            raise ValueError(f"RUTA_RAIZ_PRUEBA no es la raiz UNC autorizada: {ruta_prueba}")
        if not destino_mayuscula.startswith(raiz_mayuscula + "\\"):
            raise ValueError(f"El destino sale de la raiz autorizada de pruebas: {destino}")
        if "\\PROD\\" in destino_mayuscula or destino_mayuscula.endswith("\\PROD"):
            raise ValueError(f"Bloqueo de seguridad: el destino contiene PROD: {destino}")
    return destino


def _generar_nombre_unico(destino: str, contenido: bytes) -> str:
    """Genera un nombre alternativo cuando el archivo destino ya existe y tiene contenido distinto."""
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


def guardar_archivo_prueba(destino: str, contenido: bytes) -> tuple[str, int, bool]:
    """Crea la estructura de carpetas, guarda el archivo si no existe o es distinto,
    y verifica su tamano. Retorna (ruta_final, tamano, fue_escrito)."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if os.path.exists(destino):
        with open(destino, "rb") as f:
            existente = f.read()
        if existente == contenido:
            # Identico: no se toca el archivo existente.
            return destino, len(existente), False
        # Diferente: se genera un nombre alternativo.
        destino = _generar_nombre_unico(destino, contenido)
    with open(destino, "wb") as f:
        f.write(contenido)
    tamano_destino = os.path.getsize(destino)
    if tamano_destino != len(contenido):
        raise IOError(f"Tamano diferente despues de copiar: origen={len(contenido)}, destino={tamano_destino}")
    return destino, tamano_destino, True


def plantilla_ruta_por_compania(conn_spring: pyodbc.Connection, compania_socio: str, referencia_tipo: str = None) -> list[str] | None:
    """Busca una RutaArchivo existente para la misma compania y tipo de referencia.
    Devuelve la jerarquia (6 niveles) sin el segmento PROD, o None."""
    cache_key = (compania_socio, referencia_tipo)
    if cache_key in PLANTILLAS_CACHE:
        return PLANTILLAS_CACHE[cache_key]

    sql_tipo = """
        SELECT TOP 1 RutaArchivo
        FROM AP_Documentos
        WHERE CompaniaSocio = ? AND RutaArchivo IS NOT NULL AND ReferenciaTipoDocumento = ?
    """
    row = conn_spring.cursor().execute(sql_tipo, compania_socio, referencia_tipo).fetchone()
    if not row and referencia_tipo is not None:
        sql_any = """
            SELECT TOP 1 RutaArchivo
            FROM AP_Documentos
            WHERE CompaniaSocio = ? AND RutaArchivo IS NOT NULL
        """
        row = conn_spring.cursor().execute(sql_any, compania_socio).fetchone()
    if not row:
        PLANTILLAS_CACHE[cache_key] = None
        return None

    try:
        jerarquia = descomponer_ruta_spring(row[0])
        PLANTILLAS_CACHE[cache_key] = jerarquia
        return jerarquia
    except Exception:
        PLANTILLAS_CACHE[cache_key] = None
        return None


def construir_ruta_dinamica(
    conn_spring: pyodbc.Connection,
    compania_socio: str,
    referencia_tipo: str,
    numero_referencia: str,
    fecha: datetime
) -> list[str]:
    """Construye una jerarquia destino cuando AP_Documentos.RutaArchivo es nula."""
    if not compania_socio or not referencia_tipo or not numero_referencia or not fecha:
        raise ValueError("Faltan datos para construir la ruta: compania, tipo, numero o fecha")

    plantilla = plantilla_ruta_por_compania(conn_spring, compania_socio, referencia_tipo)
    if not plantilla:
        # Ultimo intento: buscar cualquier plantilla de la misma compania
        plantilla = plantilla_ruta_por_compania(conn_spring, compania_socio, None)
    if not plantilla:
        raise ValueError(f"No existe una RutaArchivo de referencia para la compania {compania_socio}")

    empresa_nombre = plantilla[0]
    expediente = plantilla[1]
    if referencia_tipo == "OC":
        orden_tipo = "Orden Compra"
    elif referencia_tipo == "SO":
        orden_tipo = "Orden Servicio"
    else:
        orden_tipo = plantilla[2]

    mes = MESES_ES.get(fecha.month, f"{fecha.month:02d}")
    return [
        empresa_nombre,
        expediente,
        orden_tipo,
        str(fecha.year),
        mes,
        numero_referencia
    ]


def _siguiente_orden(cursor: pyodbc.Cursor, id_padre: int | None, orden_padre: str | None) -> str:
    """Orden del nuevo nodo = Orden del padre + posicion (4 digitos) entre hermanos.
    Patron real: '0001.0001.0002.0008.0008.0410' (un segmento por nivel)."""
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


def buscar_o_crear_jerarquia_gd_grupo(
    conn_gestion: pyodbc.Connection,
    jerarquia: list[str],
    usuario: str = "MIGRACION",
    meta: dict | None = None,
    crear: bool = True
) -> int | None:
    """Busca la jerarquia en GD_Grupo. Si falta algun nivel, lo crea.
    Devuelve el IdGrupo del nivel mas profundo (hoja).

    meta: proveedor_id, razon_social y fecha_orden para el nivel 6
    (Persona, DescripcionLarga, Fecha segun el patron real de Spring).
    crear=False (simulacion): informa los niveles faltantes sin escribir
    y devuelve None."""
    meta = meta or {}
    persona = meta.get("proveedor_id")
    razon_social = meta.get("razon_social")
    fecha_orden = meta.get("fecha_orden")

    id_grupo, recorrido = buscar_grupo_ruta(conn_gestion, jerarquia, persona)
    if id_grupo:
        return id_grupo

    if not crear:
        faltantes = [d for _, d, encontrado, _ in recorrido if not encontrado]
        logging.info("[SIMULACION][GD_GRUPO] Niveles que se crearian: %s (Persona=%s, RazonSocial=%s, FechaOrden=%s)",
                     " > ".join(faltantes), persona, razon_social, fecha_orden)
        return None

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
        # Revisar raiz con IdGrupoPadre IS NULL
        cursor = conn_gestion.cursor()
        raiz = cursor.execute(
            "SELECT TOP 1 IdGrupo, Orden FROM dbo.GD_Grupo WHERE IdGrupoPadre IS NULL AND NivelGrupo = 1 AND Descripcion = ? AND Estado = 'A'",
            jerarquia[0]
        ).fetchone()
        if raiz:
            padre = raiz[0]
            orden_padre = raiz[1]
            nivel_inicial = 2

    cursor = conn_gestion.cursor()
    max_row = cursor.execute(
        "SELECT COALESCE(MAX(IdGrupo), 0) + 1 FROM dbo.GD_Grupo WITH (TABLOCKX, HOLDLOCK)"
    ).fetchone()
    next_id = max_row[0]

    for nivel in range(nivel_inicial, len(jerarquia) + 1):
        descripcion = jerarquia[nivel - 1]
        nuevo_id = next_id
        next_id += 1
        es_raiz = (padre is None and nivel == 1)
        es_hoja = (nivel == len(jerarquia))
        nuevo_orden = _siguiente_orden(cursor, padre, orden_padre)
        # Patron real Spring: niveles intermedios van con NULLs;
        # la hoja (nivel 6) lleva proveedor, razon social y fecha de la orden.
        descripcion_larga = razon_social if es_hoja else None
        persona_nivel = persona if es_hoja else None
        fecha_nivel = fecha_orden if es_hoja else None
        last_flag = 'S' if es_hoja else None
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
            usuario, descripcion_larga, last_flag, persona_nivel, fecha_nivel
        )
        conn_gestion.commit()
        padre = nuevo_id
        orden_padre = nuevo_orden

    return padre


def upsert_control_inicio(conn_ms: pyodbc.Connection, id_archivo: str, estado: str, etapa: str):
    sql = """
        MERGE dbo.MS_ArchivoTraslado AS t
        USING (VALUES (?)) AS s (IdArchivo)
        ON t.IdArchivo = s.IdArchivo
        WHEN MATCHED THEN UPDATE SET
            Estado = ?,
            Etapa = ?,
            MensajeError = NULL,
            FechaUltimoIntento = GETDATE(),
            Intentos = t.Intentos + 1
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
        SET Estado = ?,
            Etapa = ?,
            MensajeError = ?,
            RutaDestino = ?,
            IdGrupo = ?,
            ArchivoId = ?,
            FechaUltimoIntento = GETDATE(),
            FechaTraslado = CASE WHEN ? = 'COMPLETADO' THEN GETDATE() ELSE FechaTraslado END
        WHERE IdArchivo = ?
    """
    conn_ms.cursor().execute(sql, estado, etapa, mensaje, ruta, id_grupo, archivo_id, estado, id_archivo)
    conn_ms.commit()


def insertar_gd_archivo_prueba(conn_gestion: pyodbc.Connection, id_grupo: int, codigo: str,
                               ruta_archivo: str, nombre: str, usuario: str,
                               valor_texto1: str | None = None,
                               descripcion: str | None = None) -> int:
    cursor = conn_gestion.cursor()
    # ArchivoId es PK manual (no IDENTITY). Se bloquea toda la tabla para evitar
    # colisiones hasta completar el INSERT y liberar el ID en la misma transaccion.
    row = cursor.execute(
        "SELECT COALESCE(MAX(ArchivoId), 0) + 1 FROM dbo.GD_Archivo WITH (TABLOCKX, HOLDLOCK)"
    ).fetchone()
    archivo_id = row[0]
    sql = """
        INSERT INTO dbo.GD_Archivo
        (ArchivoId, Codigo, Nombre, RutaArchivo, IdGrupo, ValorTexto1, ValorTexto2, ValorTexto3,
         Estado, UltimoUsuario, UltimaFechaModif, Archivo, Descripcion)
        OUTPUT INSERTED.ArchivoId
        VALUES
        (?, ?, NULL, ?, ?, ?, NULL, NULL, 'A', ?, GETDATE(), NULL, ?)
    """
    cursor.execute(sql, (archivo_id, codigo, ruta_archivo, id_grupo, valor_texto1, usuario, descripcion))
    insertado = cursor.fetchone()[0]
    conn_gestion.commit()
    return insertado


def migrar_prueba(
    conn_ms: pyodbc.Connection,
    conn_spring: pyodbc.Connection,
    conn_gestion: pyodbc.Connection,
    tabla_adjuntos: str,
    empresa_nombre: str,
    usuario: str,
    ruta_prueba: str,
    tipo_copia: str,
    escritura: bool,
    batch: int = int(os.environ.get("BATCH_PRUEBA", "3")),
    solo: dict | None = None
):
    adjuntos = obtener_adjuntos_pendientes(conn_ms, tabla_adjuntos, batch, solo)
    logging.info(f"[PRUEBA] Se encontraron {len(adjuntos)} adjuntos pendientes o con error")

    if not adjuntos:
        logging.info("[PRUEBA] No hay adjuntos pendientes para probar.")
        return

    exitosos = 0
    omitidos = 0
    fallidos = 0
    for adjunto in adjuntos:
        id_archivo, id_registro, tabla, nombre, tipo, contenido, empresa, estado, intentos, etapa, mensaje_error = adjunto
        etapa_actual = "INICIO"
        try:
            logging.info("[PRUEBA][INICIO] IdArchivo=%s Empresa=%s Tabla=%s Id=%s Nombre=%s MIME=%s EstadoControl=%s Intentos=%s", id_archivo, empresa, tabla, id_registro, nombre, tipo, estado, intentos)
            if escritura:
                upsert_control_inicio(conn_ms, id_archivo, "PROCESANDO", etapa_actual)

            etapa_actual = "RESOLVER_AP_DOCUMENTOS"
            info = resolver_oc_os(conn_spring, tabla.strip() if tabla else tabla, id_registro.strip() if id_registro else id_registro)
            if not info or not info["numero"]:
                # Obligacion con formato valido pero sin comprobante en AP_Documentos:
                # queda SIN_AP y se revalida cada 24h por si la registran luego.
                sin_ap = (tabla == "Obligaciones"
                          and len(str(id_registro or "").split("|")) == 3)
                estado = "SIN_AP" if sin_ap else "ERROR"
                msg = ("Obligacion sin AP_Documentos en Spring (reintento en 24h)"
                       if sin_ap else "No se pudo resolver OC/OS")
                if escritura:
                    actualizar_control(conn_ms, id_archivo, estado, etapa_actual, msg, None, None, None)
                omitidos += 1
                logging.warning("[PRUEBA][%s][%s] %s IdArchivo=%s", etapa_actual, estado, msg, id_archivo)
                continue
            info = enriquecer_info_orden(conn_spring, info)
            logging.info("[PRUEBA][%s] Tipo=%s Numero=%s Proveedor=%s FechaOrden=%s RazonSocial=%s",
                         etapa_actual, info["tipo"], info["numero"], info.get("proveedor_id"),
                         info.get("fecha_orden"), info.get("razon_social"))
            if not info["ruta_unc"]:
                etapa_actual = "CONSTRUIR_RUTA_DINAMICA"
                fecha_jerarquia = info.get("fecha_orden") or info.get("fecha")
                if not info["compania"] or not info["tipo"] or not info["numero"] or not fecha_jerarquia:
                    msg = "AP_Documentos no tiene RutaArchivo y faltan datos para construir ruta dinamica"
                    if escritura:
                        actualizar_control(conn_ms, id_archivo, "ERROR", etapa_actual, msg, None, None, None)
                    omitidos += 1
                    logging.warning("[PRUEBA][%s][OMITIDO] %s para IdArchivo=%s", etapa_actual, msg, id_archivo)
                    continue
                jerarquia = construir_ruta_dinamica(conn_spring, info["compania"], info["tipo"], info["numero"], fecha_jerarquia)
                logging.info("[PRUEBA][%s] Jerarquia dinamica=%s", etapa_actual, " > ".join(jerarquia))
            else:
                etapa_actual = "VALIDAR_RUTA"
                jerarquia = descomponer_ruta_spring(info["ruta_unc"])
                logging.info("[PRUEBA][%s] Jerarquia=%s", etapa_actual, " > ".join(jerarquia))

            etapa_actual = "BUSCAR_GD_GRUPO"
            id_grupo = buscar_o_crear_jerarquia_gd_grupo(conn_gestion, jerarquia, usuario, meta=info, crear=escritura)
            if id_grupo is None:
                id_grupo = -1
            logging.info("[PRUEBA][%s] IdGrupo=%s", etapa_actual, id_grupo)

            etapa_actual = "CONSTRUIR_RUTA_PRUEBA"
            ruta_final = construir_destino_prueba(ruta_prueba, jerarquia, nombre, tipo_copia)
            logging.info("[PRUEBA][%s] TipoCopia=%s RutaDestino=%s", etapa_actual, tipo_copia, ruta_final)

            etapa_actual = "COPIAR_PRUEBA"
            ruta_destino, tamano_destino, fue_escrito = guardar_archivo_prueba(ruta_final, contenido)
            if fue_escrito:
                logging.info("[PRUEBA][%s] Archivo copiado y verificado Ruta=%s BytesOrigen=%s BytesDestino=%s", etapa_actual, ruta_destino, len(contenido), tamano_destino)
            else:
                logging.info("[PRUEBA][%s] Archivo existente identico omitido Ruta=%s BytesOrigen=%s BytesDestino=%s", etapa_actual, ruta_destino, len(contenido), tamano_destino)

            etapa_actual = "VALIDAR_DUPLICADO"
            duplicado = conn_gestion.cursor().execute(
                "SELECT TOP 1 ArchivoId FROM dbo.GD_Archivo WITH (UPDLOCK, HOLDLOCK) WHERE IdGrupo = ? AND RutaArchivo = ?",
                id_grupo, ruta_destino
            ).fetchone()
            if duplicado:
                archivo_id = duplicado[0]
                if escritura:
                    actualizar_control(conn_ms, id_archivo, "COMPLETADO", "COMPLETADO", None, ruta_destino, id_grupo, archivo_id)
                logging.info("[PRUEBA][%s] ArchivoId=%s ya existe en GD_Archivo para RutaArchivo=%s; no se duplica", etapa_actual, archivo_id, ruta_destino)
                logging.info("[PRUEBA][%s] Registro IdArchivo=%s finalizado", "ESCRITURA" if escritura else "SIMULACION", id_archivo)
                exitosos += 1
                continue

            etapa_actual = "INSERTAR_GD_ARCHIVO" if escritura else "SIMULAR_GD_ARCHIVO"
            codigo = "WH"
            valor_texto1 = TIPO_ORDEN_GD.get(info.get("tipo"), info.get("tipo"))
            archivo_id = None
            if escritura:
                archivo_id = insertar_gd_archivo_prueba(conn_gestion, id_grupo, codigo, ruta_destino, nombre, usuario, valor_texto1, None)
                conn_gestion.commit()
                logging.info("[PRUEBA][%s] ArchivoId=%s Codigo=%s ValorTexto1=%s RutaArchivo=%s IdGrupo=%s", etapa_actual, archivo_id, codigo, valor_texto1, ruta_destino, id_grupo)
            else:
                logging.info("[PRUEBA][%s] Codigo=%s Nombre=NULL RutaArchivo=%s IdGrupo=%s ValorTexto1=%s Descripcion=NULL", etapa_actual, codigo, ruta_destino, id_grupo, valor_texto1)

            if escritura:
                actualizar_control(conn_ms, id_archivo, "COMPLETADO", "COMPLETADO", None, ruta_destino, id_grupo, archivo_id)
            logging.info("[PRUEBA][%s] Registro IdArchivo=%s finalizado", "ESCRITURA" if escritura else "SIMULACION", id_archivo)
            exitosos += 1

        except Exception as ex:
            fallidos += 1
            msg = str(ex)
            logging.error("[PRUEBA][%s][FALLIDO] IdArchivo=%s Tabla=%s Id=%s Nombre=%s Error=%s", etapa_actual, id_archivo, tabla, id_registro, nombre, ex, exc_info=True)
            if escritura:
                try:
                    conn_ms.rollback()
                    conn_spring.rollback()
                except Exception as rollback_ex:
                    logging.error("[PRUEBA][ROLLBACK][FALLIDO] %s", rollback_ex)
                actualizar_control(conn_ms, id_archivo, "ERROR", etapa_actual, msg, None, None, None)

    logging.info("[PRUEBA][RESUMEN] total=%s exitosos=%s omitidos=%s fallidos=%s", len(adjuntos), exitosos, omitidos, fallidos)


def obtener_adjuntos_ap_pendientes(conn: pyodbc.Connection, batch: int = 3,
                                   obligaciones: set | None = None):
    """Devuelve archivos MS_AP_DocumentoArchivo sin traslado completado.
    Con 'obligaciones' se limita a las obligaciones relacionadas a una OC/OS."""
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
        ORDER BY a.IdApDocumentoArchivo
    """
    return conn.cursor().execute(sql, params).fetchall()


def upsert_control_inicio_ap(conn_ms: pyodbc.Connection, id_ap: int, gatipo: str, estado: str, etapa: str):
    sql = """
        MERGE dbo.MS_AP_DocumentoArchivoTraslado AS t
        USING (VALUES (?)) AS s (IdApDocumentoArchivo)
        ON t.IdApDocumentoArchivo = s.IdApDocumentoArchivo
        WHEN MATCHED THEN UPDATE SET
            Gatipo = ?,
            Estado = ?,
            Etapa = ?,
            MensajeError = NULL,
            FechaUltimoIntento = GETDATE(),
            Intentos = t.Intentos + 1
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
        SET Estado = ?,
            Etapa = ?,
            MensajeError = ?,
            RutaDestino = ?,
            IdGrupo = ?,
            ArchivoId = ?,
            FechaUltimoIntento = GETDATE(),
            FechaTraslado = CASE WHEN ? = 'COMPLETADO' THEN GETDATE() ELSE FechaTraslado END
        WHERE IdApDocumentoArchivo = ?
    """
    conn_ms.cursor().execute(sql, estado, etapa, mensaje, ruta, id_grupo, archivo_id, estado, id_ap)
    conn_ms.commit()


def migrar_ap_documento_archivo_prueba(
    conn_ms: pyodbc.Connection,
    conn_spring: pyodbc.Connection,
    conn_gestion: pyodbc.Connection,
    empresa_nombre: str,
    usuario: str,
    ruta_prueba: str,
    tipo_copia: str,
    escritura: bool,
    batch: int = int(os.environ.get("BATCH_AP_DOCUMENTO_PRUEBA", os.environ.get("BATCH_PRUEBA", "3"))),
    solo_obligaciones: set | None = None
):
    try:
        adjuntos = obtener_adjuntos_ap_pendientes(conn_ms, batch, solo_obligaciones)
    except pyodbc.ProgrammingError as ex:
        logging.error("[PRUEBA][AP_DOCUMENTO_ARCHIVO] No se encontro la tabla de control MS_AP_DocumentoArchivoTraslado: %s", ex)
        logging.info("[PRUEBA][AP_DOCUMENTO_ARCHIVO] Omitiendo migracion de MS_AP_DocumentoArchivo. Crear la tabla de control y volver a ejecutar.")
        return

    logging.info("[PRUEBA] Se encontraron %s archivos AP_DocumentoArchivo pendientes o con error", len(adjuntos))

    if not adjuntos:
        logging.info("[PRUEBA][AP_DOCUMENTO_ARCHIVO] No hay archivos pendientes.")
        return

    exitosos = 0
    omitidos = 0
    fallidos = 0
    for adjunto in adjuntos:
        id_ap, proveedor, tipo_obligacion, numero_obligacion, gatipo, ganombre, gadatos, estado, intentos, etapa, mensaje_error = adjunto
        etapa_actual = "INICIO"
        try:
            logging.info("[PRUEBA][AP][INICIO] IdAp=%s Proveedor=%s Obligacion=%s|%s Gatipo=%s Nombre=%s Estado=%s Intentos=%s",
                         id_ap, proveedor, tipo_obligacion, numero_obligacion, gatipo, ganombre, estado, intentos)
            if escritura:
                upsert_control_inicio_ap(conn_ms, id_ap, gatipo, "PROCESANDO", etapa_actual)

            etapa_actual = "RESOLVER_AP_DOCUMENTOS"
            ap = obtener_ap_documento_por_obligacion(conn_spring, proveedor, tipo_obligacion, numero_obligacion)
            if not ap:
                # La obligacion existe en el portal pero el comprobante aun no esta
                # en Spring AP (o esta con otro proveedor). Revalida en 24h.
                if escritura:
                    actualizar_control_ap(conn_ms, id_ap, gatipo, "SIN_AP", etapa_actual,
                                          "Obligacion sin AP_Documentos en Spring (reintento en 24h)", None, None, None)
                omitidos += 1
                logging.warning("[PRUEBA][AP][%s][SIN_AP] Sin AP_Documentos para IdAp=%s", etapa_actual, id_ap)
                continue
            info = {
                "tipo": ap.ReferenciaTipoDocumento.strip() if ap.ReferenciaTipoDocumento else None,
                "numero": ap.ReferenciaNumeroDocumento.strip() if ap.ReferenciaNumeroDocumento else None,
                "ruta_unc": ap.RutaArchivo.strip() if ap.RutaArchivo else None,
                "proveedor": ap.Proveedor,
                "compania": ap.CompaniaSocio.strip() if ap.CompaniaSocio else None,
                "fecha": ap.Fecha,
                "clasificacion": ap.DocumentoClasificacion.strip() if ap.DocumentoClasificacion else None,
                "referencia": ap.DocumentoReferencia.strip() if ap.DocumentoReferencia else None
            }
            info = enriquecer_info_orden(conn_spring, info)
            logging.info("[PRUEBA][AP][%s] Tipo=%s Numero=%s Proveedor=%s Compania=%s FechaOrden=%s RazonSocial=%s Ruta=%s",
                         etapa_actual, info["tipo"], info["numero"], info.get("proveedor_id"),
                         info["compania"], info.get("fecha_orden"), info.get("razon_social"), info["ruta_unc"])

            if info["ruta_unc"]:
                etapa_actual = "VALIDAR_RUTA"
                jerarquia = descomponer_ruta_spring(info["ruta_unc"])
                logging.info("[PRUEBA][AP][%s] Jerarquia=%s", etapa_actual, " > ".join(jerarquia))
            else:
                etapa_actual = "CONSTRUIR_RUTA_DINAMICA"
                fecha_jerarquia = info.get("fecha_orden") or info.get("fecha")
                if not info["compania"] or not info["tipo"] or not info["numero"] or not fecha_jerarquia:
                    msg = "AP_Documentos no tiene RutaArchivo y faltan datos para construir ruta dinamica"
                    if escritura:
                        actualizar_control_ap(conn_ms, id_ap, gatipo, "ERROR", etapa_actual, msg, None, None, None)
                    omitidos += 1
                    logging.warning("[PRUEBA][AP][%s][OMITIDO] %s para IdAp=%s", etapa_actual, msg, id_ap)
                    continue
                jerarquia = construir_ruta_dinamica(conn_spring, info["compania"], info["tipo"], info["numero"], fecha_jerarquia)
                logging.info("[PRUEBA][AP][%s] Jerarquia dinamica=%s", etapa_actual, " > ".join(jerarquia))

            etapa_actual = "BUSCAR_GD_GRUPO"
            id_grupo = buscar_o_crear_jerarquia_gd_grupo(conn_gestion, jerarquia, usuario, meta=info, crear=escritura)
            if id_grupo is None:
                id_grupo = -1
            logging.info("[PRUEBA][AP][%s] IdGrupo=%s", etapa_actual, id_grupo)

            etapa_actual = "CONSTRUIR_RUTA_PRUEBA"
            ruta_final = construir_destino_prueba(ruta_prueba, jerarquia, ganombre, tipo_copia)
            logging.info("[PRUEBA][AP][%s] TipoCopia=%s RutaDestino=%s", etapa_actual, tipo_copia, ruta_final)

            etapa_actual = "COPIAR_PRUEBA"
            ruta_destino, tamano_destino, fue_escrito = guardar_archivo_prueba(ruta_final, gadatos)
            if fue_escrito:
                logging.info("[PRUEBA][AP][%s] Archivo copiado y verificado Ruta=%s BytesOrigen=%s BytesDestino=%s", etapa_actual, ruta_destino, len(gadatos), tamano_destino)
            else:
                logging.info("[PRUEBA][AP][%s] Archivo existente identico omitido Ruta=%s BytesOrigen=%s BytesDestino=%s", etapa_actual, ruta_destino, len(gadatos), tamano_destino)

            etapa_actual = "VALIDAR_DUPLICADO"
            duplicado = conn_gestion.cursor().execute(
                "SELECT TOP 1 ArchivoId FROM dbo.GD_Archivo WITH (UPDLOCK, HOLDLOCK) WHERE IdGrupo = ? AND RutaArchivo = ?",
                id_grupo, ruta_destino
            ).fetchone()
            if duplicado:
                archivo_id = duplicado[0]
                if escritura:
                    actualizar_control_ap(conn_ms, id_ap, gatipo, "COMPLETADO", "COMPLETADO", None, ruta_destino, id_grupo, archivo_id)
                logging.info("[PRUEBA][AP][%s] ArchivoId=%s ya existe en GD_Archivo para RutaArchivo=%s; no se duplica", etapa_actual, archivo_id, ruta_destino)
                logging.info("[PRUEBA][AP][%s] Registro IdAp=%s finalizado", "ESCRITURA" if escritura else "SIMULACION", id_ap)
                exitosos += 1
                continue

            etapa_actual = "INSERTAR_GD_ARCHIVO" if escritura else "SIMULAR_GD_ARCHIVO"
            codigo = "WH"
            valor_texto1 = TIPO_ORDEN_GD.get(info.get("tipo"), info.get("tipo"))
            descripcion = CLASIFICACION_GATIPO.get((gatipo or "").strip().upper())
            archivo_id = None
            if escritura:
                archivo_id = insertar_gd_archivo_prueba(conn_gestion, id_grupo, codigo, ruta_destino, ganombre, usuario, valor_texto1, descripcion)
                conn_gestion.commit()
                logging.info("[PRUEBA][AP][%s] ArchivoId=%s Codigo=%s ValorTexto1=%s Descripcion=%s RutaArchivo=%s IdGrupo=%s", etapa_actual, archivo_id, codigo, valor_texto1, descripcion, ruta_destino, id_grupo)
            else:
                logging.info("[PRUEBA][AP][%s] Codigo=%s Nombre=NULL RutaArchivo=%s IdGrupo=%s ValorTexto1=%s Descripcion=%s", etapa_actual, codigo, ruta_destino, id_grupo, valor_texto1, descripcion)

            if escritura:
                actualizar_control_ap(conn_ms, id_ap, gatipo, "COMPLETADO", "COMPLETADO", None, ruta_destino, id_grupo, archivo_id)
            logging.info("[PRUEBA][AP][%s] Registro IdAp=%s finalizado", "ESCRITURA" if escritura else "SIMULACION", id_ap)
            exitosos += 1

        except Exception as ex:
            fallidos += 1
            msg = str(ex)
            logging.error("[PRUEBA][AP][%s][FALLIDO] IdAp=%s Gatipo=%s Nombre=%s Error=%s", etapa_actual, id_ap, gatipo, ganombre, ex, exc_info=True)
            if escritura:
                try:
                    conn_ms.rollback()
                    conn_spring.rollback()
                except Exception as rollback_ex:
                    logging.error("[PRUEBA][AP][ROLLBACK][FALLIDO] %s", rollback_ex)
                actualizar_control_ap(conn_ms, id_ap, gatipo, "ERROR", etapa_actual, msg, None, None, None)

    logging.info("[PRUEBA][AP][RESUMEN] total=%s exitosos=%s omitidos=%s fallidos=%s", len(adjuntos), exitosos, omitidos, fallidos)


if __name__ == "__main__":
    CONN_MS = os.environ.get("CONN_MS_HASS")
    CONN_SPRING = os.environ.get("CONN_SPRING_PRUEBA")
    if not CONN_MS or not CONN_SPRING:
        logging.error("[PRUEBA][CONFIGURACION][FALLIDO] Faltan CONN_MS_HASS o CONN_SPRING_PRUEBA")
        raise SystemExit(1)
    TABLA_ADJUNTOS = os.environ.get("TABLA_ADJUNTOS", "MS_Archivo")
    EMPRESA_NOMBRE = os.environ.get("EMPRESA_GD_GRUPO", "HASS PERU")
    USUARIO = os.environ.get("USUARIO_MIGRACION", "MIGRACION")
    TIPO_COPIA_PRUEBA = os.environ.get("TIPO_COPIA_PRUEBA", "LOCAL").strip().upper()
    MODO_PRUEBA = os.environ.get("MODO_PRUEBA", "SIMULACION").strip().upper()
    if TIPO_COPIA_PRUEBA not in {"LOCAL", "COMPARTIDA"}:
        raise SystemExit("TIPO_COPIA_PRUEBA debe ser LOCAL o COMPARTIDA")
    if MODO_PRUEBA not in {"SIMULACION", "ESCRITURA"}:
        raise SystemExit("MODO_PRUEBA debe ser SIMULACION o ESCRITURA")
    ESCRITURA = (MODO_PRUEBA == "ESCRITURA")
    ruta_local = r"C:\Users\jonathan.marquina\Documents\Jonathan Marquina\proyectos\servicio_documentos\pruebas_adjuntos"
    RUTA_PRUEBA = (
        os.environ.get("RUTA_RAIZ_PRUEBA", r"\\172.16.20.24\SpringGestionDoc\PRUEBAS")
        if TIPO_COPIA_PRUEBA == "COMPARTIDA"
        else os.environ.get("RUTA_PRUEBA_LOCAL", ruta_local)
    )

    logging.info("=" * 60)
    logging.info("INICIO DE PRUEBA DE MIGRACION DE ADJUNTOS")
    logging.info(f"Tipo de copia: {TIPO_COPIA_PRUEBA}")
    logging.info(f"Ruta de prueba: {RUTA_PRUEBA}")
    logging.info("Empresa GD_Grupo: obtenida dinamicamente desde AP_Documentos.RutaArchivo")
    if ESCRITURA:
        logging.info("MODO PRUEBA ESCRITURA: se registran MS_ArchivoTraslado y GD_Archivo (HASS_SPRING_PRUEBA)")
    else:
        logging.info("MODO PRUEBA SIMULACION: sin escrituras en MS_ArchivoTraslado, GD_Grupo ni GD_Archivo")
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
                logging.info("[PRUEBA][FILTRO] Procesando solo la orden %s %s: %s obligaciones relacionadas",
                             SOLO_TIPO or "OC/OS", SOLO_REFERENCIA, len(obligaciones))
            migrar_prueba(conn_ms, conn_spring, conn_spring, TABLA_ADJUNTOS, EMPRESA_NOMBRE, USUARIO, RUTA_PRUEBA, TIPO_COPIA_PRUEBA, ESCRITURA, solo=solo)
            migrar_ap_documento_archivo_prueba(conn_ms, conn_spring, conn_spring, EMPRESA_NOMBRE, USUARIO, RUTA_PRUEBA, TIPO_COPIA_PRUEBA, ESCRITURA,
                                               solo_obligaciones=solo["obligaciones"] if solo else None)
    except Exception as ex:
        logging.error("[PRUEBA][CONEXION][FALLIDO] No se pudo iniciar la prueba: %s", ex, exc_info=True)
        raise SystemExit(1)

    logging.info("=" * 60)
    logging.info("FIN DE PRUEBA")
    logging.info("=" * 60)
