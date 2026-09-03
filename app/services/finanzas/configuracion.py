from app.extensions import db
from app.models.finanzas import ConfiguracionFinanciera
from app.services.finanzas.vencimientos import validar_dia_vencimiento_pension


def obtener_configuracion_financiera(*, academia_id: int, crear: bool = False) -> ConfiguracionFinanciera | None:
    configuracion = ConfiguracionFinanciera.query.filter_by(academia_id=academia_id).first()
    if configuracion is None and crear:
        configuracion = ConfiguracionFinanciera(academia_id=academia_id)
        db.session.add(configuracion)
        db.session.flush()
    return configuracion


def guardar_dia_vencimiento_pension(*, academia_id: int, dia_vencimiento_pension: int | None) -> ConfiguracionFinanciera:
    configuracion = obtener_configuracion_financiera(academia_id=academia_id, crear=True)
    configuracion.dia_vencimiento_pension = validar_dia_vencimiento_pension(dia_vencimiento_pension)
    db.session.flush()
    return configuracion
