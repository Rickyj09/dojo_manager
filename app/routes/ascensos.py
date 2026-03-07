from datetime import date
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models.ascenso import Ascenso
from app.models.alumno import Alumno
from app.models.grado import Grado
from app.models.examenes import Examen
from app.forms.ascensos import AscensoForm


ascensos_bp = Blueprint("ascensos", __name__, url_prefix="/ascensos")


def _tenant_id():
    return getattr(current_user, "academia_id", None)


def _require_tenant():
    if not getattr(current_user, "is_authenticated", False) or not _tenant_id():
        flash("No hay academia seleccionada para este usuario.", "warning")
        return False
    return True


def _load_choices(form: AscensoForm):
    tid = _tenant_id()

    alumnos = (
        Alumno.query
        .filter_by(academia_id=tid, activo=True)
        .order_by(Alumno.apellidos.asc(), Alumno.nombres.asc())
        .all()
    )
    form.alumno_id.choices = [(a.id, f"{a.apellidos} {a.nombres}") for a in alumnos]

    grados = (
        Grado.query
        .filter_by(academia_id=tid, activo=True)
        .order_by(Grado.orden.asc())
        .all()
    )
    form.grado_anterior_id.choices = [(g.id, g.nombre) for g in grados]
    form.grado_nuevo_id.choices = [(g.id, g.nombre) for g in grados]

    examenes = (
        Examen.query
        .filter_by(academia_id=tid)
        .order_by(Examen.fecha.desc())
        .limit(200)
        .all()
    )
    form.examen_id.choices = [(0, "— Ninguno —")] + [
        (e.id, f"{e.disciplina} | {e.fecha} | #{e.id}") for e in examenes
    ]


def _sync_alumno_grado(alumno: Alumno, grado_nuevo_id: int, fecha_: date):
    alumno.grado_id = grado_nuevo_id
    alumno.fecha_ultimo_grado = fecha_

@ascensos_bp.route("/", methods=["GET"])
@login_required
def list():
    if not _require_tenant():
        return redirect(url_for("public.home"))

    tid = _tenant_id()

    q = Ascenso.query.filter_by(academia_id=tid)

    alumno_txt = (request.args.get("alumno") or "").strip()
    origen = (request.args.get("origen") or "").strip()
    desde = (request.args.get("desde") or "").strip()
    hasta = (request.args.get("hasta") or "").strip()

    if origen:
        q = q.filter(Ascenso.origen == origen)

    if desde:
        q = q.filter(Ascenso.fecha >= desde)

    if hasta:
        q = q.filter(Ascenso.fecha <= hasta)

    ascensos = q.order_by(Ascenso.fecha.desc(), Ascenso.id.desc()).all()

    alumnos_map = {a.id: a for a in Alumno.query.filter_by(academia_id=tid).all()}
    grados_map = {g.id: g for g in Grado.query.filter_by(academia_id=tid).all()}

    if alumno_txt:
        alumno_txt_low = alumno_txt.lower()
        ascensos = [
            x for x in ascensos
            if x.alumno_id in alumnos_map and
               alumno_txt_low in f"{alumnos_map[x.alumno_id].apellidos} {alumnos_map[x.alumno_id].nombres}".lower()
        ]

    return render_template(
        "ascensos/list.html",
        ascensos=ascensos,
        alumnos_map=alumnos_map,
        grados_map=grados_map,
        filtros={
            "alumno": alumno_txt,
            "origen": origen,
            "desde": desde,
            "hasta": hasta,
        },
    )


