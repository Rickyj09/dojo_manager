from __future__ import annotations

from datetime import date, datetime
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_, cast, String

from app.extensions import db, csrf
from app.models.alumno import Alumno
from app.models.sucursal import Sucursal
from app.models.asistencia import Asistencia
from app.utils.mensualidad import mensualidad_pagada, aviso_mensualidad


kiosk_bp = Blueprint("kiosk", __name__, url_prefix="/kiosk")


# ---------- Helpers ----------
def _parse_fecha(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return date.today()


def _get_identidad_value(a: Alumno) -> str:
    for attr in ("numero_identidad", "identidad", "cedula", "dni", "documento", "num_documento"):
        if hasattr(a, attr):
            val = getattr(a, attr)
            return (str(val).strip() if val is not None else "")
    return ""


def _get_nombre_completo(a: Alumno) -> str:
    if hasattr(a, "nombre_completo") and getattr(a, "nombre_completo"):
        return str(getattr(a, "nombre_completo")).strip()

    partes = []
    for attr in ("nombres", "nombre"):
        if hasattr(a, attr) and getattr(a, attr):
            partes.append(str(getattr(a, attr)).strip())
    for attr in ("apellidos", "apellido"):
        if hasattr(a, attr) and getattr(a, attr):
            partes.append(str(getattr(a, attr)).strip())
    return " ".join(partes).strip() if partes else f"Alumno #{a.id}"


def _alumno_to_dict(a: Alumno) -> dict:
    return {
        "id": a.id,
        "identidad": _get_identidad_value(a),
        "nombre": _get_nombre_completo(a),
        "sucursal_id": getattr(a, "sucursal_id", None),
        "activo": bool(getattr(a, "activo", True)),
    }


def _estado_valido(estado: str) -> bool:
    return estado in ("P", "A", "T", "J")


@kiosk_bp.route("/asistencia", methods=["GET"])
@login_required
def asistencia():
    """
    Pantalla kiosko: registra asistencia por fecha y sucursal, para alumnos.
    """
    fecha = _parse_fecha(request.args.get("fecha"))

    # Sucursales para selector
    sucursales = Sucursal.query.order_by(Sucursal.nombre.asc()).all()

    # Sucursal por defecto:
    # 1) si el user tiene sucursal_id, úsala; si no, la primera.
    sucursal_id = request.args.get("sucursal_id", type=int)
    if not sucursal_id:
        sucursal_id = getattr(current_user, "sucursal_id", None)
    if not sucursal_id and sucursales:
        sucursal_id = sucursales[0].id

    return render_template(
        "kiosk/asistencia.html",
        fecha=fecha,
        sucursales=sucursales,
        sucursal_id=sucursal_id
    )

from sqlalchemy import or_, cast, String

@kiosk_bp.route("/buscar", methods=["GET"])
@login_required
def buscar():
    q = (request.args.get("q") or "").strip()
    sucursal_id = request.args.get("sucursal_id", type=int)

    if len(q) < 2:
        return jsonify({"ok": True, "data": []})

    filtros = []

    # ---- Identidad (blindado con CAST a texto) ----
    for attr in ("numero_identidad", "identidad", "cedula", "dni", "documento", "num_documento"):
        if hasattr(Alumno, attr):
            col = getattr(Alumno, attr)
            filtros.append(cast(col, String).like(f"%{q}%"))

    # ---- Nombres / Apellidos ----
    for attr in ("nombres", "nombre", "apellidos", "apellido"):
        if hasattr(Alumno, attr):
            filtros.append(getattr(Alumno, attr).ilike(f"%{q}%"))

    if not filtros:
        return jsonify({"ok": False, "error": "No hay campos buscables en Alumno."}), 500

    query = Alumno.query.filter(or_(*filtros))

    # ---- Filtro por academia (tu tabla tiene academia_id) ----
    if hasattr(Alumno, "academia_id") and hasattr(current_user, "academia_id"):
        if current_user.academia_id:
            query = query.filter(Alumno.academia_id == current_user.academia_id)

    # ---- Activos (tu activo es 1/0) ----
    if hasattr(Alumno, "activo"):
        query = query.filter(Alumno.activo == 1)

    # ---- Sucursal ----
    if sucursal_id and hasattr(Alumno, "sucursal_id"):
        query = query.filter(Alumno.sucursal_id == sucursal_id)

    alumnos = query.order_by(Alumno.id.desc()).limit(12).all()
    return jsonify({"ok": True, "data": [_alumno_to_dict(a) for a in alumnos]})

@kiosk_bp.route("/marcar", methods=["POST"])
@csrf.exempt
@login_required
def marcar():
    payload = request.get_json(silent=True) or {}

    alumno_id = payload.get("alumno_id")
    fecha = _parse_fecha(payload.get("fecha"))
    sucursal_id = payload.get("sucursal_id")
    estado = (payload.get("estado") or "P").strip().upper()
    observacion = (payload.get("observacion") or "").strip() or None

    if not alumno_id:
        return jsonify({"ok": False, "error": "alumno_id es requerido"}), 400
    if not sucursal_id:
        return jsonify({"ok": False, "error": "sucursal_id es requerido"}), 400
    if not _estado_valido(estado):
        return jsonify({"ok": False, "error": "estado inválido (use P/A/T/J)"}), 400

    alumno = Alumno.query.get(alumno_id)
    if not alumno:
        return jsonify({"ok": False, "error": "Alumno no existe"}), 404

    suc = Sucursal.query.get(sucursal_id)
    if not suc:
        return jsonify({"ok": False, "error": "Sucursal no existe"}), 404

    # ✅ academia_id desde sucursal (confiable)
    academia_id = getattr(suc, "academia_id", None)
    if not academia_id:
        return jsonify({"ok": False, "error": "Sucursal sin academia_id"}), 400

    asistencia = Asistencia.query.filter_by(
        fecha=fecha,
        alumno_id=alumno_id,
        sucursal_id=sucursal_id
    ).first()

    if asistencia:
        asistencia.estado = estado
        asistencia.observacion = observacion
        asistencia.registrado_por_id = current_user.id
        asistencia.academia_id = academia_id
    else:
        asistencia = Asistencia(
            fecha=fecha,
            alumno_id=alumno_id,
            sucursal_id=sucursal_id,
            registrado_por_id=current_user.id,
            estado=estado,
            observacion=observacion,
            academia_id=academia_id
        )
        db.session.add(asistencia)

    db.session.commit()

        # --- Aviso mensualidad (regla cliente) ---
    pagada = mensualidad_pagada(alumno_id=alumno.id, sucursal_id=sucursal_id, fecha=fecha)
    aviso = aviso_mensualidad(fecha, pagada)

    return jsonify({
        "ok": True,
        "message": "Asistencia registrada",
        "aviso": aviso,
        "data": {
            "fecha": fecha.isoformat(),
            "alumno_id": alumno_id,
            "sucursal_id": sucursal_id,
            "academia_id": academia_id,
            "estado": estado,
            "observacion": observacion
        }
    })