from flask_login import current_user
from sqlalchemy import event
from app.extensions import db
from app.models.mixins import TenantMixin

@event.listens_for(db.session, "before_flush")
def tenancy_before_flush(session, flush_context, instances):
    if not current_user or not getattr(current_user, "is_authenticated", False):
        return
    if not getattr(current_user, "academia_id", None):
        return

    # SET en nuevos
    for obj in session.new:
        if isinstance(obj, TenantMixin) and getattr(obj, "academia_id", None) is None:
            obj.academia_id = current_user.academia_id

    # BLOQUEO cross-tenant
    for obj in session.dirty:
        if isinstance(obj, TenantMixin):
            if obj.academia_id != current_user.academia_id:
                raise ValueError("Operación cross-tenant bloqueada")