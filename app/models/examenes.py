from app.extensions import db
from app.models.sucursal import Sucursal
from app.models.grado import Grado
from app.models.user import User
from app.models.alumno import Alumno
from app.models.plantillas_examen import PlantillaExamen
from app.models.banco_preguntas import BancoPregunta, PreguntaOpcion


class Examen(db.Model):
    __tablename__ = "examenes"

    id = db.Column(db.Integer, primary_key=True)

    academia_id = db.Column(db.Integer, db.ForeignKey("academias.id"), nullable=False)
    sucursal_id = db.Column(db.Integer, db.ForeignKey(f"{Sucursal.__tablename__}.id"), nullable=True)

    disciplina = db.Column(db.String(30), nullable=False)

    fecha = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=True)
    sede = db.Column(db.String(120), nullable=True)

    grado_objetivo_id = db.Column(db.Integer, db.ForeignKey(f"{Grado.__tablename__}.id"), nullable=False)
    plantilla_id = db.Column(db.Integer, db.ForeignKey(f"{PlantillaExamen.__tablename__}.id"), nullable=True)

    cupos = db.Column(db.Integer, nullable=True)
    costo = db.Column(db.Numeric(10, 2), nullable=True, default=0.00)

    estado = db.Column(
        db.Enum(
            "BORRADOR", "ABIERTO", "CERRADO", "EN_EVALUACION",
            "PENDIENTE_DECISION", "PUBLICADO", "ANULADO",
            name="ex_estado"
        ),
        nullable=False,
        default="BORRADOR"
    )

    # ===== Configuración de componentes del examen =====
    usa_teoria = db.Column(db.Boolean, nullable=False, default=True)
    usa_poomsae = db.Column(db.Boolean, nullable=False, default=True)
    usa_combate = db.Column(db.Boolean, nullable=False, default=True)

    peso_teoria = db.Column(db.Numeric(5, 2), nullable=False, default=30.00)
    peso_poomsae = db.Column(db.Numeric(5, 2), nullable=False, default=40.00)
    peso_combate = db.Column(db.Numeric(5, 2), nullable=False, default=30.00)

    nota_minima_aprobacion = db.Column(db.Numeric(5, 2), nullable=False, default=70.00)

    mostrar_resultado_al_alumno = db.Column(db.Boolean, nullable=False, default=True)
    observaciones = db.Column(db.Text, nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey(f"{User.__tablename__}.id"), nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=db.func.now(), nullable=True)

    evaluadores = db.relationship(
        "ExamenEvaluador",
        backref="examen",
        cascade="all, delete-orphan",
        lazy=True
    )

    inscripciones = db.relationship(
        "ExamenInscripcion",
        back_populates="examen",
        cascade="all, delete-orphan",
        lazy=True
    )


class ExamenEvaluador(db.Model):
    __tablename__ = "examen_evaluadores"

    id = db.Column(db.Integer, primary_key=True)

    academia_id = db.Column(db.Integer, db.ForeignKey("academias.id"), nullable=False)
    examen_id = db.Column(db.Integer, db.ForeignKey(f"{Examen.__tablename__}.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    rol = db.Column(db.Enum("PRINCIPAL", "AUXILIAR", name="ee_rol"), nullable=False, default="AUXILIAR")

    __table_args__ = (
        db.UniqueConstraint("examen_id", "user_id", name="uq_ex_eval"),
    )


class ExamenInscripcion(db.Model):
    __tablename__ = "examen_inscripciones"

    id = db.Column(db.Integer, primary_key=True)

    examen_id = db.Column(
        db.Integer,
        db.ForeignKey(f"{Examen.__tablename__}.id", ondelete="CASCADE"),
        nullable=False
    )

    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False)

    # snapshots
    grado_actual_id = db.Column(db.Integer, db.ForeignKey(f"{Grado.__tablename__}.id"), nullable=False)
    grado_objetivo_id = db.Column(db.Integer, db.ForeignKey(f"{Grado.__tablename__}.id"), nullable=False)

    estado = db.Column(
        db.Enum("INSCRITO", "AUSENTE", "EVALUADO", "APROBADO", "REPROBADO", "PROMOVIDO", name="ei_estado"),
        nullable=False,
        default="INSCRITO"
    )

    # ===== Notas por componente =====
    nota_teoria = db.Column(db.Numeric(6, 2), nullable=True)
    nota_poomsae = db.Column(db.Numeric(6, 2), nullable=True)
    nota_combate = db.Column(db.Numeric(6, 2), nullable=True)
    nota_tecnicas = db.Column(db.Numeric(5, 2), default=0)
    nota_actitud = db.Column(db.Numeric(5, 2), default=0)
    observacion_poomsae = db.Column(db.Text, nullable=True)
    observacion_combate = db.Column(db.Text, nullable=True)

    # Resultado consolidado
    nota_final = db.Column(db.Numeric(6, 2), nullable=True)
    comentario_general = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=db.func.now(), nullable=True)

    examen = db.relationship(
        "Examen",
        back_populates="inscripciones"
    )

    alumno = db.relationship(
        "Alumno",
        backref=db.backref("inscripciones_examen", lazy=True)
    )

    grado_actual = db.relationship(
        "Grado",
        foreign_keys=[grado_actual_id]
    )

    grado_objetivo = db.relationship(
        "Grado",
        foreign_keys=[grado_objetivo_id]
    )

    __table_args__ = (
        db.UniqueConstraint("examen_id", "alumno_id", name="uq_ex_alumno"),
    )


