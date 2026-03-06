from datetime import date, datetime
from app.extensions import db
from app.models.mixins import TenantMixin

class Asistencia(TenantMixin, db.Model):
    __tablename__ = "asistencias"

    id = db.Column(db.Integer, primary_key=True)

    fecha = db.Column(db.Date, nullable=False, default=date.today)

    # Relaciones principales
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey("sucursales.id"), nullable=False)

    # Quién registró
    registrado_por_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Estado (simple y práctico)
    # P = Presente, A = Ausente, T = Tarde, J = Justificado
    estado = db.Column(db.String(1), nullable=False, default="P")

    observacion = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("fecha", "alumno_id", "sucursal_id", name="uq_asistencia_fecha_alumno_sucursal"),
        db.Index("ix_asistencias_fecha_sucursal", "fecha", "sucursal_id"),
    )
