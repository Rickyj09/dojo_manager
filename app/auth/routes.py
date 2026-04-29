from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.models import User


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _redirect_after_login(user):
    if user.has_role("SUPERADMIN") or user.has_role("ADMIN"):
        return redirect(url_for("admin.dashboard"))

    if user.has_role("PROFESOR") or user.has_role("COACH"):
        return redirect(url_for("alumnos.index"))

    return redirect(url_for("public.home"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # Si ya existe una sesión válida, redirigimos según rol
    # en lugar de forzar siempre el dashboard admin.
    if current_user.is_authenticated:
        return _redirect_after_login(current_user)

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()

        if not user or not user.check_password(password):
            flash("Usuario o contraseña incorrectos", "danger")
            return render_template("login.html")

        if not user.is_active:
            flash("Usuario inactivo. Contacte al administrador.", "warning")
            return render_template("login.html")

        login_user(user)
        flash(f"Bienvenido {user.username}", "success")

        if user.must_change_password:
            return redirect(url_for("profile.index"))

        return _redirect_after_login(user)

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada correctamente", "info")
    return redirect(url_for("public.home"))
