from datetime import date, datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func

from app.extensions import db
from app.models import Alumno, Asistencia, Role, Sucursal, User


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ============================================================
# PERMISOS / TENANCY
# ============================================================

def can_access_admin() -> bool:
    """
    Acceso general al panel administrativo.
    PROFESOR puede entrar al dashboard/asistencias,
    pero no administrar usuarios.
    """
    return (
        current_user.is_authenticated
        and (
            current_user.has_role("SUPERADMIN")
            or current_user.has_role("ADMIN")
            or current_user.has_role("PROFESOR")
        )
    )


def can_manage_users() -> bool:
    """
    AdministraciÃ³n de usuarios Ãºnicamente para ADMIN/SUPERADMIN.
    """
    return (
        current_user.is_authenticated
        and (
            current_user.has_role("SUPERADMIN")
            or current_user.has_role("ADMIN")
        )
    )


def _academia_id_actual():
    """
    Devuelve la academia del usuario actual.

    Un SUPERADMIN global puede no tener academia asociada.
    """
    academia_id = getattr(current_user, "academia_id", None)

    if academia_id:
        return academia_id

    if current_user.has_role("SUPERADMIN"):
        return None

    abort(403)


def _academia_id_requerida():
    """
    Para operaciones que necesariamente deben pertenecer
    a una academia concreta.
    """
    academia_id = _academia_id_actual()

    if academia_id is None:
        abort(403)

    return academia_id


def _usuario_visible_o_404(user_id):
    """
    ADMIN:
        solo puede acceder a usuarios de su propia academia.

    SUPERADMIN global:
        puede acceder globalmente.
    """
    academia_id = _academia_id_actual()

    query = User.query.filter_by(id=user_id)

    if academia_id is not None:
        query = query.filter_by(academia_id=academia_id)

    user = query.first_or_404()

    # Un ADMIN de academia nunca administra una cuenta SUPERADMIN.
    if user.has_role("SUPERADMIN") and not current_user.has_role("SUPERADMIN"):
        abort(403)

    return user


def _sucursal_visible_o_404(sucursal_id):
    """
    ADMIN/PROFESOR:
        Ãºnicamente sucursales de su academia.

    SUPERADMIN global:
        puede acceder globalmente.
    """
    academia_id = _academia_id_actual()

    query = Sucursal.query.filter_by(id=sucursal_id)

    if academia_id is not None:
        query = query.filter_by(academia_id=academia_id)

    return query.first_or_404()


def _roles_asignables():
    """
    ADMIN de tenant no puede asignar SUPERADMIN.

    SUPERADMIN sÃ­ puede ver todos los roles.
    """
    query = Role.query

    if not current_user.has_role("SUPERADMIN"):
        query = query.filter(Role.name != "SUPERADMIN")

    return query.order_by(Role.name).all()


def _roles_seleccionados_o_403(roles_ids):
    """
    Valida tambiÃ©n el POST, evitando que alguien agregue manualmente
    el ID de SUPERADMIN aunque no aparezca en el formulario.
    """
    permitidos = {
        role.id: role
        for role in _roles_asignables()
    }

    seleccionados = []

    for rid in roles_ids:
        try:
            role_id = int(rid)
        except (TypeError, ValueError):
            abort(400)

        role = permitidos.get(role_id)

        if role is None:
            abort(403)

        seleccionados.append(role)

    return seleccionados


# ============================================================
# DASHBOARD
# ============================================================

@admin_bp.route("/")
@login_required
def dashboard():
    if not can_access_admin():
        abort(403)

    academia_id = _academia_id_actual()

    if academia_id is not None:
        total_alumnos = Alumno.query.filter_by(
            academia_id=academia_id
        ).count()

        total_sucursales = Sucursal.query.filter_by(
            academia_id=academia_id
        ).count()

        total_usuarios = User.query.filter_by(
            academia_id=academia_id
        ).count()

    else:
        # Solo SUPERADMIN global llega aquÃ­.
        total_alumnos = Alumno.query.count()
        total_sucursales = Sucursal.query.count()
        total_usuarios = User.query.count()

    return render_template(
        "admin/dashboard.html",
        total_alumnos=total_alumnos,
        total_sucursales=total_sucursales,
        total_usuarios=total_usuarios,
    )


# ============================================================
# USUARIOS
# ============================================================

