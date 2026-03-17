from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models.alumno import Alumno
from app.models.sucursal import Sucursal
from app.models.grado import Grado
from datetime import datetime
import io
import pandas as pd
from datetime import date, timedelta
from app.models.pago import Pago
from sqlalchemy import func
from app.models.torneo import Torneo
from app.models.participacion import Participacion
from app.models.categoriascompetencia import CategoriaCompetencia
from app.utils.categorias import (
    calcular_edad,
    obtener_categoria_competencia,
    sugerir_categoria_combate,
    sugerir_categoria_poomsae,
)


def _get_fecha_base() -> date:
    """
    Devuelve la fecha base para calcular edad:
    - Si viene ?fecha_base=YYYY-MM-DD en querystring, la usa.
    - Si no viene, usa hoy.
    """
    fecha_base_str = request.args.get("fecha_base")
    if fecha_base_str:
        try:
            return datetime.strptime(fecha_base_str, "%Y-%m-%d").date()
        except ValueError:
            # Si viene mal, caemos a hoy (y opcionalmente podrías hacer flash)
            return date.today()
    return date.today()

def _rango_fechas_por_edad(edad_min, edad_max, fecha_base: date):
    """
    Filtra por edad al día 'fecha_base' transformando edad -> rango de fecha_nacimiento.
    Devuelve (fnac_desde, fnac_hasta) para:
      Alumno.fecha_nacimiento BETWEEN fnac_desde AND fnac_hasta
    """
    if not fecha_base:
        fecha_base = date.today()

    fnac_hasta = None  # más viejo (edad_min)
    fnac_desde = None  # más joven (edad_max)

    # Para tener al menos edad_min: nacido <= fecha_base - edad_min años
    if edad_min is not None:
        fnac_hasta = date(fecha_base.year - edad_min, fecha_base.month, fecha_base.day)

    # Para tener como máximo edad_max: nacido >= fecha_base - edad_max años
    if edad_max is not None:
        fnac_desde = date(fecha_base.year - edad_max, fecha_base.month, fecha_base.day)

    return fnac_desde, fnac_hasta


reportes_bp = Blueprint("reportes", __name__, url_prefix="/reportes")

def _parse_date(s: str, default: date):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return default

def _periodo_yyyymm(fecha: date) -> int:
    return fecha.year * 100 + fecha.month

def _months_between(periodo_pagado: int, periodo_corte: int) -> int:
    # periodo_pagado y periodo_corte: YYYYMM
    y1, m1 = divmod(periodo_pagado, 100)
    y2, m2 = divmod(periodo_corte, 100)
    return (y2 - y1) * 12 + (m2 - m1)

def _get_identidad_col():
    # usa el primer atributo que exista en Alumno
    for attr in ("identidad", "cedula", "numero_identidad", "dni"):
        if hasattr(Alumno, attr):
            return getattr(Alumno, attr)
    return Alumno.id  # fallback

def _aplicar_seguridad_por_rol(query):
    """PROFESOR ve solo su sucursal; ADMIN ve todo."""
    if current_user.has_role("PROFESOR"):
        query = query.filter(Alumno.sucursal_id == current_user.sucursal_id)
    return query

