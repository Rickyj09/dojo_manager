import os
from datetime import date, datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, current_app
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy import or_

from app.extensions import db
from app.tenancy import tenant_query

from app.models.alumno import Alumno
from app.models.categoria import Categoria
from app.models.sucursal import Sucursal
from app.models.grado import Grado
from app.models.participacion import Participacion
from app.models.torneo import Torneo
from app.models.medalla import Medalla
from app.models.asistencia import Asistencia

from app.utils.auditoria import registrar_auditoria


alumnos_bp = Blueprint("alumnos", __name__, url_prefix="/alumnos")


def _parse_fecha(fecha_str):
    if not fecha_str:
        return None
    try:
        return datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except ValueError:
        return None


# =========================
# LISTADO DE ALUMNOS + BUSCADOR
# =========================
@alumnos_bp.route("/", methods=["GET"])
@login_required
def index():
    q = (request.args.get("q") or "").strip()

    query = tenant_query(Alumno)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Alumno.apellidos.like(like),
                Alumno.numero_identidad.like(like),
            )
        )

    alumnos = query.order_by(Alumno.apellidos.asc(), Alumno.nombres.asc()).all()
    return render_template("alumnos/index.html", alumnos=alumnos, q=q)


# =========================
# NUEVO ALUMNO
# =========================
@alumnos_bp.route("/nuevo", methods=["GET", "POST"])
@login_required
def nuevo():
    categorias = tenant_query(Categoria).order_by(Categoria.nombre).all()

    if current_user.has_role("ADMIN"):
        sucursales = tenant_query(Sucursal).filter_by(activo=True).order_by(Sucursal.nombre).all()
    elif current_user.has_role("PROFESOR"):
        sucursales = tenant_query(Sucursal).filter_by(
            id=current_user.sucursal_id,
            activo=True
        ).all()
    else:
        flash("No tiene permisos para crear alumnos", "danger")
        return redirect(url_for("alumnos.index"))

    grados = tenant_query(Grado).filter_by(activo=True).order_by(Grado.orden).all()

    if request.method == "POST":
        nombres = (request.form.get("nombres") or "").strip()
        apellidos = (request.form.get("apellidos") or "").strip()
        categoria_id = request.form.get("categoria_id", type=int)
        fecha_nacimiento_str = (request.form.get("fecha_nacimiento") or "").strip()
        genero = (request.form.get("genero") or "").strip()
        numero_identidad = (request.form.get("numero_identidad") or "").strip() or None
        grado_id = request.form.get("grado_id", type=int)
        peso = request.form.get("peso", type=float)
        flexibilidad = (request.form.get("flexibilidad") or "").strip() or None

        if current_user.has_role("ADMIN"):
            sucursal_id = request.form.get("sucursal_id", type=int)
        else:
            sucursal_id = current_user.sucursal_id

        errores = []

        if not nombres:
            errores.append("El campo Nombres es obligatorio.")
        if not apellidos:
            errores.append("El campo Apellidos es obligatorio.")
        if not categoria_id:
            errores.append("Debe seleccionar una categoría.")
        if not fecha_nacimiento_str:
            errores.append("La fecha de nacimiento es obligatoria.")
        if not genero:
            errores.append("El género es obligatorio.")
        if not grado_id:
            errores.append("Debe seleccionar un grado.")
        if not sucursal_id:
            errores.append("Debe seleccionar una sucursal.")

        fecha_nacimiento = _parse_fecha(fecha_nacimiento_str)
        if fecha_nacimiento_str and not fecha_nacimiento:
            errores.append("La fecha de nacimiento no tiene un formato válido.")

        cat = None
        if categoria_id:
            cat = tenant_query(Categoria).filter_by(id=categoria_id).first()
            if not cat:
                errores.append("Categoría inválida para esta academia.")

        suc = None
        if sucursal_id:
            suc = tenant_query(Sucursal).filter_by(id=sucursal_id, activo=True).first()
            if not suc:
                errores.append("Sucursal inválida para esta academia.")

        grado = None
        if grado_id:
            grado = tenant_query(Grado).filter_by(id=grado_id, activo=True).first()
            if not grado:
                errores.append("Grado inválido para esta academia.")

        if errores:
            for e in errores:
                flash(e, "danger")
            return render_template(
                "alumnos/nuevo.html",
                categorias=categorias,
                sucursales=sucursales,
                grados=grados
            )

        alumno = Alumno(
            nombres=nombres,
            apellidos=apellidos,
            fecha_nacimiento=fecha_nacimiento,
            genero=genero,
            categoria_id=categoria_id,
            sucursal_id=sucursal_id,
            numero_identidad=numero_identidad,
            grado_id=grado_id,
            peso=peso,
            flexibilidad=flexibilidad,
            activo=True,
            academia_id=current_user.academia_id
        )

        db.session.add(alumno)
        db.session.commit()

        registrar_auditoria(
            accion="CREATE",
            entidad="ALUMNO",
            entidad_id=alumno.id,
            descripcion="Creación de alumno",
            datos_despues={
                "nombres": alumno.nombres,
                "apellidos": alumno.apellidos,
                "fecha_nacimiento": str(alumno.fecha_nacimiento) if alumno.fecha_nacimiento else None,
                "genero": alumno.genero,
                "categoria_id": alumno.categoria_id,
                "sucursal_id": alumno.sucursal_id,
                "grado_id": alumno.grado_id,
                "peso": alumno.peso,
                "flexibilidad": alumno.flexibilidad,
            }
        )

        archivo = request.files.get("foto")
        if archivo and archivo.filename:
            nombre_archivo = secure_filename(archivo.filename)
            ruta = os.path.join(current_app.config["UPLOAD_FOLDER"], nombre_archivo)
            archivo.save(ruta)
            alumno.foto = nombre_archivo
            db.session.commit()

        flash("Alumno creado correctamente", "success")
        return redirect(url_for("alumnos.index"))

    return render_template(
        "alumnos/nuevo.html",
        categorias=categorias,
        sucursales=sucursales,
        grados=grados
    )


