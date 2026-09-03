from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models.alumno import Alumno
from app.extensions import db
from app.services.finanzas import (
    guardar_dia_vencimiento_pension,
    obtener_cartera_alumnos,
    obtener_configuracion_financiera,
    obtener_estado_cuenta_alumno,
    obtener_resumen_cartera_academia,
)
from app.services.finanzas.familias import FinanzasError


finanzas_bp = Blueprint("finanzas", __name__, url_prefix="/finanzas")


def _academia_id_or_403():
    academia_id = getattr(current_user, "academia_id", None)
    if not academia_id:
        abort(403)
    return academia_id


def _puede_ver_finanzas():
    return (
        current_user.is_authenticated
        and (
            current_user.has_role("SUPERADMIN")
            or current_user.has_role("ADMIN")
            or current_user.has_role("PROFESOR")
        )
    )


def _puede_configurar_finanzas():
    return current_user.is_authenticated and (
        current_user.has_role("SUPERADMIN") or current_user.has_role("ADMIN")
    )


def _validar_alumno_visible(academia_id: int, alumno_id: int):
    alumno = Alumno.query.filter_by(id=alumno_id, academia_id=academia_id).first()
    if alumno is None:
        abort(404)
    if current_user.has_role("PROFESOR") and alumno.sucursal_id != current_user.sucursal_id:
        abort(403)
    return alumno


@finanzas_bp.route("/cartera")
@login_required
def cartera():
    if not _puede_ver_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    q = (request.args.get("q") or "").strip()
    filtro = (request.args.get("saldo") or "todos").strip()
    periodo = (request.args.get("periodo") or "").strip() or None
    con_saldo = filtro == "con_saldo"
    vencidos = filtro == "vencidos"
    alumno_ids = None

    if current_user.has_role("PROFESOR"):
        alumnos_visibles = Alumno.query.filter_by(
            academia_id=academia_id,
            sucursal_id=current_user.sucursal_id,
        ).with_entities(Alumno.id).all()
        alumno_ids = {row[0] for row in alumnos_visibles}

    resumen = obtener_resumen_cartera_academia(
        academia_id=academia_id,
        periodo=periodo,
        alumno_ids=alumno_ids,
    )
    alumnos = obtener_cartera_alumnos(
        academia_id=academia_id,
        q=q,
        con_saldo=con_saldo,
        vencidos=vencidos,
        periodo=periodo,
        alumno_ids=alumno_ids,
    )

    return render_template(
        "finanzas/cartera.html",
        resumen=resumen,
        alumnos=alumnos,
        q=q,
        filtro=filtro,
        periodo=periodo or "",
    )


@finanzas_bp.route("/alumnos/<int:alumno_id>/estado-cuenta")
@login_required
def estado_cuenta_alumno(alumno_id):
    if not _puede_ver_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    _validar_alumno_visible(academia_id, alumno_id)

    try:
        estado_cuenta = obtener_estado_cuenta_alumno(academia_id=academia_id, alumno_id=alumno_id)
    except FinanzasError:
        abort(404)

    return render_template("finanzas/estado_cuenta_alumno.html", estado_cuenta=estado_cuenta)


@finanzas_bp.route("/configuracion", methods=["GET", "POST"])
@login_required
def configuracion():
    if not _puede_configurar_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    configuracion_actual = obtener_configuracion_financiera(academia_id=academia_id)

    if request.method == "POST":
        valor = (request.form.get("dia_vencimiento_pension") or "").strip()
        dia = None
        if valor:
            try:
                dia = int(valor)
            except ValueError:
                flash("El dia de vencimiento debe ser un numero entre 1 y 31.", "danger")
                return render_template("finanzas/configuracion.html", configuracion=configuracion_actual)

        try:
            configuracion_actual = guardar_dia_vencimiento_pension(
                academia_id=academia_id,
                dia_vencimiento_pension=dia,
            )
            db.session.commit()
        except FinanzasError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        else:
            flash("Configuracion financiera actualizada.", "success")
            return redirect(url_for("finanzas.configuracion"))

    return render_template("finanzas/configuracion.html", configuracion=configuracion_actual)
