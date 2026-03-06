from app.extensions import db
from app.models.grado import Grado  # si lo usas para FK, no es obligatorio importarlo

class BancoPregunta(db.Model):
    __tablename__ = "banco_preguntas"

    id = db.Column(db.Integer, primary_key=True)
    academia_id = db.Column(db.Integer, db.ForeignKey("academias.id"), nullable=False)
    grado_id = db.Column(db.Integer, db.ForeignKey("grados.id"), nullable=False)

    disciplina = db.Column(db.String(30), nullable=False)  # "TAEKWONDO", "KARATE", etc.

    tipo = db.Column(
        db.Enum("OPCION_MULTIPLE", "VERDADERO_FALSO", "ABIERTA", name="bp_tipo"),
        nullable=False
    )
    enunciado = db.Column(db.Text, nullable=False)

    puntaje_max = db.Column(db.Numeric(5, 2), nullable=False, default=1.00)
    dificultad = db.Column(db.SmallInteger, nullable=True)
    tags = db.Column(db.String(255), nullable=True)

    activo = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=db.func.now(), nullable=True)

    opciones = db.relationship(
        "PreguntaOpcion",
        backref="pregunta",
        cascade="all, delete-orphan",
        lazy=True
    )


class PreguntaOpcion(db.Model):
    __tablename__ = "pregunta_opciones"

    id = db.Column(db.Integer, primary_key=True)
    pregunta_id = db.Column(
        db.Integer,
        db.ForeignKey("banco_preguntas.id", ondelete="CASCADE"),
        nullable=False
    )
    texto = db.Column(db.Text, nullable=False)
    es_correcta = db.Column(db.Boolean, nullable=False, default=False)
    orden = db.Column(db.Integer, nullable=False, default=0)