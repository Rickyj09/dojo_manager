from flask_login import current_user

def tenant_query(Model):
    return Model.query.filter_by(academia_id=current_user.academia_id)