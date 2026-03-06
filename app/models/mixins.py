from app.extensions import db

class TenantMixin:
    academia_id = db.Column(db.Integer, db.ForeignKey("academias.id"), nullable=False, index=True)