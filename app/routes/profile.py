from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db

profile_bp = Blueprint("profile", __name__, url_prefix="/perfil")

@profile_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        actual = request.form.get("password_actual")
        nueva = request.form.get("password_nueva")
        confirmar = request.form.get("password_confirmar")

        if not current_user.check_password(actual):
            flash("La contraseña actual es incorrecta", "error")
            return redirect(url_for("profile.index"))

        if not nueva or nueva != confirmar:
            flash("Las contraseñas nuevas no coinciden", "error")
            return redirect(url_for("profile.index"))

        current_user.set_password(nueva)
        current_user.must_change_password = False
        db.session.commit()

        flash("Contraseña actualizada correctamente", "success")
        return redirect(url_for("profile.index"))

    return render_template("profile/index.html", user=current_user)