@ascensos_bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    if not _require_tenant():
        return redirect(url_for("public.home"))

    form = AscensoForm()
    _load_choices(form)

    if request.method == "GET":
        form.fecha.data = date.today()

    if form.validate_on_submit():
        tid = _tenant_id()

        alumno = Alumno.query.filter_by(id=form.alumno_id.data, academia_id=tid).first()
        if not alumno:
            flash("Alumno inválido.", "danger")
            return redirect(url_for("ascensos.nuevo"))

        if form.grado_anterior_id.data == form.grado_nuevo_id.data:
            flash("El grado anterior y nuevo no pueden ser iguales.", "warning")
            return render_template("ascensos/form.html", form=form, modo="nuevo")

        examen_id = form.examen_id.data or 0
        examen_id = None if examen_id == 0 else examen_id

        if form.origen.data == "EXAMEN" and not examen_id:
            flash("Si el origen es EXAMEN, selecciona un examen.", "warning")
            return render_template("ascensos/form.html", form=form, modo="nuevo")

        asc = Ascenso(
            academia_id=tid,
            alumno_id=alumno.id,
            fecha=form.fecha.data,
            grado_anterior_id=form.grado_anterior_id.data,
            grado_nuevo_id=form.grado_nuevo_id.data,
            origen=form.origen.data,
            examen_id=examen_id,
            observacion=(form.observacion.data or "").strip() or None,
            created_by=current_user.id,
        )

        _sync_alumno_grado(alumno, asc.grado_nuevo_id, asc.fecha)

        db.session.add(asc)
        db.session.commit()

        flash("Ascenso registrado y alumno actualizado.", "success")
        return redirect(url_for("ascensos.list"))

    return render_template("ascensos/form.html", form=form, modo="nuevo")


@ascensos_bp.route("/<int:ascenso_id>/editar", methods=["GET", "POST"])
@login_required
def editar(ascenso_id: int):
    if not _require_tenant():
        return redirect(url_for("public.home"))

    tid = _tenant_id()

    asc = Ascenso.query.filter_by(id=ascenso_id, academia_id=tid).first_or_404()
    form = AscensoForm()
    _load_choices(form)

    alumno = Alumno.query.filter_by(id=asc.alumno_id, academia_id=tid).first()
    if not alumno:
        flash("Alumno no encontrado.", "danger")
        return redirect(url_for("ascensos.list"))

    if request.method == "GET":
        form.alumno_id.data = asc.alumno_id
        form.fecha.data = asc.fecha
        form.grado_anterior_id.data = asc.grado_anterior_id
        form.grado_nuevo_id.data = asc.grado_nuevo_id
        form.origen.data = asc.origen
        form.examen_id.data = asc.examen_id if asc.examen_id else 0
        form.observacion.data = asc.observacion

    if form.validate_on_submit():
        if form.grado_anterior_id.data == form.grado_nuevo_id.data:
            flash("El grado anterior y nuevo no pueden ser iguales.", "warning")
            return render_template("ascensos/form.html", form=form, modo="editar", ascenso=asc)

        examen_id = form.examen_id.data or 0
        examen_id = None if examen_id == 0 else examen_id

        if form.origen.data == "EXAMEN" and not examen_id:
            flash("Si el origen es EXAMEN, selecciona un examen.", "warning")
            return render_template("ascensos/form.html", form=form, modo="editar", ascenso=asc)

        asc.alumno_id = form.alumno_id.data
        asc.fecha = form.fecha.data
        asc.grado_anterior_id = form.grado_anterior_id.data
        asc.grado_nuevo_id = form.grado_nuevo_id.data
        asc.origen = form.origen.data
        asc.examen_id = examen_id
        asc.observacion = (form.observacion.data or "").strip() or None

        alumno = Alumno.query.filter_by(id=asc.alumno_id, academia_id=tid).first()
        if alumno:
            _sync_alumno_grado(alumno, asc.grado_nuevo_id, asc.fecha)

        db.session.commit()
        flash("Ascenso actualizado correctamente.", "success")
        return redirect(url_for("ascensos.list"))

    return render_template("ascensos/form.html", form=form, modo="editar", ascenso=asc)


@ascensos_bp.route("/<int:ascenso_id>/eliminar", methods=["POST"])
@login_required
def eliminar(ascenso_id: int):
    if not _require_tenant():
        return redirect(url_for("public.home"))

    tid = _tenant_id()
    asc = Ascenso.query.filter_by(id=ascenso_id, academia_id=tid).first_or_404()

    db.session.delete(asc)
    db.session.commit()

    flash("Ascenso eliminado correctamente.", "success")
    return redirect(url_for("ascensos.list"))