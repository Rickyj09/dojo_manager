from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import date

from app.extensions import db
from app.tenancy import tenant_query

from app.models.pago import Pago
from app.models.alumno import Alumno

from app.utils.pagos import calcular_deuda

pagos_bp = Blueprint("pagos", __name__, url_prefix="/pagos")


def _alumno_seguro(alumno_id: int):
    """Alumno dentro del tenant y, si es PROFESOR, dentro de su sucursal."""
    alumno = tenant_query(Alumno).filter_by(id=alumno_id).first_or_404()

    if current_user.has_role("PROFESOR") and alumno.sucursal_id != current_user.sucursal_id:
        flash("No tiene acceso a este alumno", "danger")
        return None

    return alumno


# =========================
# LISTADO GENERAL DE PAGOS
# =========================
@pagos_bp.route("/")
@login_required
def index():
    query = tenant_query(Pago).join(Alumno, Alumno.id == Pago.alumno_id)

    # PROFESOR: solo su sucursal (además del tenant)
    if current_user.has_role("PROFESOR"):
        query = query.filter(Pago.sucursal_id == current_user.sucursal_id)

    pagos = query.order_by(Pago.fecha_pago.desc()).all()

    return render_template("pagos/index.html", pagos=pagos)


# =========================
# REGISTRAR NUEVO PAGO
# =========================
@pagos_bp.route("/nuevo/<int:alumno_id>", methods=["GET", "POST"])
@login_required
def nuevo(alumno_id):
    alumno = _alumno_seguro(alumno_id)
    if alumno is None:
        return redirect(url_for("alumnos.index"))

    hoy = date.today()

    if request.method == "POST":
        try:
            mes = int(request.form["mes"])
            anio = int(request.form["anio"])
            monto = float(request.form["monto"])
        except (ValueError, TypeError):
            flash("Datos inválidos", "danger")
            return redirect(request.url)

        metodo = request.form.get("metodo")
        observacion = request.form.get("observacion")

        if monto <= 0:
            flash("El monto debe ser mayor a cero", "danger")
            return redirect(request.url)

        if mes < 1 or mes > 12:
            flash("Mes inválido", "danger")
            return redirect(request.url)

        if anio < 2020 or anio > 2100:
            flash("Año inválido", "danger")
            return redirect(request.url)

        # ✅ EVITAR DUPLICADOS POR TENANT
        existe = tenant_query(Pago).filter_by(
            alumno_id=alumno.id,
            mes=mes,
            anio=anio
        ).first()

        if existe:
            flash("Este mes ya está pagado", "warning")
            return redirect(request.url)

        pago = Pago(
            alumno_id=alumno.id,
            sucursal_id=alumno.sucursal_id,
            mes=mes,
            anio=anio,
            monto=monto,
            metodo=metodo,
            observacion=observacion,
            academia_id=current_user.academia_id  # ✅ explícito
        )

        db.session.add(pago)
        db.session.commit()

        flash("Pago registrado correctamente", "success")
        return redirect(url_for("pagos.historial_alumno", alumno_id=alumno.id))

    return render_template("pagos/nuevo.html", alumno=alumno, hoy=hoy)


# =========================
# HISTORIAL DE PAGOS POR ALUMNO
# =========================
@pagos_bp.route("/alumno/<int:alumno_id>")
@login_required
def historial_alumno(alumno_id):
    alumno = _alumno_seguro(alumno_id)
    if alumno is None:
        return redirect(url_for("alumnos.index"))

    pagos = (
        tenant_query(Pago)
        .filter_by(alumno_id=alumno.id)
        .order_by(Pago.anio.desc(), Pago.mes.desc())
        .all()
    )

    total_pagado = sum(float(p.monto) for p in pagos)

    # ✅ deuda calculada multi-tenant (arreglamos abajo)
    estado = calcular_deuda(alumno, academia_id=current_user.academia_id)

    return render_template(
        "pagos/historial.html",
        alumno=alumno,
        pagos=pagos,
        total_pagado=total_pagado,
        estado=estado
    )