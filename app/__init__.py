import os
from flask import Flask, request
from app.extensions import db, login_manager, migrate, csrf

# Blueprints
from app.routes.public import public_bp
from app.routes.alumnos import alumnos_bp
from app.routes.sucursales import sucursales_bp
from app.routes.admin import admin_bp
from app.auth.routes import auth_bp
from app.routes.profile import profile_bp
from app.routes.app_menu import app_menu_bp
from app.routes.pagos import pagos_bp
from app.routes.participaciones import participaciones_bp
from app.routes.torneos import torneos_bp
from app.routes.ranking import ranking_bp
from app.routes.asistencias import asistencias_bp
from app.routes.reportes import reportes_bp
from app.routes.resultados import resultados_bp
from app.routes.academias import academias_bp
from app.routes.examenes import examenes_bp
from app.routes.ascensos import ascensos_bp
from app.routes.banco_preguntas import banco_preguntas_bp
from app.routes.kiosk import kiosk_bp

from app.models import User

# ✅ CLI register (en lugar de importar comandos sueltos)
from app.cli import register_cli

# tenancy hooks (activa listeners)
from app import tenancy_hooks  # noqa: F401


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def create_app():
    app = Flask(__name__)
    app.config.from_object("app.config.Config")

    # 📁 uploads
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads", "alumnos")
    app.config["ACTAS_UPLOAD_FOLDER"] = os.path.join(app.root_path, "static", "uploads", "actas")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    os.makedirs(app.config["ACTAS_UPLOAD_FOLDER"], exist_ok=True)

    # Extensiones
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # -------------------------
    # HEADERS de seguridad
    # -------------------------
    @app.after_request
    def security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.path.startswith("/kiosk/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:; "
                "font-src 'self' data:; "
                "connect-src 'self';"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' https://cdn.jsdelivr.net; "
                "font-src 'self' https://cdn.jsdelivr.net data:; "
                "style-src 'self' https://cdn.jsdelivr.net; "
                "img-src 'self' data:;"
            )
        return response

    # -------------------------
    # CONTEXTO GLOBAL: App + tenant
    # -------------------------
    from flask_login import current_user
    from app.models.academia import Academia

    @app.context_processor
    def inject_app_and_tenant_context():
        app_nombre = "DojoManager"
        app_logo = "img/logoDojoManager.png"

        tenant_nombre = None
        tenant_id = None
        tenant_logo = None
        role_label = None
        sucursal_nombre = None

        try:
            if getattr(current_user, "is_authenticated", False):
                tenant_id = getattr(current_user, "academia_id", None)

                if tenant_id:
                    a = Academia.query.get(tenant_id)
                    if a:
                        tenant_nombre = a.nombre

                if getattr(current_user, "roles", None) and current_user.roles:
                    role_label = current_user.roles[0].name
                else:
                    role_label = "SIN ROL"

                if getattr(current_user, "sucursal", None):
                    sucursal_nombre = current_user.sucursal.nombre
                elif getattr(current_user, "sucursal_id", None):
                    sucursal_nombre = f"Sucursal {current_user.sucursal_id}"
        except Exception:
            pass

        return dict(
            app_nombre=app_nombre,
            app_logo=app_logo,
            tenant_nombre=tenant_nombre,
            tenant_id=tenant_id,
            tenant_logo=tenant_logo,
            role_label=role_label,
            sucursal_nombre=sucursal_nombre,
        )

    # -------------------------
    # Blueprints
    # -------------------------
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(alumnos_bp)
    app.register_blueprint(sucursales_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(app_menu_bp)
    app.register_blueprint(pagos_bp)
    app.register_blueprint(participaciones_bp)
    app.register_blueprint(torneos_bp)
    app.register_blueprint(ranking_bp)
    app.register_blueprint(asistencias_bp)
    app.register_blueprint(reportes_bp)
    app.register_blueprint(resultados_bp)
    app.register_blueprint(academias_bp)
    app.register_blueprint(examenes_bp)
    app.register_blueprint(ascensos_bp)
    app.register_blueprint(banco_preguntas_bp)
    app.register_blueprint(kiosk_bp)
    

    # -------------------------
    # CLI (registra TODOS los comandos del cli.py)
    # -------------------------
    register_cli(app)

    return app
