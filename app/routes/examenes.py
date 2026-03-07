from datetime import datetime, date
from decimal import Decimal
import io

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, send_file
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models.examenes import (
    Examen,
    ExamenEvaluador,
    ExamenAlumnoPregunta,
    ExamenInscripcion,
    ExamenAlumno,
    ExamenDictamen,
)
from app.models.sucursal import Sucursal
from app.models.grado import Grado
from app.models.user import User
from app.models.plantillas_examen import PlantillaExamen
from app.models.banco_preguntas import BancoPregunta, PreguntaOpcion
from app.models.alumno import Alumno
from app.models.ascenso import Ascenso

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

examenes_bp = Blueprint("examenes", __name__, url_prefix="/examenes")


# =========================================================
# Helpers
# =========================================================
def _academia_id_or_403():
    academia_id = getattr(g, "academia_id", None) or getattr(current_user, "academia_id", None)
    if not academia_id:
        flash("No hay academia seleccionada.", "warning")
        return None
    return academia_id


def _parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_time(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def _can_manage_exams():
    return True


def _is_exam_evaluator(examen_id: int, academia_id: int) -> bool:
    if getattr(current_user, "has_role", None):
        if current_user.has_role("ADMIN") or current_user.has_role("SUPERADMIN"):
            return True

    return (
        ExamenEvaluador.query
        .filter_by(academia_id=academia_id, examen_id=examen_id, user_id=current_user.id)
        .first()
        is not None
    )


def _recalcular_nota_final(examen: Examen, ins: ExamenInscripcion):
    teoria = float(ins.nota_teoria or 0)
    poomsae = float(ins.nota_poomsae or 0)
    combate = float(ins.nota_combate or 0)

    peso_teoria = float(examen.peso_teoria or 0)
    peso_poomsae = float(examen.peso_poomsae or 0)
    peso_combate = float(examen.peso_combate or 0)

    total = 0.0

    if examen.usa_teoria:
        total += teoria * (peso_teoria / 100.0)

    if examen.usa_poomsae:
        total += poomsae * (peso_poomsae / 100.0)

    if examen.usa_combate:
        total += combate * (peso_combate / 100.0)

    ins.nota_final = round(total, 2)
    return ins.nota_final


def _get_or_create_examen_alumno(examen: Examen, ins: ExamenInscripcion) -> ExamenAlumno:
    ea = ExamenAlumno.query.filter_by(examen_id=examen.id, alumno_id=ins.alumno_id).first()
    if ea:
        return ea

    ea = ExamenAlumno(
        examen_id=examen.id,
        alumno_id=ins.alumno_id,
        estado="EN_PROGRESO",
        started_at=datetime.utcnow(),
        score_auto=0,
        score_manual=0,
        score_total=0,
    )
    db.session.add(ea)
    db.session.flush()
    return ea


def _generate_questions(examen: Examen, ea: ExamenAlumno):
    if ea.preguntas and len(ea.preguntas) > 0:
        return

    if not examen.plantilla_id:
        raise ValueError("El examen no tiene plantilla asignada.")

    plantilla = PlantillaExamen.query.get(examen.plantilla_id)
    if not plantilla:
        raise ValueError("Plantilla no encontrada.")

    n = int(plantilla.num_preguntas or 0)
    if n <= 0:
        raise ValueError("La plantilla debe tener num_preguntas > 0.")

    q = (
        BancoPregunta.query
        .filter_by(academia_id=examen.academia_id, activo=True)
        .filter(BancoPregunta.disciplina == examen.disciplina)
    )

    if hasattr(BancoPregunta, "grado_id") and plantilla.grado_id:
        q = q.filter(BancoPregunta.grado_id == plantilla.grado_id)

    if plantilla.modo_seleccion == "ALEATORIA":
        preguntas = q.order_by(func.rand()).limit(n).all()
    else:
        preguntas = q.order_by(BancoPregunta.id.asc()).limit(n).all()

    if len(preguntas) < n:
        raise ValueError(f"Hay {len(preguntas)} preguntas disponibles, pero la plantilla pide {n}.")

    for idx, p in enumerate(preguntas, start=1):
        db.session.add(ExamenAlumnoPregunta(
            examen_alumno_id=ea.id,
            pregunta_id=p.id,
            evaluador_id=getattr(current_user, "id", None),
            orden=idx,
            puntaje_asignado=0,
        ))


# =========================================================
# Listado
# =========================================================
@examenes_bp.route("/", methods=["GET"])
@login_required
def list_examenes():
    if not _can_manage_exams():
        flash("No tienes permisos para gestionar exámenes.", "danger")
        return redirect(url_for("public.home"))

    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    q = Examen.query.filter_by(academia_id=academia_id).order_by(Examen.fecha.desc(), Examen.id.desc())

    estado = request.args.get("estado")
    if estado:
        q = q.filter(Examen.estado == estado)

    items = q.all()
    return render_template("examenes/list.html", items=items, estado=estado)


# =========================================================
# Crear
# =========================================================
@examenes_bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    if not _can_manage_exams():
        flash("No tienes permisos para gestionar exámenes.", "danger")
        return redirect(url_for("public.home"))

    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    sucursales = Sucursal.query.filter_by(academia_id=academia_id).order_by(Sucursal.nombre.asc()).all()
    grados = Grado.query.filter_by(academia_id=academia_id, activo=True).order_by(Grado.orden.asc()).all()
    plantillas = PlantillaExamen.query.filter_by(academia_id=academia_id, activo=True).order_by(PlantillaExamen.nombre.asc()).all()

    if request.method == "POST":
        disciplina = (request.form.get("disciplina") or "").strip().upper()
        fecha = _parse_date(request.form.get("fecha"))
        hora = _parse_time(request.form.get("hora"))
        sede = (request.form.get("sede") or "").strip() or None

        sucursal_id = request.form.get("sucursal_id", type=int)
        grado_objetivo_id = request.form.get("grado_objetivo_id", type=int)
        plantilla_id = request.form.get("plantilla_id", type=int)

        cupos = request.form.get("cupos", type=int)
        costo = request.form.get("costo", type=float)
        mostrar_resultado = request.form.get("mostrar_resultado_al_alumno") == "1"

        usa_teoria = request.form.get("usa_teoria") == "1"
        usa_poomsae = request.form.get("usa_poomsae") == "1"
        usa_combate = request.form.get("usa_combate") == "1"

        peso_teoria = request.form.get("peso_teoria", type=float)
        peso_poomsae = request.form.get("peso_poomsae", type=float)
        peso_combate = request.form.get("peso_combate", type=float)
        nota_minima_aprobacion = request.form.get("nota_minima_aprobacion", type=float)

        if not disciplina:
            flash("Disciplina es obligatoria.", "danger")
            return render_template("examenes/form.html", item=None, sucursales=sucursales, grados=grados, plantillas=plantillas)

        if not fecha:
            flash("Fecha inválida (usa YYYY-MM-DD).", "danger")
            return render_template("examenes/form.html", item=None, sucursales=sucursales, grados=grados, plantillas=plantillas)

        if not grado_objetivo_id:
            flash("Selecciona el grado objetivo.", "danger")
            return render_template("examenes/form.html", item=None, sucursales=sucursales, grados=grados, plantillas=plantillas)

        if usa_teoria and not plantilla_id:
            flash("Si el examen usa teoría, debes seleccionar una plantilla.", "danger")
            return render_template("examenes/form.html", item=None, sucursales=sucursales, grados=grados, plantillas=plantillas)

        item = Examen(
            academia_id=academia_id,
            sucursal_id=sucursal_id or None,
            disciplina=disciplina,
            fecha=fecha,
            hora=hora,
            sede=sede,
            grado_objetivo_id=grado_objetivo_id,
            plantilla_id=plantilla_id or None,
            cupos=cupos,
            costo=costo if costo is not None else 0.00,
            estado="BORRADOR",
            mostrar_resultado_al_alumno=mostrar_resultado,
            usa_teoria=usa_teoria,
            usa_poomsae=usa_poomsae,
            usa_combate=usa_combate,
            peso_teoria=peso_teoria if peso_teoria is not None else 30.00,
            peso_poomsae=peso_poomsae if peso_poomsae is not None else 40.00,
            peso_combate=peso_combate if peso_combate is not None else 30.00,
            nota_minima_aprobacion=nota_minima_aprobacion if nota_minima_aprobacion is not None else 70.00,
            created_by=getattr(current_user, "id", None),
        )
        db.session.add(item)
        db.session.commit()

        flash("Examen creado en BORRADOR.", "success")
        return redirect(url_for("examenes.editar", examen_id=item.id))

    return render_template("examenes/form.html", item=None, sucursales=sucursales, grados=grados, plantillas=plantillas)

# =========================================================
# Editar
# =========================================================
@examenes_bp.route("/<int:examen_id>/editar", methods=["GET", "POST"])
@login_required
def editar(examen_id: int):
    if not _can_manage_exams():
        flash("No tienes permisos para gestionar exámenes.", "danger")
        return redirect(url_for("public.home"))

    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    item = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()

    sucursales = Sucursal.query.filter_by(academia_id=academia_id).order_by(Sucursal.nombre.asc()).all()
    grados = Grado.query.filter_by(academia_id=academia_id, activo=True).order_by(Grado.orden.asc()).all()
    plantillas = PlantillaExamen.query.filter_by(academia_id=academia_id, activo=True).order_by(PlantillaExamen.nombre.asc()).all()

    if request.method == "POST":
        if item.estado not in ("BORRADOR", "ABIERTO"):
            flash("Este examen ya no se puede editar en este estado.", "warning")
            return redirect(url_for("examenes.editar", examen_id=item.id))

        item.disciplina = (request.form.get("disciplina") or "").strip().upper()
        item.fecha = _parse_date(request.form.get("fecha")) or item.fecha
        item.hora = _parse_time(request.form.get("hora"))
        item.sede = (request.form.get("sede") or "").strip() or None

        item.sucursal_id = request.form.get("sucursal_id", type=int) or None
        item.grado_objetivo_id = request.form.get("grado_objetivo_id", type=int) or item.grado_objetivo_id
        item.plantilla_id = request.form.get("plantilla_id", type=int) or None

        item.cupos = request.form.get("cupos", type=int)
        costo = request.form.get("costo", type=float)
        item.costo = costo if costo is not None else item.costo

        item.mostrar_resultado_al_alumno = (request.form.get("mostrar_resultado_al_alumno") == "1")

        item.usa_teoria = request.form.get("usa_teoria") == "1"
        item.usa_poomsae = request.form.get("usa_poomsae") == "1"
        item.usa_combate = request.form.get("usa_combate") == "1"

        if item.usa_teoria and not item.plantilla_id:
            flash("Si el examen usa teoría, debes seleccionar una plantilla.", "danger")
            return render_template("examenes/form.html", item=item, sucursales=sucursales, grados=grados, plantillas=plantillas)

        peso_teoria = request.form.get("peso_teoria", type=float)
        peso_poomsae = request.form.get("peso_poomsae", type=float)
        peso_combate = request.form.get("peso_combate", type=float)

        if peso_teoria is not None:
            item.peso_teoria = peso_teoria
        if peso_poomsae is not None:
            item.peso_poomsae = peso_poomsae
        if peso_combate is not None:
            item.peso_combate = peso_combate

        nota_minima = request.form.get("nota_minima_aprobacion", type=float)
        if nota_minima is not None:
            item.nota_minima_aprobacion = nota_minima

        db.session.commit()
        flash("Examen actualizado.", "success")
        return redirect(url_for("examenes.editar", examen_id=item.id))

    return render_template("examenes/form.html", item=item, sucursales=sucursales, grados=grados, plantillas=plantillas)

# =========================================================
# Cambiar estado
# =========================================================
@examenes_bp.route("/<int:examen_id>/estado", methods=["POST"])
@login_required
def cambiar_estado(examen_id: int):
    if not _can_manage_exams():
        flash("No tienes permisos para gestionar exámenes.", "danger")
        return redirect(url_for("public.home"))

    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    item = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()
    nuevo = (request.form.get("estado") or "").strip()

    allowed = {"BORRADOR", "ABIERTO", "CERRADO", "EN_EVALUACION", "PENDIENTE_DECISION", "PUBLICADO", "ANULADO"}
    if nuevo not in allowed:
        flash("Estado inválido.", "danger")
        return redirect(url_for("examenes.editar", examen_id=item.id))

    if item.estado == "ANULADO":
        flash("Un examen ANULADO no puede cambiar de estado.", "warning")
        return redirect(url_for("examenes.editar", examen_id=item.id))

    item.estado = nuevo
    db.session.commit()
    flash(f"Estado cambiado a {nuevo}.", "success")
    return redirect(url_for("examenes.editar", examen_id=item.id))


# =========================================================
# Evaluadores
# =========================================================
@examenes_bp.route("/<int:examen_id>/evaluadores", methods=["GET", "POST"])
@login_required
def evaluadores(examen_id: int):
    if not _can_manage_exams():
        flash("No tienes permisos para gestionar exámenes.", "danger")
        return redirect(url_for("public.home"))

    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    examen = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()
    users = User.query.filter_by(academia_id=academia_id).order_by(User.username.asc()).all()

    if request.method == "POST":
        action = request.form.get("action")
        user_id = request.form.get("user_id", type=int)
        rol = (request.form.get("rol") or "AUXILIAR").strip()

        if rol not in ("PRINCIPAL", "AUXILIAR"):
            rol = "AUXILIAR"

        if not user_id:
            flash("Selecciona un evaluador.", "danger")
            return redirect(url_for("examenes.evaluadores", examen_id=examen.id))

        if action == "add":
            exists = ExamenEvaluador.query.filter_by(examen_id=examen.id, user_id=user_id).first()
            if exists:
                flash("Ese usuario ya está asignado como evaluador.", "warning")
            else:
                ee = ExamenEvaluador(
                    academia_id=academia_id,
                    examen_id=examen.id,
                    user_id=user_id,
                    rol=rol,
                )
                db.session.add(ee)
                db.session.commit()
                flash("Evaluador asignado.", "success")

        elif action == "remove":
            ee = ExamenEvaluador.query.filter_by(examen_id=examen.id, user_id=user_id).first()
            if ee:
                db.session.delete(ee)
                db.session.commit()
                flash("Evaluador removido.", "success")
            else:
                flash("No se encontró esa asignación.", "warning")

        return redirect(url_for("examenes.evaluadores", examen_id=examen.id))

    asignados = ExamenEvaluador.query.filter_by(examen_id=examen.id).all()
    asignados_map = {a.user_id: a for a in asignados}

    return render_template(
        "examenes/evaluadores.html",
        examen=examen,
        users=users,
        asignados=asignados,
        asignados_map=asignados_map,
    )


# =========================================================
# Lista de evaluación
# =========================================================
@examenes_bp.route("/<int:examen_id>/evaluacion", methods=["GET"])
@login_required
def evaluacion_list(examen_id: int):
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    examen = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()

    if getattr(current_user, "has_role", None):
        if not (current_user.has_role("ADMIN") or current_user.has_role("SUPERADMIN")):
            ok = ExamenEvaluador.query.filter_by(examen_id=examen.id, user_id=current_user.id).first()
            if not ok:
                flash("No tienes permisos para evaluar este examen.", "danger")
                return redirect(url_for("examenes.editar", examen_id=examen.id))

    inscripciones = (
        ExamenInscripcion.query
        .filter_by(examen_id=examen.id)
        .order_by(ExamenInscripcion.id.asc())
        .all()
    )

    ea_map = {ea.alumno_id: ea for ea in ExamenAlumno.query.filter_by(examen_id=examen.id).all()}

    return render_template(
        "examenes/evaluacion_list.html",
        examen=examen,
        inscripciones=inscripciones,
        ea_map=ea_map,
    )


# =========================================================
# Inscripciones
# =========================================================
@examenes_bp.route("/<int:examen_id>/inscripciones", methods=["GET", "POST"])
@login_required
def inscripciones(examen_id: int):
    if not _can_manage_exams():
        flash("No tienes permisos para gestionar exámenes.", "danger")
        return redirect(url_for("public.home"))

    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    examen = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()

    if request.method == "POST" and examen.estado not in ("BORRADOR", "ABIERTO"):
        flash("No puedes modificar inscripciones en este estado.", "warning")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    action = request.form.get("action")

    if request.method == "POST":
        if action == "add_one":
            alumno_id = request.form.get("alumno_id", type=int)
            if not alumno_id:
                flash("Alumno inválido.", "danger")
                return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

            alumno = Alumno.query.filter_by(id=alumno_id, academia_id=academia_id, activo=True).first()
            if not alumno:
                flash("Alumno no encontrado o inactivo.", "danger")
                return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

            if not alumno.grado_id:
                flash("El alumno no tiene grado actual asignado. Asigna el grado antes de inscribir.", "warning")
                return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

            exists = ExamenInscripcion.query.filter_by(examen_id=examen.id, alumno_id=alumno.id).first()
            if exists:
                flash("Ese alumno ya está inscrito.", "warning")
                return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

            ins = ExamenInscripcion(
                examen_id=examen.id,
                alumno_id=alumno.id,
                grado_actual_id=alumno.grado_id,
                grado_objetivo_id=examen.grado_objetivo_id,
                estado="INSCRITO",
            )
            db.session.add(ins)
            db.session.commit()
            flash("Alumno inscrito.", "success")
            return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

        if action == "add_bulk":
            alumno_ids = request.form.getlist("alumno_ids")
            alumno_ids = [int(x) for x in alumno_ids if str(x).isdigit()]

            if not alumno_ids:
                flash("Selecciona al menos un alumno.", "warning")
                return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

            alumnos = (
                Alumno.query
                .filter(
                    Alumno.academia_id == academia_id,
                    Alumno.activo == True,
                    Alumno.id.in_(alumno_ids),
                )
                .all()
            )

            inscritos = ExamenInscripcion.query.filter_by(examen_id=examen.id).all()
            inscritos_set = {i.alumno_id for i in inscritos}

            added = 0
            skipped_no_grade = 0
            skipped_exists = 0

            for a in alumnos:
                if not a.grado_id:
                    skipped_no_grade += 1
                    continue
                if a.id in inscritos_set:
                    skipped_exists += 1
                    continue

                db.session.add(ExamenInscripcion(
                    examen_id=examen.id,
                    alumno_id=a.id,
                    grado_actual_id=a.grado_id,
                    grado_objetivo_id=examen.grado_objetivo_id,
                    estado="INSCRITO",
                ))
                added += 1

            db.session.commit()

            if added:
                flash(f"Inscritos: {added}", "success")
            if skipped_exists:
                flash(f"Omitidos (ya inscritos): {skipped_exists}", "info")
            if skipped_no_grade:
                flash(f"Omitidos (sin grado actual): {skipped_no_grade}", "warning")

            return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

        if action == "remove":
            insc_id = request.form.get("inscripcion_id", type=int)
            insc = (
                ExamenInscripcion.query
                .join(Examen)
                .filter(
                    ExamenInscripcion.id == insc_id,
                    ExamenInscripcion.examen_id == examen.id,
                    Examen.academia_id == academia_id,
                )
                .first()
            )

            if not insc:
                flash("Inscripción no encontrada.", "warning")
                return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

            db.session.delete(insc)
            db.session.commit()
            flash("Inscripción eliminada.", "success")
            return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

        flash("Acción inválida.", "danger")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    q = (request.args.get("q") or "").strip()

    qa = Alumno.query.filter_by(academia_id=academia_id, activo=True)

    if examen.sucursal_id:
        qa = qa.filter(Alumno.sucursal_id == examen.sucursal_id)

    if q:
        like = f"%{q}%"
        qa = qa.filter(
            (Alumno.apellidos.ilike(like)) |
            (Alumno.nombres.ilike(like)) |
            (Alumno.numero_identidad.ilike(like))
        )

    alumnos = qa.order_by(Alumno.apellidos.asc(), Alumno.nombres.asc()).limit(200).all()

    inscripciones = (
        ExamenInscripcion.query
        .filter_by(examen_id=examen.id)
        .order_by(ExamenInscripcion.id.desc())
        .all()
    )

    grados = Grado.query.filter_by(academia_id=academia_id).all()
    grados_map = {g.id: g for g in grados}

    return render_template(
        "examenes/inscripciones.html",
        examen=examen,
        alumnos=alumnos,
        inscripciones=inscripciones,
        grados_map=grados_map,
        q=q,
    )


# =========================================================
# Iniciar evaluación
# =========================================================
@examenes_bp.route("/<int:examen_id>/iniciar-evaluacion", methods=["POST"])
@login_required
def iniciar_evaluacion(examen_id: int):
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    examen = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()

    if not examen.plantilla_id:
        flash("Este examen no tiene plantilla asignada. Asigna una plantilla antes de iniciar evaluación.", "danger")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    plantilla = PlantillaExamen.query.filter_by(
        id=examen.plantilla_id,
        academia_id=academia_id,
        activo=True,
    ).first()

    if not plantilla:
        flash("Plantilla inválida o inactiva.", "danger")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    inscritos = ExamenInscripcion.query.filter_by(examen_id=examen.id).all()
    if not inscritos:
        flash("No hay inscritos.", "warning")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    base_q = (
        BancoPregunta.query
        .filter_by(
            academia_id=academia_id,
            grado_id=plantilla.grado_id,
            activo=True,
        )
        .filter(BancoPregunta.disciplina == examen.disciplina)
    )
    

    total_banco = base_q.count()
    if total_banco == 0:
        flash("No hay preguntas en el banco para la disciplina y grado de la plantilla.", "danger")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    n = int(plantilla.num_preguntas or 0)
    if n <= 0:
        flash("La plantilla no tiene num_preguntas válido.", "danger")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    if n > total_banco:
        flash(f"La plantilla pide {n} preguntas pero el banco solo tiene {total_banco}.", "danger")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    creados = 0

    for ins in inscritos:
        ea = ExamenAlumno.query.filter_by(examen_id=examen.id, alumno_id=ins.alumno_id).first()
        if not ea:
            ea = ExamenAlumno(
                examen_id=examen.id,
                alumno_id=ins.alumno_id,
                estado="PENDIENTE",
            )
            db.session.add(ea)
            db.session.flush()

        if ea.preguntas and len(ea.preguntas) > 0:
            continue

        if plantilla.modo_seleccion == "ALEATORIA":
            preguntas = base_q.order_by(func.rand()).limit(n).all()
        else:
            preguntas = base_q.order_by(BancoPregunta.id.asc()).limit(n).all()

        orden = 1
        for p in preguntas:
            db.session.add(ExamenAlumnoPregunta(
                examen_alumno_id=ea.id,
                pregunta_id=p.id,
                orden=orden,
            ))
            orden += 1

        creados += 1

    if examen.estado in ("BORRADOR", "ABIERTO"):
        examen.estado = "EN_EVALUACION"

    db.session.commit()
    flash(f"Evaluación iniciada. Se generaron preguntas para {creados} alumnos.", "success")
    return redirect(url_for("examenes.inscripciones", examen_id=examen.id))


# =========================================================
# Compatibilidad ruta antigua
# =========================================================
@examenes_bp.route("/<int:examen_id>/evaluacion/<int:inscripcion_id>", methods=["GET", "POST"])
@login_required
def evaluar_alumno_preguntas(examen_id: int, inscripcion_id: int):
    return redirect(url_for("examenes.evaluar_alumno", examen_id=examen_id, inscripcion_id=inscripcion_id))


# =========================================================
# Evaluar alumno
# =========================================================
@examenes_bp.route("/<int:examen_id>/evaluar/<int:inscripcion_id>", methods=["GET", "POST"])
@login_required
def evaluar_alumno(examen_id: int, inscripcion_id: int):
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    examen = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()
    ins = ExamenInscripcion.query.filter_by(id=inscripcion_id, examen_id=examen.id).first_or_404()

    ea = ExamenAlumno.query.filter_by(examen_id=examen.id, alumno_id=ins.alumno_id).first()
    if not ea:
        flash("Primero debes iniciar evaluación.", "warning")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    alumno = Alumno.query.filter_by(
        id=ins.alumno_id,
        academia_id=academia_id,
        activo=True,
    ).first()

    if not alumno:
        flash("Alumno no encontrado o inactivo.", "danger")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    preguntas = (
        ExamenAlumnoPregunta.query
        .filter_by(examen_alumno_id=ea.id)
        .order_by(ExamenAlumnoPregunta.orden.asc())
        .all()
    )

    preguntas_full = []
    for eap in preguntas:
        p = BancoPregunta.query.get(eap.pregunta_id)
        opciones = []

        if p and p.tipo in ("OPCION_MULTIPLE", "VERDADERO_FALSO"):
            opciones = (
                PreguntaOpcion.query
                .filter_by(pregunta_id=p.id)
                .order_by(PreguntaOpcion.orden.asc())
                .all()
            )

        if p:
            preguntas_full.append((eap, p, opciones))

    if request.method == "POST":
        total_teoria = 0.0

        for eap, p, opciones in preguntas_full:
            key = f"preg_{eap.id}"

            if p.tipo in ("OPCION_MULTIPLE", "VERDADERO_FALSO"):
                opcion_id = request.form.get(key, type=int)
                eap.respuesta_opcion_id = opcion_id
                eap.respuesta_texto = None
                eap.evaluador_id = getattr(current_user, "id", None)

                if opcion_id:
                    op = PreguntaOpcion.query.get(opcion_id)
                    if op and op.es_correcta:
                        eap.es_correcta = True
                        eap.puntaje_asignado = float(p.puntaje_max or 0)
                    else:
                        eap.es_correcta = False
                        eap.puntaje_asignado = 0
                else:
                    eap.es_correcta = False
                    eap.puntaje_asignado = 0

            else:
                texto = (request.form.get(key) or "").strip()
                eap.respuesta_texto = texto
                eap.respuesta_opcion_id = None
                eap.evaluador_id = getattr(current_user, "id", None)

                puntaje_manual = request.form.get(f"punt_{eap.id}", type=float)
                eap.puntaje_asignado = puntaje_manual if puntaje_manual is not None else 0

            total_teoria += float(eap.puntaje_asignado or 0)

        nota_poomsae = request.form.get("nota_poomsae", type=float)
        nota_combate = request.form.get("nota_combate", type=float)
        observacion = (request.form.get("observacion") or "").strip() or None

        if examen.usa_poomsae:
            if nota_poomsae is None:
                flash("Debes ingresar la nota de poomsae.", "danger")
                return render_template(
                    "examenes/evaluar_alumno.html",
                    examen=examen,
                    ins=ins,
                    ea=ea,
                    alumno=alumno,
                    preguntas_full=preguntas_full,
                )
            ins.nota_poomsae = round(float(nota_poomsae), 2)
        else:
            ins.nota_poomsae = 0

        if examen.usa_combate:
            if nota_combate is None:
                flash("Debes ingresar la nota de combate.", "danger")
                return render_template(
                    "examenes/evaluar_alumno.html",
                    examen=examen,
                    ins=ins,
                    ea=ea,
                    alumno=alumno,
                    preguntas_full=preguntas_full,
                )
            ins.nota_combate = round(float(nota_combate), 2)
        else:
            ins.nota_combate = 0

        ins.nota_teoria = round(float(total_teoria), 2) if examen.usa_teoria else 0
        ins.comentario_general = observacion
        ins.updated_at = datetime.utcnow()

        ea.score_auto = total_teoria
        ea.score_total = total_teoria
        ea.estado = "FINALIZADO"
        ea.finished_at = datetime.utcnow()

        _recalcular_nota_final(examen, ins)

        ins.estado = "EVALUADO"

        db.session.commit()
        flash("Evaluación guardada correctamente.", "success")

        accion = (request.form.get("accion") or "").strip()

        if accion == "guardar_siguiente":
            siguiente = (
                ExamenInscripcion.query
                .filter(
                    ExamenInscripcion.examen_id == examen.id,
                    ExamenInscripcion.id > ins.id,
                )
                .order_by(ExamenInscripcion.id.asc())
                .first()
            )
            if siguiente:
                return redirect(url_for("examenes.evaluar_alumno", examen_id=examen.id, inscripcion_id=siguiente.id))

            return redirect(url_for("examenes.resultados", examen_id=examen.id))

        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    return render_template(
        "examenes/evaluar_alumno.html",
        examen=examen,
        ins=ins,
        ea=ea,
        alumno=alumno,
        preguntas_full=preguntas_full,
    )


# =========================================================
# Dictaminar
# =========================================================
@examenes_bp.route("/<int:examen_id>/dictaminar/<int:inscripcion_id>", methods=["POST"])
@login_required
def dictaminar_alumno(examen_id: int, inscripcion_id: int):
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    examen = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()
    ins = ExamenInscripcion.query.filter_by(id=inscripcion_id, examen_id=examen.id).first_or_404()

    alumno = Alumno.query.filter_by(id=ins.alumno_id, academia_id=academia_id).first()
    if not alumno:
        flash("Alumno no encontrado.", "danger")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    resultado_final = (request.form.get("resultado_final") or "").strip().upper()
    observacion_final = (request.form.get("observacion_final") or "").strip() or None
    nota_final = float(ins.nota_final or 0)

    if resultado_final not in ("APROBADO", "REPROBADO"):
        flash("Resultado final inválido.", "danger")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    dictamen = ExamenDictamen.query.filter_by(examen_id=examen.id, alumno_id=alumno.id).first()
    if not dictamen:
        dictamen = ExamenDictamen(
            examen_id=examen.id,
            alumno_id=alumno.id,
            director_user_id=current_user.id,
            resultado_final=resultado_final,
            nota_final=nota_final,
            observacion_final=observacion_final,
        )
        db.session.add(dictamen)
    else:
        dictamen.director_user_id = current_user.id
        dictamen.resultado_final = resultado_final
        dictamen.nota_final = nota_final
        dictamen.observacion_final = observacion_final

    if resultado_final == "APROBADO":
        ins.estado = "APROBADO"
    else:
        ins.estado = "REPROBADO"

    db.session.flush()

    if resultado_final == "APROBADO":
        asc = Ascenso.query.filter_by(examen_id=examen.id, alumno_id=alumno.id).first()

        if not asc:
            asc = Ascenso(
                academia_id=academia_id,
                alumno_id=alumno.id,
                fecha=examen.fecha or date.today(),
                grado_anterior_id=ins.grado_actual_id,
                grado_nuevo_id=ins.grado_objetivo_id,
                origen="EXAMEN",
                examen_id=examen.id,
                observacion="Ascenso generado automáticamente desde examen.",
                created_by=current_user.id,
            )
            db.session.add(asc)

        alumno.grado_id = ins.grado_objetivo_id
        alumno.fecha_ultimo_grado = examen.fecha or date.today()
        ins.estado = "PROMOVIDO"

    db.session.commit()
    flash(f"Dictamen guardado: {resultado_final}.", "success")
    return redirect(url_for("examenes.inscripciones", examen_id=examen.id))


# =========================================================
# Cerrar examen
# =========================================================
@examenes_bp.route("/<int:examen_id>/cerrar", methods=["POST"])
@login_required
def cerrar_examen(examen_id: int):
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    examen = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()

    inscripciones = ExamenInscripcion.query.filter_by(examen_id=examen.id).all()
    if not inscripciones:
        flash("No hay inscritos en el examen.", "warning")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    pendientes = [i for i in inscripciones if i.estado not in ("PROMOVIDO", "REPROBADO", "APROBADO")]
    if pendientes:
        flash("No puedes cerrar el examen porque aún hay alumnos sin dictamen final.", "warning")
        return redirect(url_for("examenes.inscripciones", examen_id=examen.id))

    examen.estado = "PUBLICADO"
    db.session.commit()

    flash("Examen cerrado y publicado correctamente.", "success")
    return redirect(url_for("examenes.list_examenes"))


# =========================================================
# Acta PDF
# =========================================================
@examenes_bp.route("/<int:examen_id>/acta.pdf", methods=["GET"])
@login_required
def acta_pdf(examen_id: int):
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    examen = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()

    grados = Grado.query.filter_by(academia_id=academia_id).all()
    grados_map = {g.id: g for g in grados}

    alumnos_ids = [i.alumno_id for i in ExamenInscripcion.query.filter_by(examen_id=examen.id).all()]
    alumnos = Alumno.query.filter(Alumno.id.in_(alumnos_ids)).all() if alumnos_ids else []
    alumnos_map = {a.id: a for a in alumnos}

    evaluadores = ExamenEvaluador.query.filter_by(examen_id=examen.id).all()
    users_ids = [e.user_id for e in evaluadores]
    users = User.query.filter(User.id.in_(users_ids)).all() if users_ids else []
    users_map = {u.id: u for u in users}

    inscripciones = (
        ExamenInscripcion.query
        .filter_by(examen_id=examen.id)
        .order_by(ExamenInscripcion.id.asc())
        .all()
    )

    total_inscritos = len(inscripciones)
    total_promovidos = sum(1 for i in inscripciones if i.estado == "PROMOVIDO")
    total_reprobados = sum(1 for i in inscripciones if i.estado == "REPROBADO")
    total_evaluados = sum(1 for i in inscripciones if i.estado in ("EVALUADO", "PROMOVIDO", "REPROBADO"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.6 * cm,
        leftMargin=1.6 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=f"Acta Examen {examen.id}",
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="TituloActa",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1f2937"),
        spaceAfter=10,
    ))
    styles.add(ParagraphStyle(
        name="SubActa",
        parent=styles["Normal"],
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#4b5563"),
    ))
    styles.add(ParagraphStyle(
        name="SeccionActa",
        parent=styles["Heading2"],
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#111827"),
        spaceBefore=8,
        spaceAfter=6,
    ))

    story = []

    story.append(Paragraph("ACTA DE EXAMEN DE ASCENSO", styles["TituloActa"]))
    story.append(Paragraph(f"Examen #{examen.id} - {examen.disciplina} - Fecha: {examen.fecha}", styles["SubActa"]))
    story.append(Paragraph(f"Estado del examen: {examen.estado}", styles["SubActa"]))
    story.append(Spacer(1, 0.35 * cm))

    story.append(Paragraph("Datos generales", styles["SeccionActa"]))

    datos_generales = [
        ["Campo", "Valor"],
        ["Disciplina", examen.disciplina or "-"],
        ["Fecha", str(examen.fecha or "-")],
        ["Hora", str(examen.hora or "-") if examen.hora else "-"],
        ["Sede", examen.sede or "-"],
        ["Sucursal ID", str(examen.sucursal_id or "-")],
        ["Grado objetivo", grados_map.get(examen.grado_objetivo_id).nombre if grados_map.get(examen.grado_objetivo_id) else str(examen.grado_objetivo_id or "-")],
        ["Plantilla ID", str(examen.plantilla_id or "-")],
    ]

    t_general = Table(datos_generales, colWidths=[4.5 * cm, 11.5 * cm])
    t_general.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_general)
    story.append(Spacer(1, 0.35 * cm))

    story.append(Paragraph("Evaluadores asignados", styles["SeccionActa"]))

    eval_rows = [["Usuario", "Email", "Rol"]]
    if evaluadores:
        for e in evaluadores:
            u = users_map.get(e.user_id)
            eval_rows.append([
                u.username if u else f"#{e.user_id}",
                u.email if u else "-",
                e.rol,
            ])
    else:
        eval_rows.append(["-", "-", "Sin evaluadores"])

    t_eval = Table(eval_rows, colWidths=[5 * cm, 7 * cm, 4 * cm])
    t_eval.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_eval)
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Resultados de alumnos", styles["SeccionActa"]))

    rows = [[
        "Alumno",
        "Identidad",
        "Grado actual",
        "Grado objetivo",
        "Estado",
        "Nota",
    ]]

    for i in inscripciones:
        a = alumnos_map.get(i.alumno_id)
        nombre_alumno = f"{a.apellidos} {a.nombres}" if a else f"#{i.alumno_id}"
        identidad = a.numero_identidad if a and a.numero_identidad else "-"
        grado_actual = grados_map.get(i.grado_actual_id).nombre if grados_map.get(i.grado_actual_id) else str(i.grado_actual_id or "-")
        grado_obj = grados_map.get(i.grado_objetivo_id).nombre if grados_map.get(i.grado_objetivo_id) else str(i.grado_objetivo_id or "-")
        nota = float(i.nota_final or 0)

        rows.append([
            Paragraph(nombre_alumno, styles["BodyText"]),
            identidad,
            Paragraph(grado_actual, styles["BodyText"]),
            Paragraph(grado_obj, styles["BodyText"]),
            i.estado,
            f"{nota:.2f}",
        ])

    t_result = Table(
        rows,
        colWidths=[4.5 * cm, 2.7 * cm, 3.0 * cm, 3.0 * cm, 2.2 * cm, 1.8 * cm],
        repeatRows=1,
    )
    t_result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("ALIGN", (4, 1), (5, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_result)
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Resumen final", styles["SeccionActa"]))

    resumen_rows = [
        ["Indicador", "Valor"],
        ["Total inscritos", str(total_inscritos)],
        ["Evaluados", str(total_evaluados)],
        ["Promovidos", str(total_promovidos)],
        ["Reprobados", str(total_reprobados)],
    ]

    t_resumen = Table(resumen_rows, colWidths=[5 * cm, 3 * cm])
    t_resumen.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d1d5db")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t_resumen)
    story.append(Spacer(1, 0.7 * cm))

    story.append(Paragraph("Firma responsable: ________________________________", styles["Normal"]))
    story.append(Spacer(1, 0.25 * cm))
    story.append(Paragraph("Documento generado automáticamente por DojoManager.", styles["SubActa"]))

    doc.build(story)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=False,
        download_name=f"acta_examen_{examen.id}.pdf",
        mimetype="application/pdf",
    )


# =========================================================
# Resultados
# =========================================================
@examenes_bp.route("/<int:examen_id>/resultados", methods=["GET"])
@login_required
def resultados(examen_id: int):
    academia_id = _academia_id_or_403()
    if not academia_id:
        return redirect(url_for("public.home"))

    examen = Examen.query.filter_by(id=examen_id, academia_id=academia_id).first_or_404()

    inscripciones = (
        ExamenInscripcion.query
        .filter_by(examen_id=examen.id)
        .order_by(ExamenInscripcion.id.asc())
        .all()
    )

    grados = Grado.query.filter_by(academia_id=academia_id).all()
    grados_map = {g.id: g for g in grados}

    alumnos_ids = [i.alumno_id for i in inscripciones]
    alumnos = Alumno.query.filter(Alumno.id.in_(alumnos_ids)).all() if alumnos_ids else []
    alumnos_map = {a.id: a for a in alumnos}

    return render_template(
        "examenes/resultados.html",
        examen=examen,
        inscripciones=inscripciones,
        grados_map=grados_map,
        alumnos_map=alumnos_map,
    )