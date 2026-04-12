from datetime import date

from app.models import CategoriaCompetencia


def calcular_edad(fecha_nacimiento):
    if not fecha_nacimiento:
        return None

    hoy = date.today()
    return (
        hoy.year
        - fecha_nacimiento.year
        - ((hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day))
    )


def _normalizar_genero(genero):
    if not genero:
        return None

    genero = str(genero).strip().upper()

    if genero in ("M", "MASCULINO", "HOMBRE"):
        return "M"
    if genero in ("F", "FEMENINO", "MUJER"):
        return "F"

    return genero


def obtener_categoria_competencia(alumno, torneo, modalidad):
    modalidad = (modalidad or "").strip().upper()
    sexo = _normalizar_genero(alumno.genero)
    edad = calcular_edad(alumno.fecha_nacimiento)

    if not alumno.fecha_nacimiento:
        return None, "El alumno no tiene fecha de nacimiento registrada."
    if not sexo:
        return None, "El alumno no tiene género registrado."
    if modalidad == "POOMSAE" and not alumno.grado_id:
        return None, "El alumno no tiene grado registrado."
    if modalidad == "COMBATE" and alumno.peso is None:
        return None, "El alumno no tiene peso registrado."

    base_query = CategoriaCompetencia.query.filter(
        CategoriaCompetencia.activo == True,
        CategoriaCompetencia.academia_id == alumno.academia_id,
        CategoriaCompetencia.modalidad == modalidad,
        CategoriaCompetencia.sexo == sexo,
        CategoriaCompetencia.edad_min <= edad,
        CategoriaCompetencia.edad_max >= edad,
    )

    if modalidad == "POOMSAE":
        exacta = base_query.filter(
            CategoriaCompetencia.grado_id == alumno.grado_id
        ).order_by(CategoriaCompetencia.id.asc()).first()

        if exacta:
            return exacta, None

        por_rango = base_query.filter(
            CategoriaCompetencia.grado_min_id.isnot(None),
            CategoriaCompetencia.grado_max_id.isnot(None),
            CategoriaCompetencia.grado_min_id <= alumno.grado_id,
            CategoriaCompetencia.grado_max_id >= alumno.grado_id,
        ).order_by(CategoriaCompetencia.id.asc()).first()

        if por_rango:
            return por_rango, None

        fallback = base_query.filter(
            CategoriaCompetencia.nombre.ilike("%GENERAL%")
        ).order_by(CategoriaCompetencia.id.asc()).first()

        if fallback:
            return fallback, None

        return None, (
            "No se encontró categoría válida para POOMSAE. "
            "Revise datos del alumno (edad/grado/sexo)."
        )

    if modalidad == "COMBATE":
        exacta_combate = base_query.filter(
            CategoriaCompetencia.peso_min.isnot(None),
            CategoriaCompetencia.peso_max.isnot(None),
            CategoriaCompetencia.peso_min <= alumno.peso,
            CategoriaCompetencia.peso_max >= alumno.peso,
        ).order_by(CategoriaCompetencia.id.asc()).first()

        if exacta_combate:
            return exacta_combate, None

        fallback_combate = base_query.filter(
            CategoriaCompetencia.nombre.ilike("%GENERAL%")
        ).order_by(CategoriaCompetencia.id.asc()).first()

        if fallback_combate:
            return fallback_combate, None

        return None, (
            "No se encontró categoría válida para COMBATE. "
            "Revise datos del alumno (edad/peso/sexo)."
        )

    return None, "Modalidad inválida."