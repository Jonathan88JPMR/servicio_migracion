# -*- coding: utf-8 -*-
"""Barrido unico previo al paso a produccion.

Marca OMITIDO en las tablas de control del portal (MS_HASS_PROVEEDOR) todos
los adjuntos pendientes cuya fecha sea anterior a FECHA_MINIMA (env,
default 2026-01-01), con la misma regla que usa el servicio en runtime:

    fecha_ref = fecha de la orden (WH_OrdenCompra.FechaPreparacion /
                Compromiso.FechaDocumento, filtrando por proveedor)
                o, en su defecto, AP_Documentos.Fecha

Fuentes cubiertas:
  - MS_AP_DocumentoArchivo : por obligacion (proveedor|tipo|numero)
  - MS_Archivo 'Obligaciones'   : mismo mapa de obligaciones (Id='p|t|n')
  - MS_Archivo 'WH_OrdenCompra' : FechaPreparacion por NumeroOrden
  - MS_Archivo 'Compromiso'     : FechaDocumento por NumeroCompromiso

Los pendientes sin fecha resoluble NO se tocan (el servicio los evalua en
runtime: SIN_AP reintenta en 24h, sin fecha -> ERROR visible).

Uso:
    set SQL_PASSWORD=***
    python marcar_omitidos_previos.py              # dry-run: solo conteos
    python marcar_omitidos_previos.py --ejecutar   # aplica los cambios
"""
import os
import sys
from datetime import datetime

import pyodbc

EJECUTAR = "--ejecutar" in sys.argv
_raw_fecha_min = os.environ.get("FECHA_MINIMA", "").strip()
FECHA_MINIMA = None if _raw_fecha_min.upper() in ("TODOS", "*") else datetime.strptime(
    _raw_fecha_min or "2026-01-01", "%Y-%m-%d"
).date()
_raw_fecha_max = os.environ.get("FECHA_MAXIMA", "").strip()
FECHA_MAXIMA = None if _raw_fecha_max.upper() in ("TODOS", "*", "") else datetime.strptime(
    _raw_fecha_max, "%Y-%m-%d"
).date()

CONN_MS = (
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER=172.16.20.25;"
    "DATABASE=MS_HASS_PROVEEDOR;UID=usr_migracion_adjuntos;PWD=" + os.environ["SQL_PASSWORD"] + ";"
)
CONN_PRD = (
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER=172.16.20.24;"
    "DATABASE=HP_SPRING_PRD;UID=usr_migracion_adjuntos;PWD=" + os.environ["SQL_PASSWORD"] + ";"
)

MSG_OMITIDO_MIN = f"Documento anterior al corte {FECHA_MINIMA}"
MSG_OMITIDO_MAX = f"Documento posterior al limite {FECHA_MAXIMA}"
CHUNK = 1000


def _fuera_rango(f):
    """'min' | 'max' | None segun el lado del rango en que cae f."""
    if f is None:
        return None
    if FECHA_MINIMA is not None and f < FECHA_MINIMA:
        return "min"
    if FECHA_MAXIMA is not None and f > FECHA_MAXIMA:
        return "max"
    return None


def _a_fecha(v):
    return v.date() if isinstance(v, datetime) else v


def cargar_temp(cur, tabla, columnas, filas):
    """Carga filas en una tabla temporal #tabla por lotes."""
    cur.execute(f"CREATE TABLE {tabla} ({columnas})")
    if not filas:
        return
    marks = "(" + ",".join(["?"] * len(filas[0])) + ")"
    for i in range(0, len(filas), CHUNK):
        cur.executemany(f"INSERT INTO {tabla} VALUES {marks}", filas[i:i + CHUNK])


def marcar_ap(cur_ms, ids, msg, dry):
    """UPDATE/INSERT OMITIDO en MS_AP_DocumentoArchivoTraslado por ids."""
    n = 0
    for i in range(0, len(ids), CHUNK):
        lote = ids[i:i + CHUNK]
        marks = ",".join("?" * len(lote))
        if not dry:
            cur_ms.execute(
                f"""UPDATE dbo.MS_AP_DocumentoArchivoTraslado
                    SET Estado='OMITIDO', Etapa='VALIDAR_RANGO', MensajeError=?,
                        FechaUltimoIntento=GETDATE()
                    WHERE IdApDocumentoArchivo IN ({marks})""",
                [msg] + lote)
            cur_ms.execute(
                f"""INSERT INTO dbo.MS_AP_DocumentoArchivoTraslado
                        (IdApDocumentoArchivo, Estado, Intentos, Etapa, MensajeError,
                         FechaPrimerIntento, FechaUltimoIntento)
                    SELECT a.IdApDocumentoArchivo, 'OMITIDO', 0, 'VALIDAR_RANGO', ?,
                           GETDATE(), GETDATE()
                    FROM dbo.MS_AP_DocumentoArchivo a
                    WHERE a.IdApDocumentoArchivo IN ({marks})
                      AND NOT EXISTS (SELECT 1 FROM dbo.MS_AP_DocumentoArchivoTraslado t
                                      WHERE t.IdApDocumentoArchivo = a.IdApDocumentoArchivo)""",
                [msg] + lote)
        n += len(lote)
    return n