def get_reporte_morosidad(fecha_corte: date, sucursal_id=None, activo=True, solo_morosos=True):
    periodo_corte = _periodo_yyyymm(fecha_corte)

    # Subquery: último período pagado por alumno (MAX(YYYYMM))
    sub_ult = (
        db.session.query(
            Pago.alumno_id.label("alumno_id"),
            func.max((Pago.anio * 100) + Pago.mes).label("ult_periodo"),
            func.max(Pago.fecha_pago).label("ult_fecha_pago")
        )
        .group_by(Pago.alumno_id)
        .subquery()
    )

    identidad_col = _get_identidad_col()

    q = (
        db.session.query(
            Alumno.id.label("alumno_id"),
            identidad_col.label("identidad"),
            Alumno.nombres,
            Alumno.apellidos,
            Sucursal.nombre.label("sucursal"),
            sub_ult.c.ult_periodo,
            sub_ult.c.ult_fecha_pago
        )
        .join(Sucursal, Alumno.sucursal_id == Sucursal.id)
        .outerjoin(sub_ult, sub_ult.c.alumno_id == Alumno.id)
    )

    if hasattr(Alumno, "activo") and activo is not None:
        q = q.filter(Alumno.activo == bool(activo))

    if sucursal_id:
        q = q.filter(Alumno.sucursal_id == int(sucursal_id))

    rows = q.order_by(Sucursal.nombre, Alumno.apellidos, Alumno.nombres).all()

    data = []
    for r in rows:
        ult_periodo = r.ult_periodo  # puede ser None si nunca pagó
        ult_fecha = r.ult_fecha_pago

        if ult_periodo is None:
            meses_vencidos = ""   # sin historial (lo marcamos moroso)
            estado = "MOROSO"
        else:
            md = _months_between(int(ult_periodo), int(periodo_corte))
            meses_vencidos = max(0, md)
            estado = "MOROSO" if meses_vencidos >= 1 else "AL DÍA"

        if solo_morosos and estado != "MOROSO":
            continue

        data.append({
            "identidad": r.identidad,
            "nombres": r.nombres,
            "apellidos": r.apellidos,
            "sucursal": r.sucursal,
            "ultimo_pago": ult_fecha.isoformat() if ult_fecha else "",
            "ultimo_periodo": str(ult_periodo) if ult_periodo else "",
            "meses_vencidos": meses_vencidos,
            "estado": estado
        })

    return data


@reportes_bp.route("/", methods=["GET"])
@login_required
def index():
    # filtros
    sucursal_id = request.args.get("sucursal_id", type=int)
    genero = request.args.get("genero")  # 'M'/'F' o como manejes
    grado_id = request.args.get("grado_id", type=int)
    peso_min = request.args.get("peso_min", type=float)
    peso_max = request.args.get("peso_max", type=float)

    q = (
        db.session.query(Alumno, Sucursal, Grado)
        .join(Sucursal, Sucursal.id == Alumno.sucursal_id)
        .outerjoin(Grado, Grado.id == Alumno.grado_id)
    )
    q = _aplicar_seguridad_por_rol(q)

    if sucursal_id:
        q = q.filter(Alumno.sucursal_id == sucursal_id)
    if genero:
        q = q.filter(Alumno.genero == genero)
    if grado_id:
        q = q.filter(Alumno.grado_id == grado_id)
    if peso_min is not None:
        q = q.filter(Alumno.peso >= peso_min)
    if peso_max is not None:
        q = q.filter(Alumno.peso <= peso_max)

    q = q.order_by(Sucursal.nombre.asc(), Alumno.apellidos.asc(), Alumno.nombres.asc())

    # IMPORTANTE: usamos .all() para que en Jinja sea fácil (no Row suelto)
    filas = q.all()

    # combos
    if current_user.has_role("PROFESOR"):
        sucursales = Sucursal.query.filter_by(id=current_user.sucursal_id).all()
    else:
        sucursales = Sucursal.query.filter_by(activo=True).order_by(Sucursal.nombre).all()

    grados = Grado.query.filter_by(activo=True).order_by(Grado.orden).all()

    # Para pintar la tabla: convertimos a dicts
    resultados = []
    for alumno, sucursal, grado in filas:
        resultados.append({
            "id": alumno.numero_identidad,
            "nombres": alumno.nombres,
            "apellidos": alumno.apellidos,
            "genero": alumno.genero,
            "peso": alumno.peso,
            "sucursal": sucursal.nombre if sucursal else "",
            "grado": grado.nombre if grado else "",
        })

    return render_template(
        "reportes/index.html",
        resultados=resultados,
        total=len(resultados),
        sucursales=sucursales,
        grados=grados,
        filtros={
            "sucursal_id": sucursal_id,
            "genero": genero,
            "grado_id": grado_id,
            "peso_min": peso_min,
            "peso_max": peso_max,
        },
    )


