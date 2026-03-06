from app.extensions import db
from app.models.mixins import TenantMixin

class Categoria(TenantMixin,db.Model):
    __tablename__ = "categorias"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(30))
    orden = db.Column(db.Integer)

    alumnos = db.relationship("Alumno", backref="categoria", lazy=True)

    def __repr__(self):
        return f"<Categoria {self.nombre}>"
