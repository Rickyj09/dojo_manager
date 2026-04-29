from __future__ import annotations

from datetime import date, datetime

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required
from sqlalchemy import String, cast, or_

from app.extensions import csrf, db
from app.models.alumno import Alumno
from app.models.asistencia import Asistencia
from app.models.sucursal import Sucursal
from app.utils.mensualidad import aviso_mensualidad, mensualidad_pagada


kiosk_bp = Blueprint("kiosk", __name__, url_prefix="/kiosk")

# Mantener en False para produccion. Si quieres que el kiosko busque en
# toda la academia cuando no haya resultados en la sucursal, cambia a True.
DEMO_ALLOW_CROSS_BRANCH_SEARCH = False


def _parse_fecha(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return date.today()


def _parse_fecha_strict(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _current_academia_id() -> int | None:
    return getattr(current_user, "academia_id", None)


def _sucursales_disponibles() -> list[Sucursal]:
    query = Sucursal.query.order_by(Sucursal.nombre.asc())
    academia_id = _current_academia_id()
    if academia_id:
        query = query.filter(Sucursal.academia_id == academia_id)
    return query.all()


def _sucursal_valida_para_usuario(sucursal_id: int | None, sucursales: list[Sucursal]) -> int | None:
    if not sucursal_id:
        return None
    valid_ids = {s.id for s in sucursales}
    return sucursal_id if sucursal_id in valid_ids else None


def _get_identidad_value(alumno: Alumno) -> str:
    for attr in ("numero_identidad", "identidad", "cedula", "dni", "documento", "num_documento"):
        if hasattr(alumno, attr):
            value = getattr(alumno, attr)
            return str(value).strip() if value is not None else ""
    return ""


def _get_nombre_completo(alumno: Alumno) -> str:
    partes = []
    for attr in ("nombres", "nombre"):
        if hasattr(alumno, attr) and getattr(alumno, attr):
            partes.append(str(getattr(alumno, attr)).strip())
    for attr in ("apellidos", "apellido"):
        if hasattr(alumno, attr) and getattr(alumno, attr):
            partes.append(str(getattr(alumno, attr)).strip())
    return " ".join(partes).strip() if partes else f"Alumno #{alumno.id}"


def _alumno_to_dict(alumno: Alumno) -> dict:
    return {
        "id": alumno.id,
        "nombre": _get_nombre_completo(alumno),
        "identidad": _get_identidad_value(alumno),
        "sucursal_id": getattr(alumno, "sucursal_id", None),
        "activo": bool(getattr(alumno, "activo", True)),
    }


def _estado_valido(estado: str) -> bool:
    return estado in ("P", "A", "T", "J")


@kiosk_bp.route("/asistencia", methods=["GET"])
@login_required
def asistencia():
    fecha = _parse_fecha(request.args.get("fecha"))
    sucursales = _sucursales_disponibles()

    sucursal_id = _sucursal_valida_para_usuario(
        request.args.get("sucursal_id", type=int),
        sucursales,
    )

    if sucursal_id is None:
        sucursal_id = _sucursal_valida_para_usuario(
            getattr(current_user, "sucursal_id", None),
            sucursales,
        )

    if sucursal_id is None and sucursales:
        sucursal_id = sucursales[0].id

    return render_template(
        "kiosk/asistencia.html",
        fecha=fecha,
        sucursales=sucursales,
        sucursal_id=sucursal_id,
    )


@kiosk_bp.route("/buscar", methods=["GET"])
@login_required
def buscar():
    q = (request.args.get("q") or "").strip()
    sucursal_id = request.args.get("sucursal_id", type=int)

    if len(q) < 2:
        return jsonify({"ok": True, "data": [], "warning": None})

    filtros = []
    for attr in ("numero_identidad", "identidad", "cedula", "dni", "documento", "num_documento"):
        if hasattr(Alumno, attr):
            filtros.append(cast(getattr(Alumno, attr), String).ilike(f"%{q}%"))

    for attr in ("nombres", "nombre", "apellidos", "apellido"):
        if hasattr(Alumno, attr):
            filtros.append(getattr(Alumno, attr).ilike(f"%{q}%"))

    if not filtros:
        return jsonify({"ok": False, "error": "No hay campos buscables en Alumno."}), 500

    academia_id = _current_academia_id()

    base_query = Alumno.query.filter(or_(*filtros))
    if academia_id and hasattr(Alumno, "academia_id"):
        base_query = base_query.filter(Alumno.academia_id == academia_id)
    if hasattr(Alumno, "activo"):
        base_query = base_query.filter(Alumno.activo == True)

    warning = None
    query = base_query
    if sucursal_id and hasattr(Alumno, "sucursal_id"):
        query = query.filter(Alumno.sucursal_id == sucursal_id)

    alumnos = query.order_by(Alumno.apellidos.asc(), Alumno.nombres.asc()).limit(12).all()

    if not alumnos and sucursal_id:
        warning = f"No hay alumnos activos en la sucursal seleccionada (ID {sucursal_id})."
        if DEMO_ALLOW_CROSS_BRANCH_SEARCH:
            alumnos = base_query.order_by(Alumno.apellidos.asc(), Alumno.nombres.asc()).limit(12).all()
            if alumnos:
                warning = (
                    f"No hay alumnos en la sucursal seleccionada (ID {sucursal_id}). "
                    "Mostrando coincidencias de toda la academia por modo demo."
                )

    return jsonify({
        "ok": True,
        "data": [_alumno_to_dict(alumno) for alumno in alumnos],
        "warning": warning,
    })


@kiosk_bp.route("/marcar", methods=["POST"])
@csrf.exempt
@login_required
def marcar():
    payload = request.get_json(silent=True) or {}

    alumno_id = payload.get("alumno_id")
    sucursal_id = payload.get("sucursal_id")
    fecha_raw = payload.get("fecha")
    estado = (payload.get("estado") or "P").strip().upper()
    observacion = (payload.get("observacion") or "").strip() or None

    if not alumno_id:
        return jsonify({"ok": False, "error": "alumno_id es requerido"}), 400
    if not sucursal_id:
        return jsonify({"ok": False, "error": "sucursal_id es requerido"}), 400
    if not _estado_valido(estado):
        return jsonify({"ok": False, "error": "estado invalido (use P/A/T/J)"}), 400

    fecha = _parse_fecha_strict(fecha_raw)
    if not fecha:
        return jsonify({"ok": False, "error": "fecha invalida (use YYYY-MM-DD)"}), 400

    alumno = Alumno.query.get(alumno_id)
    if not alumno:
        return jsonify({"ok": False, "error": "Alumno no existe"}), 404

    sucursal = Sucursal.query.get(sucursal_id)
    if not sucursal:
        return jsonify({"ok": False, "error": "Sucursal no existe"}), 404

    academia_usuario = _current_academia_id()
    academia_alumno = getattr(alumno, "academia_id", None)
    academia_sucursal = getattr(sucursal, "academia_id", None)

    if academia_usuario and academia_alumno != academia_usuario:
        return jsonify({"ok": False, "error": "El alumno no pertenece a tu academia"}), 403
    if academia_usuario and academia_sucursal != academia_usuario:
        return jsonify({"ok": False, "error": "La sucursal no pertenece a tu academia"}), 403
    if academia_alumno and academia_sucursal and academia_alumno != academia_sucursal:
        return jsonify({"ok": False, "error": "Alumno y sucursal no pertenecen a la misma academia"}), 400
    if getattr(alumno, "sucursal_id", None) and alumno.sucursal_id != sucursal.id:
        return jsonify({"ok": False, "error": "El alumno no pertenece a la sucursal seleccionada"}), 400

    academia_id = academia_sucursal or academia_alumno or academia_usuario
    if not academia_id:
        return jsonify({"ok": False, "error": "No se pudo determinar la academia de la asistencia"}), 400

    asistencia = Asistencia.query.filter_by(
        fecha=fecha,
        alumno_id=alumno.id,
        sucursal_id=sucursal.id,
    ).first()

    if asistencia:
        asistencia.estado = estado
        asistencia.observacion = observacion
        asistencia.registrado_por_id = current_user.id
        asistencia.academia_id = academia_id
    else:
        asistencia = Asistencia(
            fecha=fecha,
            alumno_id=alumno.id,
            sucursal_id=sucursal.id,
            academia_id=academia_id,
            registrado_por_id=current_user.id,
            estado=estado,
            observacion=observacion,
        )
        db.session.add(asistencia)

    db.session.commit()

    aviso = ""
    try:
        pagada = mensualidad_pagada(alumno_id=alumno.id, sucursal_id=sucursal.id, fecha=fecha)
        aviso = aviso_mensualidad(fecha, pagada)
    except Exception:
        aviso = ""

    return jsonify({
        "ok": True,
        "message": "Asistencia registrada",
        "aviso": aviso,
        "data": {
            "fecha": fecha.isoformat(),
            "alumno_id": alumno.id,
            "sucursal_id": sucursal.id,
            "academia_id": academia_id,
            "estado": estado,
            "observacion": observacion,
        },
    })