@reportes_bp.route("/export/excel", methods=["GET"])
@login_required
def export_excel():
    # reutilizamos EXACTAMENTE los mismos filtros del preview
    sucursal_id = request.args.get("sucursal_id", type=int)
    genero = request.args.get("genero")
    grado_id = request.args.get("grado_id", type=int)
    peso_min = request.args.get("peso_min", type=float)
    peso_max = request.args.get("peso_max", type=float)

    q = (
        db.session.query(Alumno, Sucursal, Grado)
        .join(Sucursal, Sucursal.id == Alumno.sucursal_id)
        .outerjoin(Grado, Grado.id == Alumno.grado_id)
    )
    q = _aplicar_seguridad_por_rol(q)

    if sucursal_id:
        q = q.filter(Alumno.sucursal_id == sucursal_id)
    if genero:
        q = q.filter(Alumno.genero == genero)
    if grado_id:
        q = q.filter(Alumno.grado_id == grado_id)
    if peso_min is not None:
        q = q.filter(Alumno.peso >= peso_min)
    if peso_max is not None:
        q = q.filter(Alumno.peso <= peso_max)

    q = q.order_by(Sucursal.nombre.asc(), Alumno.apellidos.asc(), Alumno.nombres.asc())

    filas = q.all()

    data = []
    for alumno, sucursal, grado in filas:
        data.append({
            "ID": alumno.id,
            "Apellidos": alumno.apellidos,
            "Nombres": alumno.nombres,
            "Género": alumno.genero,
            "Peso": alumno.peso,
            "Sucursal": sucursal.nombre if sucursal else "",
            "Grado": grado.nombre if grado else "",
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Alumnos")
    output.seek(0)

    nombre = f"reporte_alumnos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=nombre,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@reportes_bp.route("/combate", methods=["GET"])
@login_required
def combate():
    sucursal_id = request.args.get("sucursal_id", type=int)
    genero = request.args.get("genero")
    edad_min = request.args.get("edad_min", type=int)
    edad_max = request.args.get("edad_max", type=int)
    peso_min = request.args.get("peso_min", type=float)
    peso_max = request.args.get("peso_max", type=float)

    # 1) definir fecha_base ANTES de usarla
    fecha_base = _get_fecha_base()

    q = (
        db.session.query(Alumno, Sucursal, Grado)
        .join(Sucursal, Sucursal.id == Alumno.sucursal_id)
        .outerjoin(Grado, Grado.id == Alumno.grado_id)
    )
    q = _aplicar_seguridad_por_rol(q)

    if sucursal_id:
        q = q.filter(Alumno.sucursal_id == sucursal_id)
    if genero:
        q = q.filter(Alumno.genero == genero)
    if peso_min is not None:
        q = q.filter(Alumno.peso >= peso_min)
    if peso_max is not None:
        q = q.filter(Alumno.peso <= peso_max)

    # 2) edad (fecha_nacimiento) usando fecha_base ya definida
    fnac_desde, fnac_hasta = _rango_fechas_por_edad(edad_min, edad_max, fecha_base)
    if fnac_desde and fnac_hasta:
        q = q.filter(Alumno.fecha_nacimiento.between(fnac_desde, fnac_hasta))
    elif fnac_desde:
        q = q.filter(Alumno.fecha_nacimiento >= fnac_desde)
    elif fnac_hasta:
        q = q.filter(Alumno.fecha_nacimiento <= fnac_hasta)

    q = q.order_by(Sucursal.nombre.asc(), Alumno.apellidos.asc(), Alumno.nombres.asc())
    filas = q.all()

    if current_user.has_role("PROFESOR"):
        sucursales = Sucursal.query.filter_by(id=current_user.sucursal_id).all()
    else:
        sucursales = Sucursal.query.filter_by(activo=True).order_by(Sucursal.nombre).all()

    resultados = []
    for alumno, sucursal, grado in filas:
        resultados.append({
            "id": alumno.numero_identidad,
            "apellidos": alumno.apellidos,
            "nombres": alumno.nombres,
            "genero": alumno.genero,
            "fecha_nacimiento": alumno.fecha_nacimiento,
            "peso": alumno.peso,
            "sucursal": sucursal.nombre if sucursal else "",
            "grado": grado.nombre if grado else "",
        })

    return render_template(
        "reportes/combate.html",
        resultados=resultados,
        total=len(resultados),
        sucursales=sucursales,
        filtros={
            "fecha_base": fecha_base.isoformat(),
            "sucursal_id": sucursal_id,
            "genero": genero,
            "edad_min": edad_min,
            "edad_max": edad_max,
            "peso_min": peso_min,
            "peso_max": peso_max,
        },
    )

@reportes_bp.route("/poomsae", methods=["GET"])
@login_required
def poomsae():
    sucursal_id = request.args.get("sucursal_id", type=int)
    genero = request.args.get("genero")
    edad_min = request.args.get("edad_min", type=int)
    edad_max = request.args.get("edad_max", type=int)
    grado_id = request.args.get("grado_id", type=int)
    tipo_grado = request.args.get("tipo_grado")  # 'KUP' o 'DAN'

    fecha_base = _get_fecha_base()

    q = (
        db.session.query(Alumno, Sucursal, Grado)
        .join(Sucursal, Sucursal.id == Alumno.sucursal_id)
        .outerjoin(Grado, Grado.id == Alumno.grado_id)
    )
    q = _aplicar_seguridad_por_rol(q)

    if sucursal_id:
        q = q.filter(Alumno.sucursal_id == sucursal_id)
    if genero:
        q = q.filter(Alumno.genero == genero)
    if grado_id:
        q = q.filter(Alumno.grado_id == grado_id)
    if tipo_grado:
        q = q.filter(Grado.tipo == tipo_grado)

    fnac_desde, fnac_hasta = _rango_fechas_por_edad(edad_min, edad_max, fecha_base)
    if fnac_desde and fnac_hasta:
        q = q.filter(Alumno.fecha_nacimiento.between(fnac_desde, fnac_hasta))
    elif fnac_desde:
        q = q.filter(Alumno.fecha_nacimiento >= fnac_desde)
    elif fnac_hasta:
        q = q.filter(Alumno.fecha_nacimiento <= fnac_hasta)

    q = q.order_by(Sucursal.nombre.asc(), Alumno.apellidos.asc(), Alumno.nombres.asc())
    filas = q.all()

    if current_user.has_role("PROFESOR"):
        sucursales = Sucursal.query.filter_by(id=current_user.sucursal_id).all()
    else:
        sucursales = Sucursal.query.filter_by(activo=True).order_by(Sucursal.nombre).all()

    grados = Grado.query.filter_by(activo=True).order_by(Grado.orden).all()

    resultados = []
    for alumno, sucursal, grado in filas:
        resultados.append({
            "id": alumno.numero_identidad,
            "apellidos": alumno.apellidos,
            "nombres": alumno.nombres,
            "genero": alumno.genero,
            "fecha_nacimiento": alumno.fecha_nacimiento,
            "sucursal": sucursal.nombre if sucursal else "",
            "grado": grado.nombre if grado else "",
            "grado_tipo": grado.tipo if grado else "",
        })

    return render_template(
        "reportes/poomsae.html",
        resultados=resultados,
        total=len(resultados),
        sucursales=sucursales,
        grados=grados,
        filtros={
            "fecha_base": fecha_base.isoformat(),
            "sucursal_id": sucursal_id,
            "genero": genero,
            "edad_min": edad_min,
            "edad_max": edad_max,
            "grado_id": grado_id,
            "tipo_grado": tipo_grado,
        },
    )


@reportes_bp.route("/combate/export/excel", methods=["GET"])
@login_required
def combate_export_excel():
    # mismos args que combate()
    sucursal_id = request.args.get("sucursal_id", type=int)
    genero = request.args.get("genero")
    edad_min = request.args.get("edad_min", type=int)
    edad_max = request.args.get("edad_max", type=int)
    peso_min = request.args.get("peso_min", type=float)
    peso_max = request.args.get("peso_max", type=float)

    q = (
        db.session.query(Alumno, Sucursal, Grado)
        .join(Sucursal, Sucursal.id == Alumno.sucursal_id)
        .outerjoin(Grado, Grado.id == Alumno.grado_id)
    )
    q = _aplicar_seguridad_por_rol(q)

    if sucursal_id:
        q = q.filter(Alumno.sucursal_id == sucursal_id)
    if genero:
        q = q.filter(Alumno.genero == genero)
    if peso_min is not None:
        q = q.filter(Alumno.peso >= peso_min)
    if peso_max is not None:
        q = q.filter(Alumno.peso <= peso_max)

    fnac_desde, fnac_hasta = _rango_fechas_por_edad(edad_min, edad_max)
    if fnac_desde and fnac_hasta:
        q = q.filter(Alumno.fecha_nacimiento.between(fnac_desde, fnac_hasta))
    elif fnac_desde:
        q = q.filter(Alumno.fecha_nacimiento >= fnac_desde)
    elif fnac_hasta:
        q = q.filter(Alumno.fecha_nacimiento <= fnac_hasta)

    q = q.order_by(Sucursal.nombre.asc(), Alumno.apellidos.asc(), Alumno.nombres.asc())
    filas = q.all()

    data = []
    for alumno, sucursal, grado in filas:
        data.append({
            "ID": alumno.numero_identidad,
            "Apellidos": alumno.apellidos,
            "Nombres": alumno.nombres,
            "Género": alumno.genero,
            "Fecha nacimiento": alumno.fecha_nacimiento,
            "Peso": alumno.peso,
            "Sucursal": sucursal.nombre if sucursal else "",
            "Grado": grado.nombre if grado else "",
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Combate")
    output.seek(0)

    nombre = f"reporte_combate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(output, as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@reportes_bp.route("/poomsae/export/excel", methods=["GET"])
@login_required
def poomsae_export_excel():
    sucursal_id = request.args.get("sucursal_id", type=int)
    genero = request.args.get("genero")
    edad_min = request.args.get("edad_min", type=int)
    edad_max = request.args.get("edad_max", type=int)
    grado_id = request.args.get("grado_id", type=int)
    tipo_grado = request.args.get("tipo_grado")

    q = (
        db.session.query(Alumno, Sucursal, Grado)
        .join(Sucursal, Sucursal.id == Alumno.sucursal_id)
        .outerjoin(Grado, Grado.id == Alumno.grado_id)
    )
    q = _aplicar_seguridad_por_rol(q)

    if sucursal_id:
        q = q.filter(Alumno.sucursal_id == sucursal_id)
    if genero:
        q = q.filter(Alumno.genero == genero)
    if grado_id:
        q = q.filter(Alumno.grado_id == grado_id)
    if tipo_grado:
        q = q.filter(Grado.tipo == tipo_grado)

    fecha_base = _get_fecha_base()
    fnac_desde, fnac_hasta = _rango_fechas_por_edad(edad_min, edad_max, fecha_base)
    if fnac_desde and fnac_hasta:
        q = q.filter(Alumno.fecha_nacimiento.between(fnac_desde, fnac_hasta))
    elif fnac_desde:
        q = q.filter(Alumno.fecha_nacimiento >= fnac_desde)
    elif fnac_hasta:
        q = q.filter(Alumno.fecha_nacimiento <= fnac_hasta)

    q = q.order_by(Sucursal.nombre.asc(), Alumno.apellidos.asc(), Alumno.nombres.asc())
    filas = q.all()

    data = []
    for alumno, sucursal, grado in filas:
        data.append({
            "ID": alumno.numero_identidad,
            "Apellidos": alumno.apellidos,
            "Nombres": alumno.nombres,
            "Género": alumno.genero,
            "Fecha nacimiento": alumno.fecha_nacimiento,
            "Sucursal": sucursal.nombre if sucursal else "",
            "Grado": grado.nombre if grado else "",
            "Tipo grado": grado.tipo if grado else "",
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Poomsae")
    output.seek(0)

    nombre = f"reporte_poomsae_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(output, as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def _edad_en_fecha(fnac: date, fecha_base: date) -> int | None:
        if not fnac:
            return None
        years = fecha_base.year - fnac.year
        if (fecha_base.month, fecha_base.day) < (fnac.month, fnac.day):
            years -= 1
        return years
    
@reportes_bp.route("/morosidad", methods=["GET"])
@login_required
def morosidad():
    fecha_corte = _parse_date(request.args.get("fecha_corte", ""), date.today())
    sucursal_id = request.args.get("sucursal_id")
    activo = True if request.args.get("activo", "1") == "1" else False
    solo_morosos = True if request.args.get("solo_morosos", "1") == "1" else False

    data = get_reporte_morosidad(
        fecha_corte=fecha_corte,
        sucursal_id=sucursal_id,
        activo=activo,
        solo_morosos=solo_morosos
    )

    return render_template(
        "reportes/morosidad.html",
        data=data,
        fecha_corte=fecha_corte,
        total=len(data),
        solo_morosos=solo_morosos
    )

@reportes_bp.route("/morosidad.xlsx", methods=["GET"])
@login_required
def morosidad_xlsx():
    fecha_corte = _parse_date(request.args.get("fecha_corte", ""), date.today())
    sucursal_id = request.args.get("sucursal_id")
    activo = True if request.args.get("activo", "1") == "1" else False
    solo_morosos = True if request.args.get("solo_morosos", "1") == "1" else False

    data = get_reporte_morosidad(
        fecha_corte=fecha_corte,
        sucursal_id=sucursal_id,
        activo=activo,
        solo_morosos=solo_morosos
    )

    df = pd.DataFrame(data, columns=[
        "identidad", "nombres", "apellidos", "sucursal",
        "ultimo_pago", "ultimo_periodo", "meses_vencidos", "estado"
    ])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Morosidad")

    output.seek(0)
    filename = f"morosidad_{fecha_corte.isoformat()}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def _calc_valores_evento(torneo: Torneo, modalidad_raw: str):
    """Retorna dict con valor por modalidad. Si AMBAS, aplica descuento en COMBATE."""
    poom = float(torneo.precio_poomsae or 0)
    comb = float(torneo.precio_combate or 0)
    desc = float(torneo.descuento_ambas or 0)

    modalidad_raw = (modalidad_raw or "POOMSAE").upper().strip()

    if modalidad_raw == "POOMSAE":
        return {"POOMSAE": poom}
    if modalidad_raw == "COMBATE":
        return {"COMBATE": comb}
    # AMBAS => 2 filas; descuento lo aplicamos en COMBATE
    return {"POOMSAE": poom, "COMBATE": max(0.0, comb - desc)}


@reportes_bp.route("/torneo/<int:torneo_id>/seleccionar", methods=["GET", "POST"])
@login_required
def seleccionar_competidores(torneo_id):
    torneo = Torneo.query.get_or_404(torneo_id)

    # alumnos activos (seguridad por rol)
    q = Alumno.query.filter_by(activo=True)
    if current_user.has_role("PROFESOR"):
        q = q.filter(Alumno.sucursal_id == current_user.sucursal_id)

    alumnos = q.order_by(Alumno.apellidos, Alumno.nombres).all()

    # mapa de categorías sugeridas para UI
    categorias_map = {}
    for a in alumnos:
        categorias_map[a.id] = {
            "combate": sugerir_categoria_combate(a, torneo),
            "poomsae": sugerir_categoria_poomsae(a, torneo),
            "edad": calcular_edad(a.fecha_nacimiento, torneo.fecha),
            "peso": float(a.peso) if a.peso is not None else None,
            "grado": a.grado.nombre if a.grado else None,
        }

    # precargar selecciones existentes: (alumno_id -> set(modalidades))
    existentes = Participacion.query.filter_by(torneo_id=torneo.id).all()
    mapa = {}
    for p in existentes:
        mapa.setdefault(p.alumno_id, set()).add(p.modalidad)

    if request.method == "POST":
        seleccionados = set(map(int, request.form.getlist("alumno_ids[]")))

        # borrar participaciones de alumnos desmarcados
        if seleccionados:
            (
                Participacion.query
                .filter(Participacion.torneo_id == torneo.id)
                .filter(~Participacion.alumno_id.in_(seleccionados))
                .delete(synchronize_session=False)
            )
        else:
            (
                Participacion.query
                .filter(Participacion.torneo_id == torneo.id)
                .delete(synchronize_session=False)
            )

        # upsert de seleccionados
        for a in alumnos:
            if a.id not in seleccionados:
                continue

            modalidad_raw = (request.form.get(f"modalidad_{a.id}") or "POOMSAE").upper().strip()
            if modalidad_raw not in ("POOMSAE", "COMBATE", "AMBAS"):
                modalidad_raw = "POOMSAE"

            valores = _calc_valores_evento(torneo, modalidad_raw)
            modalidades = list(valores.keys())

            for mod in modalidades:
                categoria = obtener_categoria_competencia(alumno=a, torneo=torneo, modalidad=mod)
                if not categoria:
                    flash(f"No se encontró categoría válida para {a.apellidos} {a.nombres} ({mod}).", "danger")
                    db.session.rollback()
                    return redirect(request.url)

                p = (
                    Participacion.query
                    .filter_by(torneo_id=torneo.id, alumno_id=a.id, modalidad=mod)
                    .first()
                )

                if not p:
                    p = Participacion(torneo_id=torneo.id, alumno_id=a.id, modalidad=mod)
                    db.session.add(p)

                p.categoria_id = categoria.id
                p.valor_evento = valores[mod]

        db.session.commit()
        flash("Selección guardada correctamente.", "success")
        return redirect(url_for("reportes.seleccionar_competidores", torneo_id=torneo.id))

    return render_template(
        "reportes/seleccionar_competidores.html",
        torneo=torneo,
        alumnos=alumnos,
        mapa=mapa,
        categorias_map=categorias_map
    )


@reportes_bp.route("/torneo/<int:torneo_id>/seleccion.xlsx", methods=["GET"])
@login_required
def torneo_seleccion_xlsx(torneo_id):
    torneo = Torneo.query.get_or_404(torneo_id)

    q = (
        db.session.query(Participacion, Alumno, Sucursal, CategoriaCompetencia)
        .join(Alumno, Alumno.id == Participacion.alumno_id)
        .join(Sucursal, Sucursal.id == Alumno.sucursal_id)
        .join(CategoriaCompetencia, CategoriaCompetencia.id == Participacion.categoria_id)
        .filter(Participacion.torneo_id == torneo.id)
        .order_by(Sucursal.nombre, Alumno.apellidos, Alumno.nombres, Participacion.modalidad)
    )

    if current_user.has_role("PROFESOR"):
        q = q.filter(Alumno.sucursal_id == current_user.sucursal_id)

    rows = q.all()

    data = []
    for p, a, s, cat in rows:
        data.append({
            "Identificación": a.numero_identidad or a.id,
            "Alumno": f"{a.apellidos} {a.nombres}",
            "Género": a.genero,
            "Sucursal": s.nombre,
            "Modalidad": p.modalidad,
            "Categoría": cat.nombre,
            "Valor evento": float(p.valor_evento or 0),
            "Pagado": "SI" if p.pagado_evento else "NO",
            "Fecha pago": str(p.fecha_pago_evento or ""),
            "Método pago": p.metodo_pago_evento or ""
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Seleccion")

    output.seek(0)
    filename = f"seleccion_{torneo.nombre}_{torneo.fecha}.xlsx".replace(" ", "_")
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@reportes_bp.route("/seleccion", methods=["GET", "POST"])
@login_required
def seleccion_torneo():
    torneos = Torneo.query.order_by(Torneo.fecha.desc()).all()

    if request.method == "POST":
        torneo_id = request.form.get("torneo_id")
        return redirect(url_for("reportes.seleccionar_competidores", torneo_id=int(torneo_id)))

    return render_template("reportes/seleccion_torneo.html", torneos=torneos)