def marcar_ms(cur_ms, ids, msg, dry):
    """UPDATE/INSERT OMITIDO en MS_ArchivoTraslado por IdArchivo (guid)."""
    n = 0
    for i in range(0, len(ids), CHUNK):
        lote = ids[i:i + CHUNK]
        marks = ",".join("?" * len(lote))
        if not dry:
            cur_ms.execute(
                f"""UPDATE dbo.MS_ArchivoTraslado
                    SET Estado='OMITIDO', Etapa='VALIDAR_RANGO', MensajeError=?,
                        FechaUltimoIntento=GETDATE()
                    WHERE IdArchivo IN ({marks})""",
                [msg] + lote)
            cur_ms.execute(
                f"""INSERT INTO dbo.MS_ArchivoTraslado
                        (IdArchivo, Estado, Intentos, Etapa, MensajeError,
                         FechaPrimerIntento, FechaUltimoIntento)
                    SELECT a.IdArchivo, 'OMITIDO', 0, 'VALIDAR_RANGO', ?,
                           GETDATE(), GETDATE()
                    FROM dbo.MS_Archivo a
                    WHERE a.IdArchivo IN ({marks})
                      AND NOT EXISTS (SELECT 1 FROM dbo.MS_ArchivoTraslado t
                                      WHERE t.IdArchivo = a.IdArchivo)""",
                [msg] + lote)
        n += len(lote)
    return n


