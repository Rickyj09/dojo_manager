from datetime import date

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


def obtener_familia_activa_del_alumno(*, academia_id: int, alumno_id: int):
    membresias = (
        AlumnoGrupoFamiliar.query
        .join(GrupoFamiliar, GrupoFamiliar.id == AlumnoGrupoFamiliar.grupo_familiar_id)
        .filter(
            AlumnoGrupoFamiliar.academia_id == academia_id,
            AlumnoGrupoFamiliar.alumno_id == alumno_id,
            AlumnoGrupoFamiliar.activo.is_(True),
            GrupoFamiliar.academia_id == academia_id,
            GrupoFamiliar.activo.is_(True),
        )
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
    alumno = Alumno.query.filter_by(id=alumno_id, academia_id=academia_id).first()
    if alumno is None:
        raise FinanzasError("Alumno no pertenece a la academia indicada")

    grupo = GrupoFamiliar.query.filter_by(id=grupo_familiar_id, academia_id=academia_id).first()
    if grupo is None:
        raise FinanzasError("Grupo familiar no pertenece a la academia indicada")

    familia_activa = obtener_familia_activa_del_alumno(academia_id=academia_id, alumno_id=alumno_id)
    if familia_activa is not None:
        raise FinanzasError("El alumno ya tiene una familia activa")

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


def retirar_alumno_de_familia(*, academia_id: int, alumno_id: int, fecha_fin: date):
    membresia = (
        AlumnoGrupoFamiliar.query
        .filter_by(academia_id=academia_id, alumno_id=alumno_id, activo=True)
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


def contar_alumnos_activos_de_familia(*, academia_id: int, grupo_familiar_id: int) -> int:
    return (
        AlumnoGrupoFamiliar.query
        .join(Alumno, Alumno.id == AlumnoGrupoFamiliar.alumno_id)
        .filter(
            AlumnoGrupoFamiliar.academia_id == academia_id,
            AlumnoGrupoFamiliar.grupo_familiar_id == grupo_familiar_id,
            AlumnoGrupoFamiliar.activo.is_(True),
            Alumno.academia_id == academia_id,
            Alumno.activo.is_(True),
        )
        .count()
    )