@admin_bp.route("/usuarios")
@login_required
def usuarios():
    if not can_manage_users():
        abort(403)

    academia_id = _academia_id_actual()

    if academia_id is not None:
        usuarios_query = User.query.filter_by(
            academia_id=academia_id
        )

        # ADMIN de tenant no necesita ver cuentas SUPERADMIN.
        if not current_user.has_role("SUPERADMIN"):
            usuarios_query = usuarios_query.filter(
                ~User.roles.any(Role.name == "SUPERADMIN")
            )

        usuarios = usuarios_query.order_by(
            User.username
        ).all()

    else:
        usuarios = User.query.order_by(
            User.username
        ).all()

    return render_template(
        "admin/usuarios/index.html",
        usuarios=usuarios,
    )


# ============================================================
# ROLES
# ============================================================

@admin_bp.route("/roles")
@login_required
def roles():
    if not can_manage_users():
        abort(403)

    academia_id = _academia_id_actual()

    if academia_id is None:
        # SUPERADMIN global: conteo global.
        roles_data = (
            db.session.query(
                Role.id,
                Role.name,
                func.count(User.id).label("total_usuarios"),
            )
            .outerjoin(Role.users)
            .group_by(Role.id, Role.name)
            .order_by(Role.name)
            .all()
        )

    else:
        # ADMIN tenant: puede ver catÃ¡logo de roles,
        # pero el conteo corresponde Ãºnicamente a su academia.
        roles_data = (
            db.session.query(
                Role.id,
                Role.name,
                func.count(
                    case(
                        (
                            User.academia_id == academia_id,
                            User.id,
                        ),
                        else_=None,
                    )
                ).label("total_usuarios"),
            )
            .outerjoin(Role.users)
            .group_by(Role.id, Role.name)
            .order_by(Role.name)
            .all()
        )

    return render_template(
        "admin/roles.html",
        roles=roles_data,
    )


@admin_bp.route("/roles/nuevo", methods=["GET", "POST"])
@login_required
def role_nuevo():
    # Los roles son catÃ¡logo global del sistema.
    if not current_user.has_role("SUPERADMIN"):
        abort(403)

    if request.method == "POST":
        name = request.form["name"].strip().upper()

        if Role.query.filter_by(name=name).first():
            flash("El rol ya existe", "danger")
            return redirect(
                url_for("admin.role_nuevo")
            )

        role = Role(name=name)

        db.session.add(role)
        db.session.commit()

        flash(
            "Rol creado correctamente",
            "success",
        )

        return redirect(
            url_for("admin.roles")
        )

    return render_template(
        "admin/role_form.html"
    )


@admin_bp.route(
    "/roles/<int:id>/editar",
    methods=["GET", "POST"],
)
@login_required
def role_editar(id):
    # Los roles son catÃ¡logo global del sistema.
    if not current_user.has_role("SUPERADMIN"):
        abort(403)

    role = Role.query.get_or_404(id)

    if request.method == "POST":
        role.name = request.form["name"].strip().upper()

        db.session.commit()

        flash(
            "Rol actualizado",
            "success",
        )

        return redirect(
            url_for("admin.roles")
        )

    return render_template(
        "admin/role_form.html",
        role=role,
    )


@admin_bp.route(
    "/roles/<int:id>/eliminar",
    methods=["POST"],
)
@login_required
def role_eliminar(id):
    # Los roles son catÃ¡logo global del sistema.
    if not current_user.has_role("SUPERADMIN"):
        abort(403)

    role = Role.query.get_or_404(id)

    if role.users and len(role.users) > 0:
        flash(
            "No se puede eliminar un rol asignado a usuarios",
            "danger",
        )

        return redirect(
            url_for("admin.roles")
        )

    db.session.delete(role)
    db.session.commit()

    flash(
        "Rol eliminado",
        "success",
    )

    return redirect(
        url_for("admin.roles")
    )


# ============================================================
# NUEVO USUARIO
# ============================================================

@admin_bp.route(
    "/usuarios/nuevo",
    methods=["GET", "POST"],
)
@login_required
def usuario_nuevo():
    if not can_manage_users():
        abort(403)

    # El formulario actual no permite escoger academia.
    # Por seguridad, se crea siempre dentro del tenant actual.
    academia_id = _academia_id_requerida()

    roles_disponibles = _roles_asignables()

    if request.method == "POST":
        user = User(
            username=request.form["username"],
            email=request.form["email"],
            is_active=True,
            academia_id=academia_id,
        )

        user.set_password(
            request.form["password"]
        )

        roles_ids = request.form.getlist(
            "roles"
        )

        for role in _roles_seleccionados_o_403(
            roles_ids
        ):
            user.roles.append(role)

        db.session.add(user)
        db.session.commit()

        flash(
            "Usuario creado",
            "success",
        )

        return redirect(
            url_for("admin.usuarios")
        )

    return render_template(
        "admin/usuarios/form.html",
        user=None,
        roles=roles_disponibles,
    )


