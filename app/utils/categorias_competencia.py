# app/utils/categorias_competencia.py
from datetime import date

from sqlalchemy import and_, or_
from app.models import CategoriaCompetencia


def calcular_edad(fecha_nacimiento, fecha_referencia=None):
    if not fecha_nacimiento:
        return None

    if not fecha_referencia:
        fecha_referencia = date.today()

    return (
        fecha_referencia.year
        - fecha_nacimiento.year
        - ((fecha_referencia.month, fecha_referencia.day) < (fecha_nacimiento.month, fecha_nacimiento.day))
    )


def buscar_categoria_competencia(alumno, modalidad: str):
    """
    Devuelve la mejor CategoriaCompetencia para el alumno y modalidad.
    Prioridad:
    1) exacta por grado_id
    2) rango grado_min_id/grado_max_id
    3) fallback general
    """
    if not alumno.fecha_nacimiento:
        return None, "El alumno no tiene fecha de nacimiento."
    if not alumno.genero:
        return None, "El alumno no tiene género."
    if not alumno.grado_id:
        return None, "El alumno no tiene grado asignado."

    edad = calcular_edad(alumno.fecha_nacimiento)
    modalidad = (modalidad or "").upper().strip()
    sexo = (alumno.genero or "").upper().strip()
    academia_id = alumno.academia_id

    base_query = CategoriaCompetencia.query.filter(
        CategoriaCompetencia.activo == True,
        CategoriaCompetencia.academia_id == academia_id,
        CategoriaCompetencia.modalidad == modalidad,
        CategoriaCompetencia.sexo == sexo,
        CategoriaCompetencia.edad_min <= edad,
        CategoriaCompetencia.edad_max >= edad,
    )

    # COMBATE exige peso
    if modalidad == "COMBATE":
        if alumno.peso is None:
            return None, "El alumno no tiene peso registrado."
        base_query = base_query.filter(
            CategoriaCompetencia.peso_min <= alumno.peso,
            CategoriaCompetencia.peso_max >= alumno.peso,
        )

    # 1) Exacta por grado_id
    exacta = base_query.filter(
        CategoriaCompetencia.grado_id == alumno.grado_id
    ).order_by(CategoriaCompetencia.id.asc()).first()

    if exacta:
        return exacta, None

    # 2) Por rango de grado
    por_rango = base_query.filter(
        CategoriaCompetencia.grado_min_id.isnot(None),
        CategoriaCompetencia.grado_max_id.isnot(None),
        CategoriaCompetencia.grado_min_id <= alumno.grado_id,
        CategoriaCompetencia.grado_max_id >= alumno.grado_id,
    ).order_by(CategoriaCompetencia.id.asc()).first()

    if por_rango:
        return por_rango, None

    # 3) Fallback general
    # Convención recomendada: categorias amplias con nombre GENERAL
    fallback = base_query.filter(
        or_(
            CategoriaCompetencia.nombre.ilike("%GENERAL%"),
            and_(
                CategoriaCompetencia.grado_id.is_(None),
                CategoriaCompetencia.grado_min_id.is_(None),
                CategoriaCompetencia.grado_max_id.is_(None),
            ),
        )
    ).order_by(CategoriaCompetencia.id.asc()).first()

    if fallback:
        return fallback, None

    return None, (
        f"No se encontró categoría válida para {modalidad}. "
        f"Revise datos del alumno (edad/peso/grado/sexo)."
    )