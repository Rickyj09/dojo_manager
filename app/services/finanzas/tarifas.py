from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from app.models.finanzas import ReglaDescuento, TarifaPlan
from app.services.finanzas.tarifarios import validar_referencias_activas, validar_tarifario_utilizable


CENTAVO = Decimal("0.01")


@dataclass(frozen=True)
class ResultadoCalculoTarifa:
    tarifa_base: Decimal
    descuentos_aplicados: list[dict] = field(default_factory=list)
    valor_final: Decimal = Decimal("0.00")


def redondear_decimal(value: Decimal, decimales: int = 2) -> Decimal:
    quantum = Decimal("1").scaleb(-int(decimales))
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def redondear_dinero(value: Decimal) -> Decimal:
    return redondear_decimal(value, 2)


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

    fecha = contexto_descuentos.get("fecha")
    if fecha is not None:
        if regla.vigencia_desde is not None and fecha < regla.vigencia_desde:
            return False
        if regla.vigencia_hasta is not None and fecha > regla.vigencia_hasta:
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

    validar_referencias_activas(academia_id=academia_id, plan_id=plan_id, frecuencia_id=frecuencia_id)
    validar_tarifario_utilizable(
        tarifa.tarifario, academia_id=academia_id,
        fecha=contexto_descuentos.get("fecha") or date.today(),
    )

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
            valor_con_descuento = valor_actual * (Decimal("100") - Decimal(regla.porcentaje)) / Decimal("100")
            valor_con_descuento = redondear_decimal(valor_con_descuento, regla.decimales_redondeo)
            valor_con_descuento = redondear_dinero(valor_con_descuento)
            descuento = redondear_dinero(valor_actual - valor_con_descuento)
        elif regla.valor_fijo is not None:
            descuento = redondear_decimal(regla.valor_fijo, regla.decimales_redondeo)
            descuento = redondear_dinero(descuento)

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
