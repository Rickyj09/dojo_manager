from app.models.categoriascompetencia import CategoriaCompetencia


def calcular_edad(fecha_nacimiento, fecha_torneo):
    edad = fecha_torneo.year - fecha_nacimiento.year
    if (fecha_torneo.month, fecha_torneo.day) < (fecha_nacimiento.month, fecha_nacimiento.day):
        edad -= 1
    return edad


def obtener_categoria_competencia(alumno, torneo, modalidad):
    edad = calcular_edad(alumno.fecha_nacimiento, torneo.fecha)

    categorias = (
        CategoriaCompetencia.query
        .filter_by(
            modalidad=modalidad,
            sexo=alumno.genero,
            activo=True
        )
        .all()
    )

    for cat in categorias:
        # validar edad
        if not (cat.edad_min <= edad <= cat.edad_max):
            continue

        # COMBATE: usa peso
        if modalidad == "COMBATE":
            if alumno.peso is None:
                continue

            peso_alumno = float(alumno.peso)

            if cat.peso_min is not None and peso_alumno < cat.peso_min:
                continue
            if cat.peso_max is not None and peso_alumno > cat.peso_max:
                continue

            return cat

        # POOMSAE: usa grado (rango)
        if modalidad == "POOMSAE":
            if not alumno.grado:
                continue

            orden_alumno = alumno.grado.orden

            if cat.grado_min and cat.grado_max:
                if cat.grado_min.orden <= orden_alumno <= cat.grado_max.orden:
                    return cat

    return None


def sugerir_categoria_combate(alumno, torneo):
    categoria = obtener_categoria_competencia(alumno, torneo, "COMBATE")
    return categoria.nombre if categoria else None


def sugerir_categoria_poomsae(alumno, torneo):
    categoria = obtener_categoria_competencia(alumno, torneo, "POOMSAE")
    return categoria.nombre if categoria else None