# =========================
# EDITAR ALUMNO
# =========================
@alumnos_bp.route("/<int:id>/editar", methods=["GET", "POST"])
@login_required
def editar(id):
    alumno = tenant_query(Alumno).filter_by(id=id).first_or_404()

    if current_user.has_role("PROFESOR") and alumno.sucursal_id != current_user.sucursal_id:
        flash("No tiene permisos para editar este alumno", "danger")
        return redirect(url_for("alumnos.index"))

    grados = tenant_query(Grado).filter_by(activo=True).order_by(Grado.orden).all()

    participaciones = (
        db.session.query(Participacion)
        .join(Torneo, Torneo.id == Participacion.torneo_id)
        .outerjoin(Medalla, Medalla.id == Participacion.medalla_id)
        .filter(
            Participacion.alumno_id == alumno.id,
            Participacion.academia_id == current_user.academia_id
        )
        .order_by(Torneo.fecha.desc())
        .all()
    )

    hoy = date.today()

    asistencia_hoy = Asistencia.query.filter_by(
        alumno_id=alumno.id,
        sucursal_id=alumno.sucursal_id,
        fecha=hoy,
        academia_id=current_user.academia_id
    ).first()

    historial_asistencias = (
        Asistencia.query
        .join(Sucursal, Sucursal.id == Asistencia.sucursal_id)
        .filter(
            Asistencia.alumno_id == alumno.id,
            Asistencia.sucursal_id == alumno.sucursal_id,
            Asistencia.academia_id == current_user.academia_id
        )
        .order_by(Asistencia.fecha.desc())
        .limit(10)
        .all()
    )

    if request.method == "POST":
        datos_antes = {
            "nombres": alumno.nombres,
            "apellidos": alumno.apellidos,
            "fecha_nacimiento": str(alumno.fecha_nacimiento) if alumno.fecha_nacimiento else None,
            "genero": alumno.genero,
            "numero_identidad": alumno.numero_identidad,
            "peso": alumno.peso,
            "flexibilidad": alumno.flexibilidad,
            "grado_id": alumno.grado_id,
            "foto": alumno.foto
        }

        nombres = (request.form.get("nombres") or "").strip()
        apellidos = (request.form.get("apellidos") or "").strip()
        fecha_nacimiento_str = (request.form.get("fecha_nacimiento") or "").strip()
        genero = (request.form.get("genero") or "").strip()
        numero_identidad = (request.form.get("numero_identidad") or "").strip() or None
        peso = request.form.get("peso", type=float)
        flexibilidad = (request.form.get("flexibilidad") or "").strip() or None
        grado_id = request.form.get("grado_id", type=int)

        errores = []

        if not nombres:
            errores.append("El campo Nombres es obligatorio.")
        if not apellidos:
            errores.append("El campo Apellidos es obligatorio.")
        if not fecha_nacimiento_str:
            errores.append("La fecha de nacimiento es obligatoria.")
        if not genero:
            errores.append("El género es obligatorio.")
        if not grado_id:
            errores.append("Debe seleccionar un grado.")
        if alumno.sucursal_id is None:
            errores.append("El alumno debe tener una sucursal asignada.")

        fecha_nacimiento = _parse_fecha(fecha_nacimiento_str)
        if fecha_nacimiento_str and not fecha_nacimiento:
            errores.append("La fecha de nacimiento no tiene un formato válido.")

        grado = None
        if grado_id:
            grado = tenant_query(Grado).filter_by(id=grado_id, activo=True).first()
            if not grado:
                errores.append("El grado seleccionado no es válido para esta academia.")

        if errores:
            for e in errores:
                flash(e, "danger")
            return render_template(
                "alumnos/editar.html",
                alumno=alumno,
                grados=grados,
                participaciones=participaciones,
                fecha_asistencia=hoy.isoformat(),
                asistencia=asistencia_hoy,
                historial_asistencias=historial_asistencias
            )

        alumno.nombres = nombres
        alumno.apellidos = apellidos
        alumno.fecha_nacimiento = fecha_nacimiento
        alumno.genero = genero
        alumno.numero_identidad = numero_identidad
        alumno.peso = peso
        alumno.flexibilidad = flexibilidad
        alumno.grado_id = grado_id

        archivo = request.files.get("foto")
        if archivo and archivo.filename:
            nombre_archivo = secure_filename(archivo.filename)
            ruta = os.path.join(current_app.config["UPLOAD_FOLDER"], nombre_archivo)
            archivo.save(ruta)
            alumno.foto = nombre_archivo

        db.session.commit()

        registrar_auditoria(
            accion="UPDATE",
            entidad="ALUMNO",
            entidad_id=alumno.id,
            descripcion="Edición de alumno",
            datos_antes=datos_antes,
            datos_despues={
                "nombres": alumno.nombres,
                "apellidos": alumno.apellidos,
                "fecha_nacimiento": str(alumno.fecha_nacimiento) if alumno.fecha_nacimiento else None,
                "genero": alumno.genero,
                "numero_identidad": alumno.numero_identidad,
                "peso": alumno.peso,
                "flexibilidad": alumno.flexibilidad,
                "grado_id": alumno.grado_id,
                "foto": alumno.foto
            }
        )

        flash("Alumno actualizado correctamente", "success")
        return redirect(url_for("alumnos.index"))

    return render_template(
        "alumnos/editar.html",
        alumno=alumno,
        grados=grados,
        participaciones=participaciones,
        fecha_asistencia=hoy.isoformat(),
        asistencia=asistencia_hoy,
        historial_asistencias=historial_asistencias
    )


