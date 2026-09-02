from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from app.models.finanzas import ReglaDescuento, TarifaPlan


CENTAVO = Decimal("0.01")


@dataclass(frozen=True)
class ResultadoCalculoTarifa:
    tarifa_base: Decimal
    descuentos_aplicados: list[dict] = field(default_factory=list)
    valor_final: Decimal = Decimal("0.00")


def redondear_dinero(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _regla_aplica(regla: ReglaDescuento, contexto_descuentos: dict) -> bool:
    if not regla.activo:
        return False

    regla_ids = set(contexto_descuentos.get("reglas_descuento_ids") or [])
    if regla_ids and regla.id not in regla_ids:
        return False

    cantidad_alumnos = contexto_descuentos.get("cantidad_alumnos")
    if regla.tipo == "HERMANOS" and regla.cantidad_minima is not None:
        if cantidad_alumnos is None or int(cantidad_alumnos) < regla.cantidad_minima:
            return False

    return True


def calcular_tarifa(
    *,
    academia_id: int,
    tarifario_id: int,
    plan_id: int,
    frecuencia_id: int,
    contexto_descuentos: dict | None = None,
) -> ResultadoCalculoTarifa:
    contexto_descuentos = contexto_descuentos or {}

    tarifa = (
        TarifaPlan.query
        .filter(
            TarifaPlan.academia_id == academia_id,
            TarifaPlan.tarifario_id == tarifario_id,
            TarifaPlan.plan_id == plan_id,
            TarifaPlan.frecuencia_id == frecuencia_id,
            TarifaPlan.activo.is_(True),
        )
        .first()
    )
    if tarifa is None:
        raise ValueError("No existe una tarifa activa para la combinacion indicada")

    valor_base = redondear_dinero(tarifa.valor_base)
    valor_actual = valor_base
    descuentos = []

    regla_ids = contexto_descuentos.get("reglas_descuento_ids") or []
    reglas_query = ReglaDescuento.query.filter(
        ReglaDescuento.academia_id == academia_id,
        ReglaDescuento.activo.is_(True),
    )
    if regla_ids:
        reglas_query = reglas_query.filter(ReglaDescuento.id.in_(regla_ids))
    elif "tipo" in contexto_descuentos:
        reglas_query = reglas_query.filter(ReglaDescuento.tipo == contexto_descuentos["tipo"])

    reglas = reglas_query.order_by(ReglaDescuento.cantidad_minima.desc(), ReglaDescuento.id.asc()).all()

    for regla in reglas:
        if not _regla_aplica(regla, contexto_descuentos):
            continue

        descuento = Decimal("0.00")
        if regla.porcentaje is not None:
            descuento = redondear_dinero(valor_actual * Decimal(regla.porcentaje) / Decimal("100"))
        elif regla.valor_fijo is not None:
            descuento = redondear_dinero(regla.valor_fijo)

        if descuento <= 0:
            continue

        valor_actual = max(Decimal("0.00"), redondear_dinero(valor_actual - descuento))
        descuentos.append(
            {
                "regla_id": regla.id,
                "codigo": regla.codigo,
                "nombre": regla.nombre,
                "tipo": regla.tipo,
                "descuento": descuento,
            }
        )
        if regla.tipo == "HERMANOS" and not regla_ids:
            break

    return ResultadoCalculoTarifa(
        tarifa_base=valor_base,
        descuentos_aplicados=descuentos,
        valor_final=redondear_dinero(valor_actual),
    )
