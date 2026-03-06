from app.extensions import db
from app.models.academia import Academia
from app.models.alumno import Alumno
from app.models.grado import Grado
from app.models.user import User
from app.models.examenes import Examen


class Ascenso(db.Model):
    __tablename__ = "ascensos"

    id = db.Column(db.Integer, primary_key=True)
    academia_id = db.Column(db.Integer, db.ForeignKey("academias.id"), nullable=False)

    alumno_id = db.Column(db.Integer, db.ForeignKey("alumnos.id"), nullable=False)

    fecha = db.Column(db.Date, nullable=False)

    # ✅ deben ser Integer porque grados.id es INT
    grado_anterior_id = db.Column(db.Integer, db.ForeignKey(f"{Grado.__tablename__}.id"), nullable=False)
    grado_nuevo_id = db.Column(db.Integer, db.ForeignKey(f"{Grado.__tablename__}.id"), nullable=False)

    origen = db.Column(db.Enum("EXAMEN", "MANUAL", name="as_origen"), nullable=False, default="EXAMEN")

    # ✅ debe ser Integer porque examenes.id es INT
    examen_id = db.Column(db.Integer, db.ForeignKey(f"{Examen.__tablename__}.id"), nullable=True)

    observacion = db.Column(db.Text, nullable=True)

    # ✅ debe ser Integer porque users.id es INT
    created_by = db.Column(db.Integer, db.ForeignKey(f"{User.__tablename__}.id"), nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)