class ExamenAlumno(db.Model):
    __tablename__ = "examen_alumno"

    id = db.Column(db.Integer, primary_key=True)

    examen_id = db.Column(db.Integer, db.ForeignKey(f"{Examen.__tablename__}.id", ondelete="CASCADE"), nullable=False)
    alumno_id = db.Column(db.Integer, db.ForeignKey(f"{Alumno.__tablename__}.id"), nullable=False)

    estado = db.Column(
        db.Enum("PENDIENTE", "EN_PROGRESO", "FINALIZADO", name="ea_estado"),
        nullable=False,
        default="PENDIENTE"
    )

    score_auto = db.Column(db.Numeric(6, 2), nullable=True, default=0.00)
    score_manual = db.Column(db.Numeric(6, 2), nullable=True, default=0.00)
    score_total = db.Column(db.Numeric(6, 2), nullable=True, default=0.00)

    propuesta_resultado = db.Column(
        db.Enum("PROPUESTO_APROBADO", "PROPUESTO_REPROBADO", name="ea_prop"),
        nullable=True
    )
    observacion_evaluadores = db.Column(db.Text, nullable=True)

    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=db.func.now(), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("examen_id", "alumno_id", name="uq_ea_examen_alumno"),
    )

    preguntas = db.relationship(
        "ExamenAlumnoPregunta",
        backref="examen_alumno",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="ExamenAlumnoPregunta.orden"
    )


class ExamenAlumnoPregunta(db.Model):
    __tablename__ = "examen_alumno_preguntas"

    id = db.Column(db.Integer, primary_key=True)

    examen_alumno_id = db.Column(
        db.Integer,
        db.ForeignKey(f"{ExamenAlumno.__tablename__}.id", ondelete="CASCADE"),
        nullable=False
    )

    pregunta_id = db.Column(
        db.Integer,
        db.ForeignKey(f"{BancoPregunta.__tablename__}.id"),
        nullable=False
    )

    evaluador_id = db.Column(
        db.Integer,
        db.ForeignKey(f"{User.__tablename__}.id"),
        nullable=True
    )

    respuesta_texto = db.Column(db.Text, nullable=True)
    respuesta_opcion_id = db.Column(
        db.Integer,
        db.ForeignKey(f"{PreguntaOpcion.__tablename__}.id"),
        nullable=True
    )

    es_correcta = db.Column(db.Boolean, nullable=True)

    puntaje_asignado = db.Column(db.Numeric(6, 2), nullable=True, default=0.00)
    observacion = db.Column(db.Text, nullable=True)

    orden = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=db.func.now(), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("examen_alumno_id", "pregunta_id", name="uq_eap_unica"),
    )


class ExamenDictamen(db.Model):
    __tablename__ = "examen_dictamen"

    id = db.Column(db.Integer, primary_key=True)

    examen_id = db.Column(db.Integer, db.ForeignKey(f"{Examen.__tablename__}.id", ondelete="CASCADE"), nullable=False)
    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False)

    director_user_id = db.Column(db.Integer, db.ForeignKey(f"{User.__tablename__}.id"), nullable=False)

    resultado_final = db.Column(db.Enum("APROBADO", "REPROBADO", name="ed_res"), nullable=False)
    nota_final = db.Column(db.Numeric(6, 2), nullable=True)
    observacion_final = db.Column(db.Text, nullable=True)

    fecha_dictamen = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("examen_id", "alumno_id", name="uq_dictamen"),
    )