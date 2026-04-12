from flask import Blueprint, abort, render_template, flash, request, redirect, url_for
from flask_login import login_required, current_user
from app.extensions import db
##from app.auth.decorators import admin_required
from app.models import User,Role, Alumno,Sucursal
from sqlalchemy import func
from datetime import date, datetime
from app.models import Asistencia


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

def can_access_admin() -> bool:
    return (
        current_user.is_authenticated
        and (
            current_user.has_role("SUPERADMIN")
            or current_user.has_role("ADMIN")
            or current_user.has_role("PROFESOR")
        )
    )


@admin_bp.route("/")
@login_required
def dashboard():
    if not can_access_admin():
        abort(403)

    total_alumnos = Alumno.query.count()
    total_sucursales = Sucursal.query.count()
    total_usuarios = User.query.count()

    return render_template(
        "admin/dashboard.html",
        total_alumnos=total_alumnos,
        total_sucursales=total_sucursales,
        total_usuarios=total_usuarios
    )



@admin_bp.route("/usuarios")
@login_required
#@admin_required
def usuarios():
    usuarios = User.query.order_by(User.username).all()
    return render_template(
        "admin/usuarios/index.html",
        usuarios=usuarios
    )

@admin_bp.route("/roles")
@login_required
#@admin_required
def roles():
    roles = (
        db.session.query(
            Role.id,
            Role.name,
            func.count(User.id).label("total_usuarios")
        )
        .outerjoin(Role.users)
        .group_by(Role.id, Role.name)
        .order_by(Role.name)
        .all()
    )

    return render_template("admin/roles.html", roles=roles)



@admin_bp.route("/roles/nuevo", methods=["GET", "POST"])
@login_required
#@admin_required
def role_nuevo():
    if request.method == "POST":
        name = request.form["name"].strip().upper()

        if Role.query.filter_by(name=name).first():
            flash("El rol ya existe", "danger")
            return redirect(url_for("admin.role_nuevo"))

        role = Role(name=name)
        db.session.add(role)
        db.session.commit()

        flash("Rol creado correctamente", "success")
        return redirect(url_for("admin.roles"))

    return render_template("admin/role_form.html")


@admin_bp.route("/roles/<int:id>/editar", methods=["GET", "POST"])
@login_required
#@admin_required
def role_editar(id):
    role = Role.query.get_or_404(id)

    if request.method == "POST":
        role.name = request.form["name"].strip().upper()
        db.session.commit()

        flash("Rol actualizado", "success")
        return redirect(url_for("admin.roles"))

    return render_template("admin/role_form.html", role=role)


@admin_bp.route("/roles/<int:id>/eliminar", methods=["POST"])
@login_required
#@admin_required
def role_eliminar(id):
    role = Role.query.get_or_404(id)

    # Validación: si el rol está asignado a usuarios, no permitir borrar
    if role.users and len(role.users) > 0:
        flash("No se puede eliminar un rol asignado a usuarios", "danger")
        return redirect(url_for("admin.roles"))

    db.session.delete(role)
    db.session.commit()
    flash("Rol eliminado", "success")
    return redirect(url_for("admin.roles"))


## Usuario Nuevo
@admin_bp.route("/usuarios/nuevo", methods=["GET", "POST"])
@login_required
#@admin_required
def usuario_nuevo():
    roles = Role.query.order_by(Role.name).all()

    if request.method == "POST":
        user = User(
            username=request.form["username"],
            email=request.form["email"],
            is_active=True
        )
        user.set_password(request.form["password"])

        roles_ids = request.form.getlist("roles")
        for rid in roles_ids:
            role = Role.query.get(int(rid))
            user.roles.append(role)

        db.session.add(user)
        db.session.commit()

        flash("Usuario creado", "success")
        return redirect(url_for("admin.usuarios"))

    return render_template(
        "admin/usuarios/form.html",
        user=None,
        roles=roles
    )

## Editsr usuario + rol

@admin_bp.route("/usuarios/<int:id>/editar", methods=["GET", "POST"])
@login_required
#@admin_required
def usuario_editar(id):
    user = User.query.get_or_404(id)
    roles = Role.query.order_by(Role.name).all()

    if request.method == "POST":
        user.username = request.form["username"]
        user.email = request.form["email"]
        user.is_active = "is_active" in request.form

        user.roles.clear()
        roles_ids = request.form.getlist("roles")
        for rid in roles_ids:
            role = Role.query.get(int(rid))
            user.roles.append(role)

        db.session.commit()
        flash("Usuario actualizado", "success")
        return redirect(url_for("admin.usuarios"))

    return render_template(
        "admin/usuarios/form.html",
        user=user,
        roles=roles
    )


@admin_bp.route("/usuarios/<int:id>/eliminar", methods=["POST"])
@login_required
#@admin_required
def usuario_eliminar(id):
    user = User.query.get_or_404(id)

    if user.username == "admin":
        flash("No se puede eliminar el usuario admin", "danger")
        return redirect(url_for("admin.usuarios"))

    db.session.delete(user)
    db.session.commit()
    flash("Usuario eliminado", "success")
    return redirect(url_for("admin.usuarios"))


## Reset Password (ADMIN)

