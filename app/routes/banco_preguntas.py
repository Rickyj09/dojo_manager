from flask import Blueprint, render_template, request, redirect, url_for, flash, g
from flask_login import login_required, current_user

from app.extensions import db
from app.models.banco_preguntas import BancoPregunta, PreguntaOpcion
from app.models.grado import Grado

banco_preguntas_bp = Blueprint("banco_preguntas", __name__, url_prefix="/banco-preguntas")


# =========================================================
# Helpers
# =========================================================
def _academia_id_or_403():
    academia_id = getattr(g, "academia_id", None) or getattr(current_user, "academia_id", None)
    if not academia_id:
        flash("No hay academia seleccionada.", "warning")
        return None
    return academia_id


# =========================================================
# Listado
# =========================================================
@banco_preguntas_bp.route("/", methods=["GET"])
@login_required
def list():
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    q = BancoPregunta.query.filter_by(academia_id=academia_id)

    disciplina = (request.args.get("disciplina") or "").strip()
    tipo = (request.args.get("tipo") or "").strip()
    grado_id = request.args.get("grado_id", type=int)
    texto = (request.args.get("texto") or "").strip()

    if disciplina:
        q = q.filter(BancoPregunta.disciplina == disciplina)

    if tipo:
        q = q.filter(BancoPregunta.tipo == tipo)

    if grado_id:
        q = q.filter(BancoPregunta.grado_id == grado_id)

    if texto:
        like = f"%{texto}%"
        q = q.filter(BancoPregunta.enunciado.ilike(like))

    items = q.order_by(BancoPregunta.id.desc()).all()

    grados = (
        Grado.query
        .filter_by(academia_id=academia_id, activo=True)
        .order_by(Grado.orden.asc())
        .all()
    )
    grados_map = {g.id: g for g in grados}

    return render_template(
        "banco_preguntas/list.html",
        items=items,
        grados=grados,
        grados_map=grados_map,
        filtros={
            "disciplina": disciplina,
            "tipo": tipo,
            "grado_id": grado_id,
            "texto": texto,
        },
    )


# =========================================================
# Crear nueva pregunta
# =========================================================
@banco_preguntas_bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    grados = (
        Grado.query
        .filter_by(academia_id=academia_id, activo=True)
        .order_by(Grado.orden.asc())
        .all()
    )

    if request.method == "POST":
        grado_id = request.form.get("grado_id", type=int)
        disciplina = (request.form.get("disciplina") or "").strip().upper()
        tipo = (request.form.get("tipo") or "").strip().upper()
        enunciado = (request.form.get("enunciado") or "").strip()
        puntaje_max = request.form.get("puntaje_max", type=float)
        dificultad = request.form.get("dificultad", type=int)
        tags = (request.form.get("tags") or "").strip() or None
        activo = request.form.get("activo") == "1"

        if not grado_id:
            flash("Selecciona el grado.", "danger")
            return render_template("banco_preguntas/form.html", item=None, grados=grados)

        if not disciplina:
            flash("La disciplina es obligatoria.", "danger")
            return render_template("banco_preguntas/form.html", item=None, grados=grados)

        if tipo not in ("OPCION_MULTIPLE", "VERDADERO_FALSO", "ABIERTA"):
            flash("Tipo inválido.", "danger")
            return render_template("banco_preguntas/form.html", item=None, grados=grados)

        if not enunciado:
            flash("El enunciado es obligatorio.", "danger")
            return render_template("banco_preguntas/form.html", item=None, grados=grados)

        item = BancoPregunta(
            academia_id=academia_id,
            grado_id=grado_id,
            disciplina=disciplina,
            tipo=tipo,
            enunciado=enunciado,
            puntaje_max=puntaje_max if puntaje_max is not None else 1.00,
            dificultad=dificultad,
            tags=tags,
            activo=activo,
        )
        db.session.add(item)
        db.session.commit()

        flash("Pregunta creada.", "success")

        if tipo == "ABIERTA":
            return redirect(url_for("banco_preguntas.list"))

        return redirect(url_for("banco_preguntas.opciones", pregunta_id=item.id))

    return render_template("banco_preguntas/form.html", item=None, grados=grados)


# =========================================================
# Eliminar pregunta
# =========================================================
@banco_preguntas_bp.route("/<int:pregunta_id>/eliminar", methods=["POST"])
@login_required
def eliminar(pregunta_id: int):
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    item = BancoPregunta.query.filter_by(id=pregunta_id, academia_id=academia_id).first_or_404()

    db.session.delete(item)
    db.session.commit()

    flash("Pregunta eliminada.", "success")
    return redirect(url_for("banco_preguntas.list"))


# =========================================================
# Gestionar opciones
# =========================================================
@banco_preguntas_bp.route("/<int:pregunta_id>/opciones", methods=["GET", "POST"])
@login_required
def opciones(pregunta_id: int):
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    pregunta = BancoPregunta.query.filter_by(id=pregunta_id, academia_id=academia_id).first_or_404()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            texto = (request.form.get("texto") or "").strip()
            es_correcta = request.form.get("es_correcta") == "1"
            orden = request.form.get("orden", type=int) or 0

            if not texto:
                flash("El texto de la opción es obligatorio.", "danger")
                return redirect(url_for("banco_preguntas.opciones", pregunta_id=pregunta.id))

            # Si es verdadero/falso u opción múltiple y esta nueva opción se marca correcta,
            # opcionalmente puedes limpiar otras correctas. Por ahora no lo forzamos.
            op = PreguntaOpcion(
                pregunta_id=pregunta.id,
                texto=texto,
                es_correcta=es_correcta,
                orden=orden,
            )
            db.session.add(op)
            db.session.commit()
            flash("Opción agregada.", "success")

        elif action == "remove":
            opcion_id = request.form.get("opcion_id", type=int)
            op = PreguntaOpcion.query.filter_by(id=opcion_id, pregunta_id=pregunta.id).first()

            if op:
                db.session.delete(op)
                db.session.commit()
                flash("Opción eliminada.", "success")
            else:
                flash("Opción no encontrada.", "warning")

        return redirect(url_for("banco_preguntas.opciones", pregunta_id=pregunta.id))

    opciones = (
        PreguntaOpcion.query
        .filter_by(pregunta_id=pregunta.id)
        .order_by(PreguntaOpcion.orden.asc(), PreguntaOpcion.id.asc())
        .all()
    )

    return render_template(
        "banco_preguntas/opciones.html",
        pregunta=pregunta,
        opciones=opciones,
    )