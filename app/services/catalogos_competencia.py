import json
from collections import Counter
from pathlib import Path

from app.extensions import db
from app.models import CategoriaCompetencia, Grado


ARCHIVO_CATALOGO = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "categorias_competencia_tkd.json"
)

TOTAL_ESPERADO = 192

DISTRIBUCION_ESPERADA = {
    ("COMBATE", "M"): 60,
    ("COMBATE", "F"): 60,
    ("POOMSAE", "M"): 36,
    ("POOMSAE", "F"): 36,
}


def _normalizar_texto(valor):
    if valor is None:
        return None

    valor = str(valor).strip()
    return valor or None


def _normalizar_float(valor):
    if valor is None:
        return None

    return float(valor)


def _resolver_grado_id(grados_por_nombre, nombre):
    nombre = _normalizar_texto(nombre)

    if not nombre:
        return None

    grado_id = grados_por_nombre.get(nombre)

    if grado_id is None:
        raise RuntimeError(
            f"No existe en DojoManager el grado requerido por el catálogo: {nombre}"
        )

    return grado_id


def _clave_categoria(
    *,
    modalidad,
    sexo,
    edad_min,
    edad_max,
    peso_min,
    peso_max,
    grado_id,
    grado_min_id,
    grado_max_id,
    nombre,
):
    return (
        str(modalidad).strip().upper(),
        str(sexo).strip().upper(),
        int(edad_min),
        int(edad_max),
        _normalizar_float(peso_min),
        _normalizar_float(peso_max),
        grado_id,
        grado_min_id,
        grado_max_id,
        str(nombre).strip(),
    )


def asegurar_categorias_competencia_base(
    academia_id: int,
    archivo=None,
):
    """
    Carga el catálogo TKD base de categorías de competencia
    para una academia.

    Es idempotente:
    ejecutar varias veces no duplica las mismas categorías.

    No realiza commit.
    El llamador controla la transacción.
    """

    ruta = Path(archivo) if archivo else ARCHIVO_CATALOGO

    if not ruta.exists():
        raise RuntimeError(
            f"No existe el catálogo de categorías: {ruta}"
        )

    with ruta.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    categorias = payload.get("categorias")

    if not isinstance(categorias, list):
        raise RuntimeError(
            "El JSON no contiene una lista válida en 'categorias'."
        )

    if len(categorias) != TOTAL_ESPERADO:
        raise RuntimeError(
            f"Catálogo incompleto: se esperaban "
            f"{TOTAL_ESPERADO} categorías y se encontraron "
            f"{len(categorias)}."
        )

    distribucion = Counter(
        (
            str(item["modalidad"]).strip().upper(),
            str(item["sexo"]).strip().upper(),
        )
        for item in categorias
    )

    if dict(distribucion) != DISTRIBUCION_ESPERADA:
        raise RuntimeError(
            "La distribución del catálogo no coincide con "
            f"la esperada. Encontrado: {dict(distribucion)}"
        )

    grados_por_nombre = {
        g.nombre.strip(): g.id
        for g in Grado.query.all()
    }

    existentes = {}

    for categoria in (
        CategoriaCompetencia.query
        .filter_by(academia_id=academia_id)
        .all()
    ):
        clave = _clave_categoria(
            modalidad=categoria.modalidad,
            sexo=categoria.sexo,
            edad_min=categoria.edad_min,
            edad_max=categoria.edad_max,
            peso_min=categoria.peso_min,
            peso_max=categoria.peso_max,
            grado_id=categoria.grado_id,
            grado_min_id=categoria.grado_min_id,
            grado_max_id=categoria.grado_max_id,
            nombre=categoria.nombre,
        )

        existentes[clave] = categoria

    creadas = 0
    actualizadas = 0
    sin_cambios = 0

    for item in categorias:
        grado_id = _resolver_grado_id(
            grados_por_nombre,
            item.get("grado_nombre"),
        )

        grado_min_id = _resolver_grado_id(
            grados_por_nombre,
            item.get("grado_min_nombre"),
        )

        grado_max_id = _resolver_grado_id(
            grados_por_nombre,
            item.get("grado_max_nombre"),
        )

        modalidad = str(item["modalidad"]).strip().upper()
        sexo = str(item["sexo"]).strip().upper()
        edad_min = int(item["edad_min"])
        edad_max = int(item["edad_max"])
        peso_min = _normalizar_float(item.get("peso_min"))
        peso_max = _normalizar_float(item.get("peso_max"))
        nombre = str(item["nombre"]).strip()
        activo = bool(item.get("activo", True))

        clave = _clave_categoria(
            modalidad=modalidad,
            sexo=sexo,
            edad_min=edad_min,
            edad_max=edad_max,
            peso_min=peso_min,
            peso_max=peso_max,
            grado_id=grado_id,
            grado_min_id=grado_min_id,
            grado_max_id=grado_max_id,
            nombre=nombre,
        )

        existente = existentes.get(clave)

        if existente:
            if existente.activo != activo:
                existente.activo = activo
                actualizadas += 1
            else:
                sin_cambios += 1

            continue

        categoria = CategoriaCompetencia(
            academia_id=academia_id,
            modalidad=modalidad,
            sexo=sexo,
            edad_min=edad_min,
            edad_max=edad_max,
            peso_min=peso_min,
            peso_max=peso_max,
            grado_id=grado_id,
            grado_min_id=grado_min_id,
            grado_max_id=grado_max_id,
            nombre=nombre,
            activo=activo,
        )

        db.session.add(categoria)

        existentes[clave] = categoria
        creadas += 1

    return {
        "academia_id": academia_id,
        "creadas": creadas,
        "actualizadas": actualizadas,
        "sin_cambios": sin_cambios,
        "total_catalogo": len(categorias),
    }
