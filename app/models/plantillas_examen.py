from app.extensions import db


class PlantillaExamen(db.Model):
    __tablename__ = "plantillas_examen"

    id = db.Column(db.Integer, primary_key=True)
    academia_id = db.Column(db.Integer, db.ForeignKey("academias.id"), nullable=False)
    grado_id = db.Column(db.Integer, db.ForeignKey("grados.id"), nullable=False)

    disciplina = db.Column(db.String(30), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)

    modo_seleccion = db.Column(
        db.Enum("FIJA", "ALEATORIA", name="pe_modo"),
        nullable=False,
        default="FIJA"
    )
    num_preguntas = db.Column(db.Integer, nullable=True)

    activo = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=db.func.now(), nullable=True)

    # relación con tabla puente
    preguntas = db.relationship(
        "PlantillaPregunta",
        backref="plantilla",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="PlantillaPregunta.orden"
    )


class PlantillaPregunta(db.Model):
    __tablename__ = "plantilla_preguntas"

    id = db.Column(db.Integer, primary_key=True)

    plantilla_id = db.Column(
        db.Integer,
        db.ForeignKey("plantillas_examen.id", ondelete="CASCADE"),
        nullable=False
    )
    pregunta_id = db.Column(
        db.Integer,
        db.ForeignKey("banco_preguntas.id"),
        nullable=False
    )

    orden = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint("plantilla_id", "pregunta_id", name="uq_plantilla_pregunta"),
    )