# ============================================================
# EDITAR USUARIO
# ============================================================

@admin_bp.route(
    "/usuarios/<int:id>/editar",
    methods=["GET", "POST"],
)
@login_required
def usuario_editar(id):
    if not can_manage_users():
        abort(403)

    user = _usuario_visible_o_404(id)

    roles_disponibles = _roles_asignables()

    if request.method == "POST":
        user.username = request.form["username"]
        user.email = request.form["email"]
        user.is_active = (
            "is_active" in request.form
        )

        user.roles.clear()

        roles_ids = request.form.getlist(
            "roles"
        )

        for role in _roles_seleccionados_o_403(
            roles_ids
        ):
            user.roles.append(role)

        db.session.commit()

        flash(
            "Usuario actualizado",
            "success",
        )

        return redirect(
            url_for("admin.usuarios")
        )

    return render_template(
        "admin/usuarios/form.html",
        user=user,
        roles=roles_disponibles,
    )


# ============================================================
# ELIMINAR USUARIO
# ============================================================

@admin_bp.route(
    "/usuarios/<int:id>/eliminar",
    methods=["POST"],
)
@login_required
def usuario_eliminar(id):
    if not can_manage_users():
        abort(403)

    user = _usuario_visible_o_404(id)

    if user.id == current_user.id:
        flash(
            "No puede eliminar su propio usuario",
            "danger",
        )

        return redirect(
            url_for("admin.usuarios")
        )

    if user.username == "admin":
        flash(
            "No se puede eliminar el usuario admin",
            "danger",
        )

        return redirect(
            url_for("admin.usuarios")
        )

    db.session.delete(user)
    db.session.commit()

    flash(
        "Usuario eliminado",
        "success",
    )

    return redirect(
        url_for("admin.usuarios")
    )


# ============================================================
# RESET PASSWORD
# ============================================================

@admin_bp.route(
    "/usuarios/<int:id>/reset-password",
    methods=["GET", "POST"],
)
@login_required
def usuario_reset_password(id):
    if not can_manage_users():
        abort(403)

    user = _usuario_visible_o_404(id)

    if request.method == "POST":
        password = request.form.get(
            "password"
        )

        password2 = request.form.get(
            "password2"
        )

        if not password or not password2:
            flash(
                "Debe ingresar la contraseÃ±a",
                "danger",
            )

            return redirect(
                request.url
            )

        if password != password2:
            flash(
                "Las contraseÃ±as no coinciden",
                "danger",
            )

            return redirect(
                request.url
            )

        user.set_password(password)
        user.must_change_password = True

        db.session.commit()

        flash(
            "ContraseÃ±a actualizada correctamente",
            "success",
        )

        return redirect(
            url_for("admin.usuarios")
        )

    return render_template(
        "admin/usuarios/reset_password.html",
        user=user,
    )


# ============================================================
# ASIGNAR SUCURSAL
# ============================================================

@admin_bp.route(
    "/usuarios/<int:user_id>/asignar-sucursal",
    methods=["GET", "POST"],
)
@login_required
def asignar_sucursal(user_id):
    if not can_manage_users():
        abort(403)

    user = _usuario_visible_o_404(
        user_id
    )

    if not user.has_role("PROFESOR"):
        flash(
            "Este usuario no es profesor",
            "danger",
        )

        return redirect(
            url_for("admin.usuarios")
        )

    # Para SUPERADMIN global, tomamos la academia
    # del usuario que estÃ¡ siendo administrado.
    academia_id = getattr(
        user,
        "academia_id",
        None,
    )

    if not academia_id:
        abort(400)

    sucursales = (
        Sucursal.query
        .filter_by(
            academia_id=academia_id,
            activo=True,
        )
        .order_by(
            Sucursal.nombre
        )
        .all()
    )

    if request.method == "POST":
        sucursal_id = request.form.get(
            "sucursal_id",
            type=int,
        )

        if not sucursal_id:
            flash(
                "Debe seleccionar una sucursal",
                "danger",
            )

            return redirect(
                request.url
            )

        sucursal = Sucursal.query.filter_by(
            id=sucursal_id,
            academia_id=academia_id,
            activo=True,
        ).first_or_404()

        user.sucursal_id = sucursal.id

        db.session.commit()

        flash(
            "Sucursal asignada correctamente",
            "success",
        )

        return redirect(
            url_for("admin.usuarios")
        )

    return render_template(
        "admin/usuarios/asignar_sucursal.html",
        usuario=user,
        sucursales=sucursales,
    )


# ============================================================
# ASISTENCIAS
# ============================================================

