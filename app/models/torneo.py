from app.extensions import db
from app.models.mixins import TenantMixin

class Torneo(TenantMixin,db.Model):
    __tablename__ = "torneos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    ciudad = db.Column(db.String(100))
    fecha = db.Column(db.Date, nullable=False)
    organizador = db.Column(db.String(100))
    activo = db.Column(db.Boolean, default=True)

    # === NUEVO: costos por evento ===
    precio_poomsae = db.Column(db.Numeric(10, 2), nullable=False, default=30)
    precio_combate = db.Column(db.Numeric(10, 2), nullable=False, default=30)

    # si participa en ambas (POOMSAE+COMBATE), valor final total
    # (ej: 35 o 40 según evento)
    precio_ambas = db.Column(db.Numeric(10, 2), nullable=False, default=40)