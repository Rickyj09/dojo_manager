# app/routes/academias.py
from flask import Blueprint, abort, current_app, render_template, request, redirect, url_for, flash
from flask_login import current_user, login_required
from werkzeug.exceptions import RequestEntityTooLarge
from sqlalchemy import func

from app.extensions import db
from app.models.academia import Academia
from app.services.branding import BrandingError, actualizar_logo_academia

academias_bp = Blueprint("academias", __name__, url_prefix="/academias")


@academias_bp.errorhandler(RequestEntityTooLarge)
def archivo_demasiado_grande(error):
    if request.endpoint != "academias.identidad_visual":
        return error
    flash("El logo no puede superar los 2 MB.", "danger")
    return redirect(url_for("academias.identidad_visual"))


@academias_bp.route("/identidad-visual", methods=["GET", "POST"])
@login_required
def identidad_visual():
    if not (current_user.has_role("ADMIN") or current_user.has_role("SUPERADMIN")):
        abort(403)
    academia_id = current_user.academia_id
    if not academia_id:
        abort(403)
    # La academia nunca se elige con un parámetro de la petición.
    if "academia_id" in request.args or "academia_id" in request.form:
        abort(403)
    academia = Academia.query.filter_by(id=academia_id).first_or_404()
    if request.method == "POST":
        try:
            accion = request.form.get("accion", "guardar")
            if accion not in ("guardar", "restaurar"):
                raise BrandingError("Seleccione una acción válida.")
            actualizar_logo_academia(academia_id=academia_id,
                archivo=request.files.get("logo"), restaurar=accion == "restaurar")
            flash("Logo predeterminado restaurado." if accion == "restaurar" else "Identidad visual actualizada.", "success")
            return redirect(url_for("academias.identidad_visual"))
        except BrandingError as exc:
            flash(str(exc), "danger")
            return render_template("academias/identidad_visual.html", academia=academia), 400
        except Exception:
            db.session.rollback()
            current_app.logger.exception("No se pudo actualizar el logo de la academia")
            flash("No se pudo guardar el logo. Vuelva a intentarlo.", "danger")
            return render_template("academias/identidad_visual.html", academia=academia), 500
    return render_template("academias/identidad_visual.html", academia=academia)


@academias_bp.route("/", methods=["GET"])
@login_required
def index():
    academias = Academia.query.order_by(Academia.nombre.asc()).all()
    return render_template("academias/index.html", academias=academias)


@academias_bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    """
    Crea academia (incluye externas) sin JavaScript.
    - Evita duplicados por nombre (case-insensitive)
    """
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()

        if not nombre:
            flash("Nombre requerido.", "danger")
            return redirect(request.url)

        existente = Academia.query.filter(func.lower(Academia.nombre) == nombre.lower()).first()
        if existente:
            flash("La academia ya existe.", "info")
            return redirect(url_for("academias.index"))

        a = Academia(nombre=nombre, activo=True)
        db.session.add(a)
        db.session.commit()

        flash("Academia creada correctamente.", "success")
        return redirect(url_for("academias.index"))

    return render_template("academias/nueva.html")


@academias_bp.route("/<int:academia_id>/editar", methods=["GET", "POST"])
@login_required
def editar(academia_id):
    a = Academia.query.get_or_404(academia_id)

    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        activo = request.form.get("activo") == "1"

        if not nombre:
            flash("Nombre requerido.", "danger")
            return redirect(request.url)

        # evitar duplicado con otra academia
        existe_otro = (
            Academia.query
            .filter(func.lower(Academia.nombre) == nombre.lower(), Academia.id != a.id)
            .first()
        )
        if existe_otro:
            flash("Ya existe otra academia con ese nombre.", "danger")
            return redirect(request.url)

        a.nombre = nombre
        a.activo = activo
        db.session.commit()

        flash("Academia actualizada.", "success")
        return redirect(url_for("academias.index"))

    return render_template("academias/editar.html", academia=a)


@academias_bp.route("/<int:academia_id>/toggle", methods=["POST"])
@login_required
def toggle(academia_id):
    """
    Activar/Desactivar rápido.
    """
    a = Academia.query.get_or_404(academia_id)
    a.activo = not bool(a.activo)
    db.session.commit()
    flash("Estado actualizado.", "success")
    return redirect(url_for("academias.index"))


@academias_bp.route("/<int:academia_id>/eliminar", methods=["POST"])
@login_required
def eliminar(academia_id):
    """
    Eliminación física (úsala solo si estás seguro).
    Si hay FK en resultados/usuarios/etc. fallará por integridad.
    """
    a = Academia.query.get_or_404(academia_id)
    try:
        db.session.delete(a)
        db.session.commit()
        flash("Academia eliminada.", "success")
    except Exception:
        db.session.rollback()
        flash("No se pudo eliminar: está siendo usada por otros registros. Desactívala mejor.", "danger")

    return redirect(url_for("academias.index"))
