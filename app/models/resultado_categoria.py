from app.extensions import db
from datetime import datetime
from app.models.mixins import TenantMixin

class ResultadoCategoria(TenantMixin,db.Model):
    __tablename__ = "resultados_categoria"

    id = db.Column(db.Integer, primary_key=True)

    torneo_id = db.Column(db.Integer, db.ForeignKey("torneos.id"), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey("categorias_competencia.id"), nullable=False)

    modalidad = db.Column(db.String(10), nullable=False)  # POOMSAE / COMBATE

    total_competidores = db.Column(db.Integer, nullable=False, default=0)
    acta_foto = db.Column(db.String(255), nullable=True)
    observacion = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    torneo = db.relationship("Torneo")
    categoria = db.relationship("CategoriaCompetencia")