# =========================
# ELIMINAR ALUMNO
# =========================
@alumnos_bp.route("/<int:id>/eliminar", methods=["POST"])
@login_required
def eliminar(id):
    alumno = tenant_query(Alumno).filter_by(id=id).first_or_404()

    if current_user.has_role("PROFESOR") and alumno.sucursal_id != current_user.sucursal_id:
        flash("No tiene permisos para eliminar este alumno", "danger")
        return redirect(url_for("alumnos.index"))

    registrar_auditoria(
        accion="DELETE",
        entidad="ALUMNO",
        entidad_id=alumno.id,
        descripcion=f"Eliminación de alumno {alumno.nombres} {alumno.apellidos}",
        datos_antes={
            "nombres": alumno.nombres,
            "apellidos": alumno.apellidos,
            "sucursal_id": alumno.sucursal_id
        }
    )

    db.session.delete(alumno)
    db.session.commit()

    flash("Alumno eliminado correctamente", "success")
    return redirect(url_for("alumnos.index"))


# =========================
# PERFIL / HISTORIAL
# =========================
@alumnos_bp.route("/<int:id>/perfil")
@login_required
def perfil(id):
    alumno = tenant_query(Alumno).filter_by(id=id).first_or_404()

    if current_user.has_role("PROFESOR") and alumno.sucursal_id != current_user.sucursal_id:
        flash("No tiene acceso a este alumno", "danger")
        return redirect(url_for("alumnos.index"))

    participaciones = (
        db.session.query(Participacion)
        .join(Torneo, Torneo.id == Participacion.torneo_id)
        .outerjoin(Medalla, Medalla.id == Participacion.medalla_id)
        .filter(
            Participacion.alumno_id == alumno.id,
            Participacion.academia_id == current_user.academia_id
        )
        .order_by(Torneo.fecha.desc())
        .all()
    )

    return render_template(
        "alumnos/perfil.html",
        alumno=alumno,
        participaciones=participaciones
    )