@admin_bp.route("/usuarios/<int:id>/reset-password", methods=["GET", "POST"])
@login_required
#@admin_required
def usuario_reset_password(id):
    user = User.query.get_or_404(id)

    if request.method == "POST":
        password = request.form.get("password")
        password2 = request.form.get("password2")

        if not password or not password2:
            flash("Debe ingresar la contraseña", "danger")
            return redirect(request.url)

        if password != password2:
            flash("Las contraseñas no coinciden", "danger")
            return redirect(request.url)

        user.set_password(password)
        user.must_change_password = True
        db.session.commit()

        flash("Contraseña actualizada correctamente", "success")
        return redirect(url_for("admin.usuarios"))

    return render_template(
        "admin/usuarios/reset_password.html",
        user=user
    )

def admin_required():
    return current_user.is_authenticated and current_user.has_role("ADMIN")


## asignar sucursal
@admin_bp.route("/usuarios/<int:user_id>/asignar-sucursal", methods=["GET", "POST"])
@login_required
def asignar_sucursal(user_id):
    user = User.query.get_or_404(user_id)

    # Seguridad: solo profesores
    if not user.has_role("PROFESOR"):
        flash("Este usuario no es profesor", "danger")
        return redirect(url_for("admin.usuarios"))

    sucursales = Sucursal.query.filter_by(activo=True).all()

    if request.method == "POST":
        sucursal_id = request.form.get("sucursal_id")

        if not sucursal_id:
            flash("Debe seleccionar una sucursal", "danger")
            return redirect(request.url)

        user.sucursal_id = int(sucursal_id)
        db.session.commit()

        flash("Sucursal asignada correctamente", "success")
        return redirect(url_for("admin.usuarios"))

    return render_template(
        "admin/usuarios/asignar_sucursal.html",
        usuario=user,
        sucursales=sucursales
    )

@admin_bp.route("/asistencias", methods=["GET"])
@login_required
def asistencias():
    if not (current_user.has_role("SUPERADMIN") or current_user.has_role("ADMIN") or current_user.has_role("PROFESOR")):
        abort(403)

    # fecha filtro
    fecha_str = request.args.get("fecha")
    fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date() if fecha_str else date.today()

    # sucursal: profesor bloqueado a su sucursal
    if current_user.has_role("PROFESOR"):
        if not current_user.sucursal_id:
            flash("Tu usuario no tiene sucursal asignada. Pide al admin que te la asigne.", "danger")
            return redirect(url_for("admin.dashboard"))
        sucursal_id = current_user.sucursal_id
    else:
        sucursal_id = request.args.get("sucursal_id", type=int)

    sucursales = Sucursal.query.filter_by(activo=True).order_by(Sucursal.nombre).all()

    # si no elige sucursal (ADMIN), solo muestra pantalla para seleccionar
    if not sucursal_id:
        return render_template(
            "admin/asistencias.html",
            fecha=fecha,
            sucursal_id=None,
            sucursales=sucursales,
            alumnos=[],
            asistencias_map={}
        )

    # alumnos de la sucursal
    alumnos = Alumno.query.filter_by(sucursal_id=sucursal_id).order_by(Alumno.apellidos, Alumno.nombres).all()

    # asistencias existentes del día
    asistencias = Asistencia.query.filter_by(fecha=fecha, sucursal_id=sucursal_id).all()
    asistencias_map = {a.alumno_id: a for a in asistencias}

    return render_template(
        "admin/asistencias.html",
        fecha=fecha,
        sucursal_id=sucursal_id,
        sucursales=sucursales,
        alumnos=alumnos,
        asistencias_map=asistencias_map
    )

@admin_bp.route("/asistencias/guardar", methods=["POST"])
@login_required
def asistencias_guardar():
    if not (current_user.has_role("SUPERADMIN") or current_user.has_role("ADMIN") or current_user.has_role("PROFESOR")):
        abort(403)

    fecha = datetime.strptime(request.form["fecha"], "%Y-%m-%d").date()
    sucursal_id = int(request.form["sucursal_id"])

    # profesor: validar que sea su sucursal
    if current_user.has_role("PROFESOR") and current_user.sucursal_id != sucursal_id:
        abort(403)

    # Recibimos estado por alumno: estado_<id>
    # Ej: estado_15 = P/A/T/J
    alumnos = Alumno.query.filter_by(sucursal_id=sucursal_id).all()
    for al in alumnos:
        key = f"estado_{al.id}"
        estado = request.form.get(key, "A")  # default ausente si no llega

        # upsert por unique constraint (fecha, alumno_id, sucursal_id)
        asistencia = Asistencia.query.filter_by(
            fecha=fecha, alumno_id=al.id, sucursal_id=sucursal_id
        ).first()

        if asistencia:
            asistencia.estado = estado
            asistencia.registrado_por_id = current_user.id
        else:
            asistencia = Asistencia(
                fecha=fecha,
                alumno_id=al.id,
                sucursal_id=sucursal_id,
                estado=estado,
                registrado_por_id=current_user.id
            )
            db.session.add(asistencia)

    db.session.commit()
    flash("Asistencia guardada correctamente.", "success")
    return redirect(url_for("admin.asistencias", fecha=fecha.strftime("%Y-%m-%d"), sucursal_id=sucursal_id))
