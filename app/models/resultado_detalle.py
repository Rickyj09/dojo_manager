from app.extensions import db
from app.models.mixins import TenantMixin

class ResultadoDetalle(TenantMixin,db.Model):
    __tablename__ = "resultados_detalle"

    id = db.Column(db.Integer, primary_key=True)

    resultado_categoria_id = db.Column(db.Integer, db.ForeignKey("resultados_categoria.id"), nullable=False)

    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=True)  # puede ser externo

    academia_id = db.Column(db.Integer, db.ForeignKey("academias.id"), nullable=False)

    nombre_competidor = db.Column(db.String(200), nullable=True)  # si es externo o para guardar “tal cual acta”
    puesto = db.Column(db.Integer, nullable=True)

    medalla_id = db.Column(db.Integer, db.ForeignKey("medallas.id"), nullable=True)

    puntaje = db.Column(db.Numeric(6, 2), nullable=True)  # SOLO poomsae

    observacion = db.Column(db.String(255), nullable=True)

    resultado_categoria = db.relationship("ResultadoCategoria", backref="detalles")
    alumno = db.relationship("Alumno")
    academia = db.relationship("Academia")
    medalla = db.relationship("Medalla")