from app.extensions import db
from app.models.mixins import TenantMixin

class Medalla(TenantMixin,db.Model):
    __tablename__ = "medallas"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(20), nullable=False)  # Oro, Plata, Bronce
    orden = db.Column(db.Integer, nullable=False)
    color = db.Column(db.String(20))