@admin_bp.route(
    "/asistencias",
    methods=["GET"],
)
@login_required
def asistencias():
    if not can_access_admin():
        abort(403)

    fecha_str = request.args.get(
        "fecha"
    )

    try:
        fecha = (
            datetime.strptime(
                fecha_str,
                "%Y-%m-%d",
            ).date()
            if fecha_str
            else date.today()
        )

    except ValueError:
        abort(400)

    academia_id_actual = (
        _academia_id_actual()
    )

    if academia_id_actual is None:
        # SUPERADMIN global.
        sucursales_query = (
            Sucursal.query
            .filter_by(activo=True)
        )

    else:
        sucursales_query = (
            Sucursal.query
            .filter_by(
                academia_id=academia_id_actual,
                activo=True,
            )
        )

    sucursales = (
        sucursales_query
        .order_by(Sucursal.nombre)
        .all()
    )

    # PROFESOR queda bloqueado
    # a su sucursal.
    if current_user.has_role(
        "PROFESOR"
    ):
        if not current_user.sucursal_id:
            flash(
                "Tu usuario no tiene sucursal asignada. "
                "Pide al admin que te la asigne.",
                "danger",
            )

            return redirect(
                url_for("admin.dashboard")
            )

        sucursal_id = (
            current_user.sucursal_id
        )

    else:
        sucursal_id = request.args.get(
            "sucursal_id",
            type=int,
        )

    if not sucursal_id:
        return render_template(
            "admin/asistencias.html",
            fecha=fecha,
            sucursal_id=None,
            sucursales=sucursales,
            alumnos=[],
            asistencias_map={},
        )

    sucursal = _sucursal_visible_o_404(
        sucursal_id
    )

    if (
        current_user.has_role("PROFESOR")
        and current_user.sucursal_id
        != sucursal.id
    ):
        abort(403)

    alumnos = (
        Alumno.query
        .filter_by(
            academia_id=sucursal.academia_id,
            sucursal_id=sucursal.id,
        )
        .order_by(
            Alumno.apellidos,
            Alumno.nombres,
        )
        .all()
    )

    asistencias_db = (
        Asistencia.query
        .filter_by(
            academia_id=sucursal.academia_id,
            fecha=fecha,
            sucursal_id=sucursal.id,
        )
        .all()
    )

    asistencias_map = {
        asistencia.alumno_id: asistencia
        for asistencia in asistencias_db
    }

    return render_template(
        "admin/asistencias.html",
        fecha=fecha,
        sucursal_id=sucursal.id,
        sucursales=sucursales,
        alumnos=alumnos,
        asistencias_map=asistencias_map,
    )


# ============================================================
# GUARDAR ASISTENCIAS
# ============================================================

@admin_bp.route(
    "/asistencias/guardar",
    methods=["POST"],
)
@login_required
def asistencias_guardar():
    if not can_access_admin():
        abort(403)

    fecha_str = request.form.get(
        "fecha"
    )

    try:
        fecha = datetime.strptime(
            fecha_str,
            "%Y-%m-%d",
        ).date()

    except (TypeError, ValueError):
        abort(400)

    sucursal_id = request.form.get(
        "sucursal_id",
        type=int,
    )

    if not sucursal_id:
        abort(400)

    sucursal = _sucursal_visible_o_404(
        sucursal_id
    )

    if (
        current_user.has_role("PROFESOR")
        and current_user.sucursal_id
        != sucursal.id
    ):
        abort(403)

    alumnos = (
        Alumno.query
        .filter_by(
            academia_id=sucursal.academia_id,
            sucursal_id=sucursal.id,
        )
        .all()
    )

    for alumno in alumnos:
        key = f"estado_{alumno.id}"

        estado = request.form.get(
            key,
            "A",
        )

        asistencia = (
            Asistencia.query
            .filter_by(
                academia_id=sucursal.academia_id,
                fecha=fecha,
                alumno_id=alumno.id,
                sucursal_id=sucursal.id,
            )
            .first()
        )

        if asistencia:
            asistencia.estado = estado
            asistencia.registrado_por_id = (
                current_user.id
            )

        else:
            asistencia = Asistencia(
                academia_id=sucursal.academia_id,
                fecha=fecha,
                alumno_id=alumno.id,
                sucursal_id=sucursal.id,
                estado=estado,
                registrado_por_id=current_user.id,
            )

            db.session.add(
                asistencia
            )

    db.session.commit()

    flash(
        "Asistencia guardada correctamente.",
        "success",
    )

    return redirect(
        url_for(
            "admin.asistencias",
            fecha=fecha.strftime(
                "%Y-%m-%d"
            ),
            sucursal_id=sucursal.id,
        )
    )
