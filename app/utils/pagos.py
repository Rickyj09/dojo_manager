from datetime import date
from app.models.pago import Pago

def _meses_entre(inicio: date, fin: date):
    """Cantidad de meses calendario entre inicio y fin (incluye ambos meses)."""
    return (fin.year - inicio.year) * 12 + (fin.month - inicio.month) + 1

def _iter_meses(inicio: date, fin: date):
    """Itera (anio, mes) desde inicio hasta fin, inclusive."""
    y, m = inicio.year, inicio.month
    while (y < fin.year) or (y == fin.year and m <= fin.month):
        yield (y, m)
        m += 1
        if m == 13:
            m = 1
            y += 1

from datetime import date
from app.models.pago import Pago

def _iter_meses(inicio: date, fin: date):
    """Itera (anio, mes) desde inicio hasta fin (inclusive)."""
    y, m = inicio.year, inicio.month
    while (y < fin.year) or (y == fin.year and m <= fin.month):
        yield (y, m)
        m += 1
        if m == 13:
            m = 1
            y += 1

def calcular_deuda(alumno, academia_id: int):
    hoy = date.today()

    # Fecha de inicio de cobro (si existe)
    fecha_inicio = getattr(alumno, "fecha_ingreso", None) or hoy
    if isinstance(fecha_inicio, str):
        fecha_inicio = date.fromisoformat(fecha_inicio)

    # Pagos del tenant
    pagos = (
        Pago.query
        .filter_by(academia_id=academia_id, alumno_id=alumno.id)
        .all()
    )
    pagados_set = {(p.anio, p.mes) for p in pagos}

    meses_total = list(_iter_meses(fecha_inicio, hoy))

    pendientes = []
    for (anio, mes) in meses_total:
        if (anio, mes) not in pagados_set:
            pendientes.append({"anio": anio, "mes": mes})

    total_meses = len(meses_total)
    cantidad_pendientes = len(pendientes)
    pagados = total_meses - cantidad_pendientes

    return {
        "total_meses": total_meses,
        "pagados": pagados,
        "cantidad_pendientes": cantidad_pendientes,
        "pendientes": pendientes[-12:],  # último 12 para no llenar la pantalla
    }