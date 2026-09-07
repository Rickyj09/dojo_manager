from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.exceptions import HTTPException

from app.models.alumno import Alumno
from app.extensions import db
from app.services.finanzas import (
    MEDIOS_PAGO_FINANCIERO,
    anular_pago,
    aplicar_pago_a_obligaciones,
    eliminar_archivo_comprobante,
    guardar_dia_vencimiento_pension,
    guardar_comprobante_pago,
    obtener_detalle_pago,
    listar_comprobantes_pago,
    obtener_cartera_alumnos,
    obtener_comprobante,
    obtener_configuracion_financiera,
    obtener_estado_cuenta_alumno,
    obtener_obligaciones_aplicables_pago,
    obtener_resumen_cartera_academia,
    registrar_pago,
    resolver_ruta_comprobante,
)
from app.services.finanzas.familias import FinanzasError


finanzas_bp = Blueprint("finanzas", __name__, url_prefix="/finanzas")

ROLES_LECTURA_FINANZAS = ("SUPERADMIN", "ADMIN", "PROFESOR")
ROLES_ADMINISTRACION_FINANZAS = ("SUPERADMIN", "ADMIN")


def _academia_id_or_403():
    academia_id = getattr(current_user, "academia_id", None)
    if not academia_id:
        abort(403)
    return academia_id


def _puede_ver_finanzas():
    return current_user.is_authenticated and any(
        current_user.has_role(rol) for rol in ROLES_LECTURA_FINANZAS
    )


def _puede_configurar_finanzas():
    return current_user.is_authenticated and any(
        current_user.has_role(rol) for rol in ROLES_ADMINISTRACION_FINANZAS
    )


def _puede_escribir_finanzas():
    return _puede_configurar_finanzas()


def _validar_alumno_visible(academia_id: int, alumno_id: int):
    alumno = Alumno.query.filter_by(id=alumno_id, academia_id=academia_id).first()
    if alumno is None:
        abort(404)
    if current_user.has_role("PROFESOR") and alumno.sucursal_id != current_user.sucursal_id:
        abort(403)
    return alumno


