from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.tenancy import tenant_query
from app.models.asistencia import Asistencia
from app.models.sucursal import Sucursal
from app.models.alumno import Alumno

asistencias_bp = Blueprint("asistencias", __name__, url_prefix="/asistencias")


@asistencias_bp.route("/", methods=["GET"])
@login_required
def index():
    # filtros
    fecha_str = request.args.get("fecha") or date.today().isoformat()
    sucursal_id = request.args.get("sucursal_id")

    try:
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except ValueError:
        fecha = date.today()

    # sucursal según rol
    if current_user.has_role("PROFESOR"):
        sucursal_id = current_user.sucursal_id

    sucursales = tenant_query(Sucursal).filter_by(activo=True).order_by(Sucursal.nombre).all()

    alumnos_q = tenant_query(Alumno).filter_by(activo=True)
    if sucursal_id:
        alumnos_q = alumnos_q.filter(Alumno.sucursal_id == int(sucursal_id))
    alumnos = alumnos_q.order_by(Alumno.apellidos.asc(), Alumno.nombres.asc()).all()

    # asistencias del día (tenant)
    asistencias = tenant_query(Asistencia).filter_by(fecha=fecha)
    if sucursal_id:
        asistencias = asistencias.filter(Asistencia.sucursal_id == int(sucursal_id))
    asistencias = asistencias.all()

    asist_map = {(a.alumno_id, a.sucursal_id): a for a in asistencias}

    return render_template(
        "asistencias/index.html",
        fecha=fecha.isoformat(),
        sucursal_id=int(sucursal_id) if sucursal_id else None,
        sucursales=sucursales,
        alumnos=alumnos,
        asist_map=asist_map
    )


@asistencias_bp.route("/registrar", methods=["POST"])
@login_required
def registrar():
    fecha_str = request.form.get("fecha") or date.today().isoformat()
    sucursal_id = request.form.get("sucursal_id")

    try:
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except ValueError:
        fecha = date.today()

    # rol: profesor fuerza su sucursal
    if current_user.has_role("PROFESOR"):
        sucursal_id = current_user.sucursal_id

    if not sucursal_id:
        flash("Debe seleccionar sucursal.", "danger")
        return redirect(url_for("asistencias.index", fecha=fecha.isoformat()))

    sucursal_id = int(sucursal_id)

    # Validar sucursal del tenant
    suc = tenant_query(Sucursal).filter_by(id=sucursal_id, activo=True).first()
    if not suc:
        flash("Sucursal inválida para esta academia.", "danger")
        return redirect(url_for("asistencias.index", fecha=fecha.isoformat()))

    # estados recibidos: estado_<alumno_id> = P/A/T/J
    # solo alumnos del tenant y de esa sucursal
    alumnos = tenant_query(Alumno).filter_by(activo=True, sucursal_id=sucursal_id).all()

    for al in alumnos:
        estado = request.form.get(f"estado_{al.id}", "P").strip().upper()
        if estado not in ("P", "A", "T", "J"):
            estado = "P"

        observacion = (request.form.get(f"obs_{al.id}") or "").strip() or None

        # upsert por unique (academia_id, fecha, alumno_id, sucursal_id)
        reg = tenant_query(Asistencia).filter_by(
            fecha=fecha,
            alumno_id=al.id,
            sucursal_id=sucursal_id
        ).first()

        if not reg:
            reg = Asistencia(
                fecha=fecha,
                alumno_id=al.id,
                sucursal_id=sucursal_id,
                registrado_por_id=current_user.id,
                estado=estado,
                observacion=observacion,
                academia_id=current_user.academia_id,  # explícito
            )
            db.session.add(reg)
        else:
            reg.estado = estado
            reg.observacion = observacion
            reg.registrado_por_id = current_user.id

    db.session.commit()
    flash("Asistencias guardadas.", "success")
    return redirect(url_for("asistencias.index", fecha=fecha.isoformat(), sucursal_id=sucursal_id))