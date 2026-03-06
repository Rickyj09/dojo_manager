from app.extensions import db
from datetime import date 
from sqlalchemy import Enum
from app.models.mixins import TenantMixin

class Alumno(TenantMixin,db.Model):
    __tablename__ = "alumnos"

    id = db.Column(db.Integer, primary_key=True)
    nombres = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(100), nullable=False)
    fecha_nacimiento = db.Column(db.Date, nullable=False)
    genero = db.Column(db.String(1), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    numero_identidad = db.Column(db.String(20), nullable=True)
    fecha_ingreso = db.Column(
        db.Date,
        nullable=True,
        default=date.today
    )
    categoria_id = db.Column(
        db.Integer,
        db.ForeignKey("categorias.id"),
        nullable=False
    )

    # =========================
    # SUCURSAL
    # =========================
    sucursal_id = db.Column(
        db.Integer,
        db.ForeignKey("sucursales.id"),
        nullable=False
    )

    sucursal = db.relationship(
        "Sucursal",
        back_populates="alumnos"
    )

  

    peso = db.Column(db.Numeric(5,2))
    estatura = db.Column(db.Numeric(4,2))
    flexibilidad = db.Column(
        Enum("Baja","Media","Alta", name="flexibilidad_emun"),
        nullable=True
    )
    fecha_ultimo_grado = db.Column(db.Date)
    foto = db.Column(db.String(255))

    # =========================
    # PROFESOR (USER)
    # =========================
    profesor_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True  # para permitir alumnos sin profesor (si lo deseas)
    )

 ##================================
 ##  Grado cinturon
 ##================================

    grado_id = db.Column(
        db.Integer,
        db.ForeignKey("grados.id"),
        nullable=True
    )

    grado = db.relationship("Grado", backref="alumnos")

