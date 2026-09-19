from datetime import date
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.finanzas import ReglaDescuento
from app.services.finanzas.familias import FinanzasError


TIPOS_REGLA_DESCUENTO = (
    "HERMANOS",
    "BECA",
    "CONVENIO",
    "PROMOCION",
    "ESPECIAL",
    "OTRO",
)


def _decimal_opcional(valor, campo):
    valor = str(valor or "").strip()

    if not valor:
        return None

    try:
        return Decimal(valor)
    except (InvalidOperation, ValueError):
        raise FinanzasError(f"El campo {campo} no es válido")


def _entero(valor, campo, *, default=None):
    valor = str(valor or "").strip()

    if not valor:
        if default is not None:
            return default
        return None

    try:
        return int(valor)
    except ValueError:
        raise FinanzasError(f"El campo {campo} no es válido")


def _fecha_opcional(valor, campo):
    valor = str(valor or "").strip()

    if not valor:
        return None

    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise FinanzasError(f"El campo {campo} no es válido")


def _validar_modo_descuento(porcentaje, valor_fijo):
    if porcentaje is None and valor_fijo is None:
        raise FinanzasError(
            "Debe indicar un porcentaje o un valor fijo de descuento."
        )

    if porcentaje is not None and valor_fijo is not None:
        raise FinanzasError(
            "Use porcentaje o valor fijo, no ambos."
        )

    if porcentaje is not None:
        if porcentaje <= 0 or porcentaje > 100:
            raise FinanzasError(
                "El porcentaje debe ser mayor que 0 y máximo 100."
            )

    if valor_fijo is not None:
        if valor_fijo <= 0:
            raise FinanzasError(
                "El valor fijo debe ser mayor que 0."
            )


def guardar_regla_descuento(
    *,
    academia_id: int,
    datos: dict,
    regla: ReglaDescuento | None = None,
):
    codigo = str(datos.get("codigo") or "").strip()
    nombre = str(datos.get("nombre") or "").strip()
    tipo = str(datos.get("tipo") or "").strip().upper()

    if regla is None and not codigo:
        raise FinanzasError("El código es obligatorio.")

    if not nombre:
        raise FinanzasError("El nombre es obligatorio.")

    if tipo not in TIPOS_REGLA_DESCUENTO:
        raise FinanzasError("El tipo de descuento no es válido.")

    porcentaje = _decimal_opcional(
        datos.get("porcentaje"),
        "porcentaje",
    )
    valor_fijo = _decimal_opcional(
        datos.get("valor_fijo"),
        "valor fijo",
    )

    _validar_modo_descuento(
        porcentaje,
        valor_fijo,
    )

    cantidad_minima = _entero(
        datos.get("cantidad_minima"),
        "cantidad mínima",
    )

    if tipo == "HERMANOS":
        if cantidad_minima is None or cantidad_minima < 2:
            raise FinanzasError(
                "Una regla de hermanos requiere cantidad mínima "
                "de al menos 2 alumnos."
            )
    else:
        cantidad_minima = None

    decimales_redondeo = _entero(
        datos.get("decimales_redondeo"),
        "decimales de redondeo",
        default=2,
    )

    if decimales_redondeo < 0 or decimales_redondeo > 4:
        raise FinanzasError(
            "Los decimales de redondeo deben estar entre 0 y 4."
        )

    vigencia_desde = _fecha_opcional(
        datos.get("vigencia_desde"),
        "vigencia desde",
    )
    vigencia_hasta = _fecha_opcional(
        datos.get("vigencia_hasta"),
        "vigencia hasta",
    )

    if (
        vigencia_desde is not None
        and vigencia_hasta is not None
        and vigencia_hasta < vigencia_desde
    ):
        raise FinanzasError(
            "La fecha final de vigencia no puede ser anterior "
            "a la fecha inicial."
        )

    if regla is None:
        regla = ReglaDescuento(
            academia_id=academia_id,
            codigo=codigo,
            activo=True,
        )
        db.session.add(regla)
    elif regla.academia_id != academia_id:
        raise FinanzasError(
            "La regla de descuento no pertenece a la academia indicada."
        )

    regla.nombre = nombre
    regla.tipo = tipo
    regla.porcentaje = porcentaje
    regla.valor_fijo = valor_fijo
    regla.cantidad_minima = cantidad_minima
    regla.decimales_redondeo = decimales_redondeo
    regla.requiere_autorizacion = bool(
        datos.get("requiere_autorizacion")
    )
    regla.vigencia_desde = vigencia_desde
    regla.vigencia_hasta = vigencia_hasta

    db.session.flush()

    return regla


def alternar_regla_descuento(
    *,
    academia_id: int,
    regla: ReglaDescuento,
):
    if regla.academia_id != academia_id:
        raise FinanzasError(
            "La regla de descuento no pertenece a la academia indicada."
        )

    regla.activo = not regla.activo
    db.session.flush()

    return regla