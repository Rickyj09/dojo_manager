import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.finanzas.familias import FinanzasError


CONDICION_SIN_VENCIMIENTO = "SIN_VENCIMIENTO"
CONDICION_VIGENTE = "VIGENTE"
CONDICION_VENCIDA = "VENCIDA"

BUCKET_SIN_VENCIMIENTO = "SIN_VENCIMIENTO"
BUCKET_NO_VENCIDA = "NO_VENCIDA"
BUCKET_1_30 = "1_30"
BUCKET_31_60 = "31_60"
BUCKET_61_90 = "61_90"
BUCKET_MAS_90 = "MAS_90"


@dataclass(frozen=True)
class AnalisisVencimiento:
    condicion: str
    dias_atraso: int
    bucket_antiguedad: str


def validar_dia_vencimiento_pension(dia: int | None) -> int | None:
    if dia is None or dia == "":
        return None
    dia = int(dia)
    if dia < 1 or dia > 31:
        raise FinanzasError("El dia de vencimiento de pension debe estar entre 1 y 31")
    return dia


def calcular_fecha_vencimiento_pension(periodo: str, dia_vencimiento_pension: int | None) -> date | None:
    dia = validar_dia_vencimiento_pension(dia_vencimiento_pension)
    if dia is None:
        return None

    try:
        anio, mes = (int(parte) for parte in periodo.split("-", 1))
    except (AttributeError, TypeError, ValueError):
        raise FinanzasError("El periodo debe tener formato YYYY-MM")

    if mes < 1 or mes > 12:
        raise FinanzasError("El periodo debe tener formato YYYY-MM")

    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(dia, ultimo_dia))


def analizar_vencimiento_obligacion(
    *,
    fecha_vencimiento: date | None,
    saldo: Decimal,
    estado_financiero: str,
    fecha_referencia: date,
) -> AnalisisVencimiento:
    if fecha_vencimiento is None:
        return AnalisisVencimiento(CONDICION_SIN_VENCIMIENTO, 0, BUCKET_SIN_VENCIMIENTO)

    if estado_financiero == "ANULADA" or saldo <= 0 or fecha_referencia <= fecha_vencimiento:
        return AnalisisVencimiento(CONDICION_VIGENTE, 0, BUCKET_NO_VENCIDA)

    dias_atraso = (fecha_referencia - fecha_vencimiento).days
    return AnalisisVencimiento(
        condicion=CONDICION_VENCIDA,
        dias_atraso=dias_atraso,
        bucket_antiguedad=clasificar_antiguedad_cartera(dias_atraso),
    )


def clasificar_antiguedad_cartera(dias_atraso: int) -> str:
    if dias_atraso <= 0:
        return BUCKET_NO_VENCIDA
    if dias_atraso <= 30:
        return BUCKET_1_30
    if dias_atraso <= 60:
        return BUCKET_31_60
    if dias_atraso <= 90:
        return BUCKET_61_90
    return BUCKET_MAS_90