def main():
    if FECHA_MINIMA is None and FECHA_MAXIMA is None:
        print("[INFO] Sin rango de fechas (TODOS): nada que omitir.")
        return
    print(f"[INFO] Rango: {FECHA_MINIMA or '-inf'} .. {FECHA_MAXIMA or '+inf'} "
          f"| modo: {'EJECUTAR' if EJECUTAR else 'DRY-RUN'}")
    with pyodbc.connect(CONN_MS, timeout=30) as ms, \
         pyodbc.connect(CONN_PRD, timeout=30) as sp:
        cur_ms, cur_sp = ms.cursor(), sp.cursor()

        # ---- 1) Obligaciones -> fecha_ref (orden o AP) -----------------------
        pend_ap = cur_ms.execute("""
            SELECT a.IdApDocumentoArchivo, a.Proveedor,
                   RTRIM(a.ObligacionTipoDocumento), RTRIM(a.ObligacionNumeroDocumento)
            FROM dbo.MS_AP_DocumentoArchivo a
            LEFT JOIN dbo.MS_AP_DocumentoArchivoTraslado t
              ON t.IdApDocumentoArchivo = a.IdApDocumentoArchivo
            WHERE a.Gadatos IS NOT NULL
              AND (t.IdApDocumentoArchivo IS NULL OR t.Estado IN ('PENDIENTE','ERROR'))
        """).fetchall()

        claves = {}
        for id_ap, prov, tipo, num in pend_ap:
            claves.setdefault((prov, tipo, num), []).append(id_ap)

        cargar_temp(cur_sp, "#obl", "p INT, t VARCHAR(5), n VARCHAR(30)", list(claves))
        # fecha del documento AP + referencia a la orden por clave
        ap_info = {}
        for r in cur_sp.execute("""
            SELECT o.p, o.t, o.n, MAX(d.Fecha),
                   MIN(d.ReferenciaTipoDocumento), MIN(d.ReferenciaNumeroDocumento)
            FROM #obl o
            JOIN dbo.AP_Documentos d
              ON d.Proveedor = o.p
             AND RTRIM(d.ObligacionTipoDocumento) = o.t
             AND RTRIM(d.ObligacionNumeroDocumento) = o.n
            GROUP BY o.p, o.t, o.n"""):
            ap_info[(r[0], r[1], r[2])] = {"fecha_ap": r[3], "tipo": r[4], "numero": r[5]}

        # fecha de la orden por (tipo, numero, proveedor) — igual que el servicio
        refs = {("SO" if v["tipo"] == "OS" else v["tipo"], v["numero"], k[0])
                for k, v in ap_info.items() if v["tipo"] and v["numero"]}
        cargar_temp(cur_sp, "#refs", "tipo VARCHAR(5), numero VARCHAR(30), prov INT", list(refs))
        orden_fecha = {}
        for r in cur_sp.execute("""
            SELECT r.numero, r.prov, MAX(oc.FechaPreparacion)
            FROM #refs r JOIN dbo.WH_OrdenCompra oc
              ON RTRIM(oc.NumeroOrden) = r.numero AND oc.Proveedor = r.prov
            WHERE r.tipo = 'OC'
            GROUP BY r.numero, r.prov"""):
            orden_fecha[("OC", r[0], r[1])] = r[2]
        for r in cur_sp.execute("""
            SELECT r.numero, r.prov, MAX(c.FechaDocumento)
            FROM #refs r JOIN dbo.Compromiso c
              ON RTRIM(c.NumeroCompromiso) = r.numero AND c.Proveedor = r.prov
            WHERE r.tipo IN ('SO','OS')
            GROUP BY r.numero, r.prov"""):
            orden_fecha[("SO", r[0], r[1])] = r[2]

        def fecha_ref(clave):
            info = ap_info.get(clave)
            if not info:
                return None  # sin AP_Documentos -> el servicio lo marca SIN_AP
            f_ord = orden_fecha.get((info["tipo"], info["numero"], clave[0]))
            return _a_fecha(f_ord) or _a_fecha(info["fecha_ap"])

        ids_ap_min, ids_ap_max = [], []
        for clave, ids in claves.items():
            lado = _fuera_rango(fecha_ref(clave))
            if lado == "min":
                ids_ap_min += ids
            elif lado == "max":
                ids_ap_max += ids
        print(f"[AP] pendientes={len(pend_ap)} claves={len(claves)} "
              f"sin_AP={len(claves) - len(ap_info)} "
              f"a_omitir={len(ids_ap_min) + len(ids_ap_max)} "
              f"(previos={len(ids_ap_min)} posteriores={len(ids_ap_max)})")
        print(f"[AP] marcados OMITIDO: "
              f"{marcar_ap(cur_ms, ids_ap_min, MSG_OMITIDO_MIN, not EJECUTAR) + marcar_ap(cur_ms, ids_ap_max, MSG_OMITIDO_MAX, not EJECUTAR)}")

        # ---- 2) MS_Archivo ---------------------------------------------------
        pend_ms = cur_ms.execute("""
            SELECT a.IdArchivo, a.Tabla, a.Id
            FROM dbo.MS_Archivo a
            LEFT JOIN dbo.MS_ArchivoTraslado t ON t.IdArchivo = a.IdArchivo
            WHERE a.Contenido IS NOT NULL
              AND (t.IdArchivo IS NULL OR t.Estado IN ('PENDIENTE','ERROR'))
        """).fetchall()

        obl_ids, oc_nums, so_nums = {}, set(), set()
        for id_arch, tabla, id_reg in pend_ms:
            t = (tabla or "").strip()
            if t == "Obligaciones" and len(str(id_reg).split("|")) == 3:
                p, ot, on = (x.strip() for x in str(id_reg).split("|"))
                try:
                    obl_ids[id_arch] = (int(p), ot, on)
                except ValueError:
                    pass
            elif t == "WH_OrdenCompra":
                oc_nums.add(str(id_reg).strip())
            elif t == "Compromiso":
                so_nums.add(str(id_reg).strip())

        # fechas de orden sin filtrar proveedor (MAX = criterio conservador)
        cargar_temp(cur_sp, "#oc", "numero VARCHAR(30)", [(n,) for n in oc_nums] or [("",)])
        oc_fecha = {r[0]: r[1] for r in cur_sp.execute("""
            SELECT o.numero, MAX(oc.FechaPreparacion)
            FROM #oc o JOIN dbo.WH_OrdenCompra oc ON RTRIM(oc.NumeroOrden) = o.numero
            GROUP BY o.numero""")}
        cargar_temp(cur_sp, "#so", "numero VARCHAR(30)", [(n,) for n in so_nums] or [("",)])
        so_fecha = {r[0]: r[1] for r in cur_sp.execute("""
            SELECT o.numero, MAX(c.FechaDocumento)
            FROM #so o JOIN dbo.Compromiso c ON RTRIM(c.NumeroCompromiso) = o.numero
            GROUP BY o.numero""")}

        ids_ms_min, ids_ms_max = [], []
        for id_arch, tabla, id_reg in pend_ms:
            t = (tabla or "").strip()
            if t == "Obligaciones":
                clave = obl_ids.get(id_arch)
                f = fecha_ref(clave) if clave else None
            elif t == "WH_OrdenCompra":
                f = _a_fecha(oc_fecha.get(str(id_reg).strip()))
            elif t == "Compromiso":
                f = _a_fecha(so_fecha.get(str(id_reg).strip()))
            else:
                f = None
            lado = _fuera_rango(f)
            if lado == "min":
                ids_ms_min.append(id_arch)
            elif lado == "max":
                ids_ms_max.append(id_arch)

        print(f"[MS] pendientes={len(pend_ms)} "
              f"a_omitir={len(ids_ms_min) + len(ids_ms_max)} "
              f"(previos={len(ids_ms_min)} posteriores={len(ids_ms_max)})")
        print(f"[MS] marcados OMITIDO: "
              f"{marcar_ms(cur_ms, ids_ms_min, MSG_OMITIDO_MIN, not EJECUTAR) + marcar_ms(cur_ms, ids_ms_max, MSG_OMITIDO_MAX, not EJECUTAR)}")

        if EJECUTAR:
            ms.commit()
            print("[OK] Cambios aplicados.")
        else:
            print("[DRY-RUN] Sin cambios. Ejecutar con --ejecutar para aplicar.")


if __name__ == "__main__":
    main()
