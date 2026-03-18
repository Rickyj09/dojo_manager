from app.extensions import db
from app.models.mixins import TenantMixin


class CategoriaCompetencia(TenantMixin, db.Model):
    __tablename__ = "categorias_competencia"

    id = db.Column(db.Integer, primary_key=True)

    modalidad = db.Column(db.String(10), nullable=False)  # POOMSAE / COMBATE
    sexo = db.Column(db.String(1), nullable=False)        # M / F

    edad_min = db.Column(db.Integer, nullable=False)
    edad_max = db.Column(db.Integer, nullable=False)

    peso_min = db.Column(db.Float)   # NULL para POOMSAE
    peso_max = db.Column(db.Float)   # NULL para POOMSAE

    # legado
    grado_id = db.Column(db.Integer, nullable=True)

    # nuevo rango de grados para poomsae
    grado_min_id = db.Column(db.Integer, db.ForeignKey("grados.id"), nullable=True)
    grado_max_id = db.Column(db.Integer, db.ForeignKey("grados.id"), nullable=True)

    grado_min = db.relationship("Grado", foreign_keys=[grado_min_id])
    grado_max = db.relationship("Grado", foreign_keys=[grado_max_id])

    nombre = db.Column(db.String(100), nullable=False)
    activo = db.Column(db.Boolean, default=True)