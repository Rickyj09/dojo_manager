from datetime import date
from sqlalchemy import or_, update

from app.extensions import db
from app.models.alumno import Alumno
from app.models.finanzas import AlumnoGrupoFamiliar, GrupoFamiliar


class FinanzasError(ValueError):
    pass


def crear_grupo_familiar(*, academia_id: int, codigo: str, nombre: str, observaciones: str | None = None):
    grupo = GrupoFamiliar(
        academia_id=academia_id,
        codigo=codigo,
        nombre=nombre,
        observaciones=observaciones,
        activo=True,
    )
    db.session.add(grupo)
    db.session.flush()
    return grupo


def obtener_familia_activa_del_alumno(
    *,
    academia_id: int,
    alumno_id: int,
    fecha_referencia=None,
):
    filtros = [
        AlumnoGrupoFamiliar.academia_id == academia_id,
        AlumnoGrupoFamiliar.alumno_id == alumno_id,
        GrupoFamiliar.academia_id == academia_id,
    ]

    if fecha_referencia is None:
        filtros.extend([
            AlumnoGrupoFamiliar.activo.is_(True),
            GrupoFamiliar.activo.is_(True),
        ])
    else:
        filtros.extend([
            AlumnoGrupoFamiliar.fecha_inicio <= fecha_referencia,
            or_(
                AlumnoGrupoFamiliar.fecha_fin.is_(None),
                AlumnoGrupoFamiliar.fecha_fin >= fecha_referencia,
            ),
        ])

    membresias = (
        AlumnoGrupoFamiliar.query
        .join(
            GrupoFamiliar,
            GrupoFamiliar.id == AlumnoGrupoFamiliar.grupo_familiar_id,
        )
        .filter(*filtros)
        .all()
    )

    if len(membresias) > 1:
        raise FinanzasError("El alumno tiene mas de una familia activa")

    return membresias[0].grupo_familiar if membresias else None


def asignar_alumno_a_familia(
    *,
    academia_id: int,
    alumno_id: int,
    grupo_familiar_id: int,
    fecha_inicio: date,
):
    db.session.execute(update(Alumno).where(Alumno.id == alumno_id, Alumno.academia_id == academia_id)
                       .values(activo=Alumno.activo).execution_options(synchronize_session=False))
    alumno = Alumno.query.filter_by(id=alumno_id, academia_id=academia_id).first()
    if alumno is None:
        raise FinanzasError("Alumno no pertenece a la academia indicada")

    grupo = GrupoFamiliar.query.filter_by(id=grupo_familiar_id, academia_id=academia_id).first()
    if grupo is None:
        raise FinanzasError("Grupo familiar no pertenece a la academia indicada")
    if not alumno.activo or not grupo.activo:
        raise FinanzasError("El alumno y la familia deben estar activos.")

    familia_activa = obtener_familia_activa_del_alumno(academia_id=academia_id, alumno_id=alumno_id)
    if familia_activa is not None:
        raise FinanzasError("El alumno ya tiene una familia activa")
    if AlumnoGrupoFamiliar.query.filter(
        AlumnoGrupoFamiliar.academia_id == academia_id, AlumnoGrupoFamiliar.alumno_id == alumno_id,
        or_(AlumnoGrupoFamiliar.fecha_fin.is_(None), AlumnoGrupoFamiliar.fecha_fin >= fecha_inicio),
    ).first():
        raise FinanzasError("El ingreso se solapa con una membresía familiar existente.")

    membresia = AlumnoGrupoFamiliar(
        academia_id=academia_id,
        grupo_familiar_id=grupo.id,
        alumno_id=alumno.id,
        fecha_inicio=fecha_inicio,
        activo=True,
    )
    db.session.add(membresia)
    db.session.flush()
    return membresia


def retirar_alumno_de_familia(*, academia_id: int, alumno_id: int, fecha_fin: date, grupo_familiar_id=None):
    db.session.execute(update(Alumno).where(Alumno.id == alumno_id, Alumno.academia_id == academia_id)
                       .values(activo=Alumno.activo).execution_options(synchronize_session=False))
    membresia = (
        AlumnoGrupoFamiliar.query
        .filter_by(academia_id=academia_id, alumno_id=alumno_id, activo=True)
        .filter(AlumnoGrupoFamiliar.grupo_familiar_id == grupo_familiar_id if grupo_familiar_id is not None else True)
        .populate_existing()
        .first()
    )
    if membresia is None:
        raise FinanzasError("El alumno no tiene una familia activa")
    if fecha_fin < membresia.fecha_inicio:
        raise FinanzasError("La fecha de retiro no puede ser anterior al ingreso familiar")

    membresia.fecha_fin = fecha_fin
    membresia.activo = False
    db.session.flush()
    return membresia


def contar_alumnos_activos_de_familia(
    *,
    academia_id: int,
    grupo_familiar_id: int,
    fecha_referencia=None,
) -> int:
    filtros = [
        AlumnoGrupoFamiliar.academia_id == academia_id,
        AlumnoGrupoFamiliar.grupo_familiar_id == grupo_familiar_id,
        Alumno.academia_id == academia_id,
    ]

    if fecha_referencia is None:
        filtros.extend([
            AlumnoGrupoFamiliar.activo.is_(True),
            Alumno.activo.is_(True),
        ])
    else:
        filtros.extend([
            AlumnoGrupoFamiliar.fecha_inicio <= fecha_referencia,
            or_(
                AlumnoGrupoFamiliar.fecha_fin.is_(None),
                AlumnoGrupoFamiliar.fecha_fin >= fecha_referencia,
            ),
        ])

    return (
        AlumnoGrupoFamiliar.query
        .join(Alumno, Alumno.id == AlumnoGrupoFamiliar.alumno_id)
        .filter(*filtros)
        .count()
    )