def _parse_fecha_pago(value: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise FinanzasError("La fecha de pago no es valida")


def _aplicaciones_desde_formulario():
    aplicaciones = []
    for key, value in request.form.items():
        if not key.startswith("aplicar_"):
            continue
        value = (value or "").strip()
        if not value:
            continue
        try:
            obligacion_id = int(key.removeprefix("aplicar_"))
        except ValueError:
            raise FinanzasError("Obligacion invalida")
        aplicaciones.append(
            {
                "obligacion_financiera_id": obligacion_id,
                "valor_aplicado": value,
            }
        )
    return aplicaciones


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
        puede_escribir=_puede_escribir_finanzas(),
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

    return render_template(
        "finanzas/estado_cuenta_alumno.html",
        estado_cuenta=estado_cuenta,
        puede_escribir=_puede_escribir_finanzas(),
    )


@finanzas_bp.route("/alumnos/<int:alumno_id>/pagos/nuevo", methods=["GET", "POST"])
@login_required
def nuevo_pago_alumno(alumno_id):
    if not _puede_escribir_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    alumno = _validar_alumno_visible(academia_id, alumno_id)
    form = {
        "fecha_pago": request.form.get("fecha_pago") or date.today().isoformat(),
        "valor": request.form.get("valor") or "",
        "moneda": request.form.get("moneda") or "USD",
        "medio_pago": request.form.get("medio_pago") or "EFECTIVO",
        "referencia": request.form.get("referencia") or "",
        "observacion": request.form.get("observacion") or "",
    }

    if request.method == "POST":
        try:
            pago = registrar_pago(
                academia_id=academia_id,
                alumno_id=alumno.id,
                fecha_pago=_parse_fecha_pago(form["fecha_pago"]),
                valor=form["valor"],
                moneda=form["moneda"],
                medio_pago=form["medio_pago"],
                referencia=form["referencia"].strip() or None,
                observacion=form["observacion"].strip() or None,
            )
            db.session.commit()
        except FinanzasError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        else:
            flash("Pago registrado correctamente.", "success")
            return redirect(url_for("finanzas.detalle_pago", pago_id=pago.id))

    return render_template(
        "finanzas/pago_form.html",
        alumno=alumno,
        medios_pago=MEDIOS_PAGO_FINANCIERO,
        form=form,
    )


@finanzas_bp.route("/pagos/<int:pago_id>")
@login_required
def detalle_pago(pago_id):
    if not _puede_ver_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    try:
        detalle = obtener_detalle_pago(academia_id=academia_id, pago_id=pago_id)
    except FinanzasError:
        abort(404)
    _validar_alumno_visible(academia_id, detalle.pago.alumno_id)
    obligaciones_aplicables = obtener_obligaciones_aplicables_pago(academia_id=academia_id, pago_id=pago_id)
    comprobantes = listar_comprobantes_pago(academia_id=academia_id, pago_id=pago_id)

    return render_template(
        "finanzas/pago_detalle.html",
        detalle=detalle,
        obligaciones_aplicables=obligaciones_aplicables,
        comprobantes=comprobantes,
        puede_escribir=_puede_escribir_finanzas(),
    )


@finanzas_bp.route("/pagos/<int:pago_id>/aplicar", methods=["POST"])
@login_required
def aplicar_pago_financiero(pago_id):
    if not _puede_escribir_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    try:
        detalle = obtener_detalle_pago(academia_id=academia_id, pago_id=pago_id)
        _validar_alumno_visible(academia_id, detalle.pago.alumno_id)
        aplicaciones = _aplicaciones_desde_formulario()
        creadas = aplicar_pago_a_obligaciones(
            academia_id=academia_id,
            pago_id=pago_id,
            aplicaciones=aplicaciones,
        )
        db.session.commit()
    except FinanzasError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    else:
        flash(f"Se aplicaron {len(creadas)} valores del pago.", "success")
    return redirect(url_for("finanzas.detalle_pago", pago_id=pago_id))


@finanzas_bp.route("/pagos/<int:pago_id>/comprobantes", methods=["POST"])
@login_required
def cargar_comprobante_pago(pago_id):
    if not _puede_escribir_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    comprobante = None
    try:
        detalle = obtener_detalle_pago(academia_id=academia_id, pago_id=pago_id)
        _validar_alumno_visible(academia_id, detalle.pago.alumno_id)
        comprobante = guardar_comprobante_pago(
            academia_id=academia_id,
            pago_id=pago_id,
            archivo=request.files.get("comprobante"),
            uploaded_by_id=current_user.id,
            observacion=request.form.get("observacion_comprobante"),
        )
        db.session.commit()
    except FinanzasError as exc:
        db.session.rollback()
        if comprobante is not None:
            eliminar_archivo_comprobante(comprobante)
        flash(str(exc), "danger")
    except HTTPException:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        if comprobante is not None:
            eliminar_archivo_comprobante(comprobante)
        flash("No se pudo guardar el comprobante.", "danger")
    else:
        flash("Comprobante cargado correctamente.", "success")
    return redirect(url_for("finanzas.detalle_pago", pago_id=pago_id))


@finanzas_bp.route("/comprobantes/<int:comprobante_id>")
@login_required
def ver_comprobante(comprobante_id):
    if not _puede_ver_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    try:
        comprobante = obtener_comprobante(academia_id=academia_id, comprobante_id=comprobante_id)
        detalle = obtener_detalle_pago(academia_id=academia_id, pago_id=comprobante.pago_financiero_id)
        _validar_alumno_visible(academia_id, detalle.pago.alumno_id)
        ruta = resolver_ruta_comprobante(comprobante)
    except FinanzasError:
        abort(404)
    if not ruta.exists():
        abort(404)
    return send_file(
        ruta,
        mimetype=comprobante.mime_type,
        as_attachment=False,
        download_name=comprobante.nombre_original,
    )


@finanzas_bp.route("/pagos/<int:pago_id>/anular", methods=["POST"])
@login_required
def anular_pago_financiero(pago_id):
    if not _puede_escribir_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    try:
        detalle = obtener_detalle_pago(academia_id=academia_id, pago_id=pago_id)
        _validar_alumno_visible(academia_id, detalle.pago.alumno_id)
        anular_pago(academia_id=academia_id, pago_id=pago_id)
        db.session.commit()
    except FinanzasError as exc:
        db.session.rollback()
        if "pago con aplicaciones" in str(exc):
            flash("No se puede anular este pago porque tiene valores aplicados. Primero debe existir un procedimiento de reverso.", "danger")
        else:
            flash(str(exc), "danger")
    else:
        flash("Pago anulado correctamente.", "success")
    return redirect(url_for("finanzas.detalle_pago", pago_id=pago_id))


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
