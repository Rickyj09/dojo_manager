from app.extensions import db
from datetime import date
from app.models.mixins import TenantMixin

class Pago(TenantMixin,db.Model):
    __tablename__ = "pagos"



    id = db.Column(db.Integer, primary_key=True)

    alumno_id = db.Column(
        db.Integer,
        db.ForeignKey("alumnos.id"),
        nullable=False
    )

    sucursal_id = db.Column(
        db.Integer,
        db.ForeignKey("sucursales.id"),
        nullable=False
    )

    monto = db.Column(db.Numeric(10, 2), nullable=False)

    fecha_pago = db.Column(db.Date, default=date.today, nullable=False)

    mes = db.Column(db.Integer, nullable=False)   # 1-12
    anio = db.Column(db.Integer, nullable=False)

    metodo = db.Column(db.String(30))  # efectivo, transferencia, etc.

    observacion = db.Column(db.String(255))

    # Relaciones
    alumno = db.relationship("Alumno", backref="pagos")
    sucursal = db.relationship("Sucursal", backref="pagos")
    __table_args__ = (
    db.UniqueConstraint("academia_id", "alumno_id", "anio", "mes", name="uq_pago_tenant_alumno_anio_mes"),
    )
