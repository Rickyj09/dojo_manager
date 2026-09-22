from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.models.academia import Academia
from app.models.sucursal import Sucursal


sucursales_bp = Blueprint(
    "sucursales",
    __name__,
    url_prefix="/sucursales",
)


def _puede_administrar_sucursales():
    return (
        current_user.is_authenticated
        and (
            current_user.has_role("SUPERADMIN")
            or current_user.has_role("ADMIN")
        )
    )


def _academia_id_actual():
    """
    ADMIN:
        trabaja únicamente con su academia.

    SUPERADMIN con academia:
        trabaja con su academia.

    SUPERADMIN global sin academia:
        puede administrar globalmente.
    """
    academia_id = getattr(
        current_user,
        "academia_id",
        None,
    )

    if academia_id:
        return academia_id

    if current_user.has_role("SUPERADMIN"):
        return None

    abort(403)


def _exigir_administracion():
    if not _puede_administrar_sucursales():
        abort(403)


def _sucursal_visible_o_404(sucursal_id):
    academia_id = _academia_id_actual()

    query = Sucursal.query.filter_by(
        id=sucursal_id,
    )

    if academia_id is not None:
        query = query.filter_by(
            academia_id=academia_id,
        )

    return query.first_or_404()


def _academias_disponibles(academia_id):
    if academia_id is None:
        return (
            Academia.query
            .order_by(Academia.nombre.asc())
            .all()
        )

    academia = db.session.get(
        Academia,
        academia_id,
    )

    if academia is None:
        abort(403)

    return [academia]


def _resolver_academia_destino(academia_id_scope):
    """
    Para ADMIN el tenant lo impone el servidor.

    Solo SUPERADMIN global puede seleccionar una academia
    desde el formulario.
    """
    if academia_id_scope is not None:
        return academia_id_scope

    academia_id = request.form.get(
        "academia_id",
        type=int,
    )

    if not academia_id:
        abort(400)

    academia = db.session.get(
        Academia,
        academia_id,
    )

    if academia is None:
        abort(400)

    return academia.id


# ===============================
# LISTAR SUCURSALES
# ===============================
@sucursales_bp.route("/")
@login_required
def index():
    _exigir_administracion()

    academia_id = _academia_id_actual()

    query = Sucursal.query

    if academia_id is not None:
        query = query.filter_by(
            academia_id=academia_id,
        )

    sucursales = (
        query
        .order_by(
            Sucursal.nombre.asc()
        )
        .all()
    )

    return render_template(
        "sucursales/index.html",
        sucursales=sucursales,
    )


# ===============================
# CREAR SUCURSAL
# ===============================
@sucursales_bp.route(
    "/nuevo",
    methods=["GET", "POST"],
)
@login_required
def nuevo():
    _exigir_administracion()

    academia_id_scope = _academia_id_actual()

    academias = _academias_disponibles(
        academia_id_scope,
    )

    academia_fija = (
        academias[0]
        if academia_id_scope is not None
        else None
    )

    if request.method == "POST":
        nombre = (
            request.form.get("nombre")
            or ""
        ).strip()

        if not nombre:
            flash(
                "El nombre de la sucursal es obligatorio.",
                "danger",
            )

            return render_template(
                "sucursales/form.html",
                sucursal=None,
                academias=academias,
                academia_fija=academia_fija,
            ), 400

        academia_id = _resolver_academia_destino(
            academia_id_scope,
        )

        sucursal = Sucursal(
            nombre=nombre,
            direccion=(
                request.form.get("direccion")
                or ""
            ).strip()
            or None,
            academia_id=academia_id,
            activo=(
                "activo"
                in request.form
            ),
        )

        db.session.add(sucursal)
        db.session.commit()

        flash(
            "Sucursal creada correctamente",
            "success",
        )

        return redirect(
            url_for(
                "sucursales.index"
            )
        )

    return render_template(
        "sucursales/form.html",
        sucursal=None,
        academias=academias,
        academia_fija=academia_fija,
    )


# ===============================
# EDITAR SUCURSAL
# ===============================
@sucursales_bp.route(
    "/<int:id>/editar",
    methods=["GET", "POST"],
)
@login_required
def editar(id):
    _exigir_administracion()

    sucursal = _sucursal_visible_o_404(
        id,
    )

    academia_id_scope = _academia_id_actual()

    academias = _academias_disponibles(
        academia_id_scope,
    )

    academia_fija = (
        academias[0]
        if academia_id_scope is not None
        else None
    )

    if request.method == "POST":
        nombre = (
            request.form.get("nombre")
            or ""
        ).strip()

        if not nombre:
            flash(
                "El nombre de la sucursal es obligatorio.",
                "danger",
            )

            return render_template(
                "sucursales/form.html",
                sucursal=sucursal,
                academias=academias,
                academia_fija=academia_fija,
            ), 400

        academia_id = _resolver_academia_destino(
            academia_id_scope,
        )

        sucursal.nombre = nombre
        sucursal.direccion = (
            request.form.get("direccion")
            or ""
        ).strip() or None

        sucursal.academia_id = (
            academia_id
        )

        sucursal.activo = (
            "activo"
            in request.form
        )

        db.session.commit()

        flash(
            "Sucursal actualizada",
            "success",
        )

        return redirect(
            url_for(
                "sucursales.index"
            )
        )

    return render_template(
        "sucursales/form.html",
        sucursal=sucursal,
        academias=academias,
        academia_fija=academia_fija,
    )


# ===============================
# ELIMINAR SUCURSAL
# ===============================
@sucursales_bp.route(
    "/<int:id>/eliminar",
    methods=["POST"],
)
@login_required
def eliminar(id):
    _exigir_administracion()

    sucursal = _sucursal_visible_o_404(
        id,
    )

    db.session.delete(sucursal)
    db.session.commit()

    flash(
        "Sucursal eliminada",
        "success",
    )

    return redirect(
        url_for(
            "sucursales.index"
        )
    )