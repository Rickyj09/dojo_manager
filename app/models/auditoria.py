from app import db
from datetime import datetime
from app.models.mixins import TenantMixin

class Auditoria(TenantMixin, db.Model):
    __tablename__ = 'auditoria'

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, nullable=False)
    usuario_nombre = db.Column(db.String(100), nullable=False)
    accion = db.Column(db.String(50), nullable=False)
    entidad = db.Column(db.String(50), nullable=False)
    entidad_id = db.Column(db.Integer)
    descripcion = db.Column(db.Text)
    datos_antes = db.Column(db.JSON)
    datos_despues = db.Column(db.JSON)
    ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
