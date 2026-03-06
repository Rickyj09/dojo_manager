from app.extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
)

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    # ✅ NUEVO: tenant (academia)
    academia_id = db.Column(
        db.Integer,
        db.ForeignKey("academias.id"),
        nullable=True,   # MVP: puedes dejarlo True si tendrás superadmin global
        index=True
    )
    academia = db.relationship("Academia", backref="users")

    # 🔹 sucursal asignada (sucursal ya tendrá academia_id por el TenantMixin)
    sucursal_id = db.Column(
        db.Integer,
        db.ForeignKey("sucursales.id"),
        nullable=True
    )
    sucursal = db.relationship("Sucursal", backref="profesores")

    roles = db.relationship(
        "Role",
        secondary=user_roles,
        back_populates="users"
    )

    must_change_password = db.Column(db.Boolean, default=False)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def has_role(self, role_name: str) -> bool:
        return any(role.name == role_name for role in self.roles)

    @property
    def is_superadmin(self) -> bool:
        # Ajusta el nombre del rol si usas otro (ej: "ADMIN", "SUPERADMIN", etc.)
        return self.has_role("SUPERADMIN")