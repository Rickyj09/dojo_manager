# app/models/sucursal.py
from app.extensions import db
from app.models.mixins import TenantMixin

class Sucursal(TenantMixin, db.Model):
    __tablename__ = "sucursales"

    id = db.Column(db.Integer, primary_key=True)

    nombre = db.Column(db.String(100), nullable=False)
    direccion = db.Column(db.String(200))
    activo = db.Column(db.Boolean, default=True)

    academia_id = db.Column(
        db.Integer,
        db.ForeignKey("academias.id"),
        nullable=False,
        index=True
    )

    # ✅ Campos públicos (igual que producción)
    resumen_publico = db.Column(db.Text, nullable=True)
    google_maps_url = db.Column(db.String(500), nullable=True)

    foto_1 = db.Column(db.String(255), nullable=True)
    foto_2 = db.Column(db.String(255), nullable=True)
    foto_3 = db.Column(db.String(255), nullable=True)

    facebook_url = db.Column(db.String(255), nullable=True)
    instagram_url = db.Column(db.String(255), nullable=True)
    youtube_url = db.Column(db.String(255), nullable=True)

    whatsapp_numero = db.Column(db.String(20), nullable=True)
    whatsapp_mensaje = db.Column(db.String(255), nullable=True)

    # 🔹 RELACIONES
    alumnos = db.relationship(
        "Alumno",
        back_populates="sucursal",
        cascade="all, delete-orphan"
    )

    academia = db.relationship(
        "Academia",
        back_populates="sucursales"
    )