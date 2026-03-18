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
        .order_by(CategoriaCompetencia.edad_min, CategoriaCompetencia.peso_min)
        .all()
    )

    for cat in categorias:
        if not (cat.edad_min <= edad <= cat.edad_max):
            continue

        # COMBATE
        if modalidad == "COMBATE":
            if alumno.peso is None:
                continue

            peso_alumno = float(alumno.peso)

            if cat.peso_min is not None and peso_alumno < cat.peso_min:
                continue
            if cat.peso_max is not None and peso_alumno > cat.peso_max:
                continue

            return cat

        # POOMSAE
        if modalidad == "POOMSAE":
            if not alumno.grado:
                continue

            orden_alumno = alumno.grado.orden

            # nueva estructura con rango
            if getattr(cat, "grado_min", None) is not None and getattr(cat, "grado_max", None) is not None:
                if cat.grado_min.orden <= orden_alumno <= cat.grado_max.orden:
                    return cat

            # compatibilidad con estructura vieja
            elif getattr(cat, "grado_id", None):
                if alumno.grado_id == cat.grado_id:
                    return cat

    return None


def evaluar_categoria_combate(alumno, torneo):
    if alumno.peso is None:
        return {
            "ok": False,
            "estado": "FALTA_PESO",
            "texto": "Falta peso",
            "badge": "danger"
        }

    categoria = obtener_categoria_competencia(alumno, torneo, "COMBATE")

    if categoria:
        return {
            "ok": True,
            "estado": "OK",
            "texto": categoria.nombre,
            "badge": "primary"
        }

    return {
        "ok": False,
        "estado": "SIN_CATEGORIA",
        "texto": "Sin categoría",
        "badge": "warning"
    }


def evaluar_categoria_poomsae(alumno, torneo):
    if not alumno.grado:
        return {
            "ok": False,
            "estado": "FALTA_GRADO",
            "texto": "Falta grado",
            "badge": "danger"
        }

    categoria = obtener_categoria_competencia(alumno, torneo, "POOMSAE")

    if categoria:
        return {
            "ok": True,
            "estado": "OK",
            "texto": categoria.nombre,
            "badge": "success"
        }

    return {
        "ok": False,
        "estado": "SIN_CATEGORIA",
        "texto": "Sin categoría",
        "badge": "warning"
    }


def sugerir_categoria_combate(alumno, torneo):
    return evaluar_categoria_combate(alumno, torneo)


def sugerir_categoria_poomsae(alumno, torneo):
    return evaluar_categoria_poomsae(alumno, torneo)