from app.extensions import db
from app.models.mixins import TenantMixin


class Participacion(TenantMixin,db.Model):
    __tablename__ = "participaciones"

    id = db.Column(db.Integer, primary_key=True)

    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False, index=True)
    torneo_id = db.Column(db.Integer, db.ForeignKey("torneos.id"), nullable=False, index=True)

    categoria_id = db.Column(
        db.Integer,
        db.ForeignKey("categorias_competencia.id"),
        nullable=False,
        index=True
    )

    modalidad = db.Column(db.String(10), nullable=False, index=True)  # POOMSAE / COMBATE
    observacion = db.Column(db.String(255), nullable=True)

    # ===== Resultados (desde actas) =====
    puesto = db.Column(db.Integer, nullable=True)                 # combate: puesto / poomsae: puesto
    puntaje = db.Column(db.Numeric(6, 2), nullable=True)          # solo POOMSAE
    medalla_id = db.Column(db.Integer, db.ForeignKey("medallas.id"), nullable=True)

    # ===== Pago por evento (NO pensión) =====
    valor_evento = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    pagado_evento = db.Column(db.Boolean, nullable=False, default=False)
    fecha_pago_evento = db.Column(db.Date, nullable=True)
    metodo_pago_evento = db.Column(db.String(30), nullable=True)

    # ===== Relaciones =====
    alumno = db.relationship("Alumno", backref="participaciones")
    torneo = db.relationship("Torneo", backref="participaciones")
    medalla = db.relationship("Medalla")
    categoria = db.relationship("CategoriaCompetencia")

    __table_args__ = (
        db.UniqueConstraint(
            "torneo_id", "alumno_id", "modalidad",
            name="uq_participaciones_torneo_alumno_modalidad"
        ),
    )