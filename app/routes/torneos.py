from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.torneo import Torneo

torneos_bp = Blueprint("torneos", __name__, url_prefix="/torneos")

def _academia_id_actual():
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

@torneos_bp.route("/")
@login_required
def index():
    academia_id = _academia_id_actual()

    query = Torneo.query

    if academia_id is not None:
        query = query.filter(
            Torneo.academia_id == academia_id
        )

    torneos = (
        query
        .order_by(Torneo.fecha.desc())
        .all()
    )

    return render_template(
        "torneos/index.html",
        torneos=torneos,
    )


@torneos_bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    academia_id = _academia_id_actual()

    if academia_id is None:
        abort(403)

    if request.method == "POST":
        try:
            fecha = datetime.strptime(request.form["fecha"], "%Y-%m-%d").date()
        except ValueError:
            flash("Fecha inválida", "danger")
            return redirect(request.url)

        def _money(key, default):
            raw = (request.form.get(key) or "").strip()
            if raw == "":
                return Decimal(str(default))
            # por si el usuario pone coma
            raw = raw.replace(",", ".")
            try:
                val = Decimal(raw)
            except InvalidOperation:
                raise ValueError(f"Valor inválido para {key}")
            if val < 0:
                raise ValueError(f"El valor de {key} no puede ser negativo")
            return val

        try:
            precio_poomsae = _money("precio_poomsae", 30)
            precio_combate = _money("precio_combate", 30)
            precio_ambas = _money("precio_ambas", 40)
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(request.url)
        torneo = Torneo(
            academia_id=academia_id,
            nombre=request.form["nombre"],
            ciudad=request.form.get("ciudad"),
            fecha=fecha,
            organizador=request.form.get("organizador"),
            activo=True,
            precio_poomsae=precio_poomsae,
            precio_combate=precio_combate,
            precio_ambas=precio_ambas,
        )

        db.session.add(torneo)
        db.session.commit()

        flash("Torneo registrado correctamente", "success")
        return redirect(url_for("torneos.index"))

    return render_template("torneos/nuevo.html")