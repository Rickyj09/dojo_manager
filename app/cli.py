# app/cli.py
import os

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.models.academia import Academia
from app.models.sucursal import Sucursal
from app.models.user import User
from app.models.role import Role

# tu comando existente
from app.models.categoria import Categoria
from app.models.categoriascompetencia import CategoriaCompetencia
from app.services.finanzas import FinanzasError, generar_obligaciones_mensuales, parsear_periodo


ACADEMIA_ADMIN_OBJETIVO = "Borjas Lions"
PASSWORD_ENV_ADMIN_ACADEMIA = "DOJOMANAGER_NEW_USER_PASSWORD"


@click.command("seed-karate-categorias")
@click.option("--academia-id", required=True, type=int)
@with_appcontext
def seed_karate_categorias(academia_id: int):
    # ... tu código actual tal cual ...
    pass


@click.command("seed-academia")
@click.option("--academia", required=True)
@click.option("--ciudad", default="")
@click.option("--sucursal", default="Matriz")
@click.option("--direccion", default="")
@click.option("--username", required=True)
@click.option("--email", required=True)
@click.option("--password", required=True)
@with_appcontext
def seed_academia(academia, ciudad, sucursal, direccion, username, email, password):
    # 1) academia
    a = Academia.query.filter_by(nombre=academia).first()
    if not a:
        a = Academia(nombre=academia, ciudad=ciudad, activo=True)
        db.session.add(a)
        db.session.flush()

    # 2) sucursal
    s = Sucursal.query.filter_by(academia_id=a.id, nombre=sucursal).first()
    if not s:
        s = Sucursal(nombre=sucursal, direccion=direccion, activo=True, academia_id=a.id)
        db.session.add(s)
        db.session.flush()

    # 3) rol superadmin
    r = Role.query.filter_by(name="SUPERADMIN").first()
    if not r:
        r = Role(name="SUPERADMIN", description="Acceso total")
        db.session.add(r)
        db.session.flush()

    # 4) user admin
    u = User.query.filter((User.username == username) | (User.email == email)).first()
    if not u:
        u = User(username=username, email=email, is_active=True, academia_id=a.id, sucursal_id=s.id)
        u.set_password(password)
        db.session.add(u)
        db.session.flush()

    if r not in u.roles:
        u.roles.append(r)

    db.session.commit()
    click.echo(f"✅ OK: academia={a.id}, sucursal={s.id}, admin={u.id} ({u.username})")


def _mostrar_resultado_usuario(usuario: User, creado: bool) -> None:
    """Imprime el resultado del alta sin revelar información sensible."""
    academia = usuario.academia
    roles = ", ".join(sorted(rol.name for rol in usuario.roles)) or "SIN ROL"
    click.echo(f"username: {usuario.username}")
    click.echo(f"user id: {usuario.id}")
    click.echo(f"academia_id: {usuario.academia_id}")
    click.echo(f"academia: {academia.nombre if academia else 'SIN ACADEMIA'}")
    click.echo(f"rol: {roles}")
    click.echo(f"estado: {'activo' if usuario.is_active else 'inactivo'}")
    click.echo(f"resultado: {'creado' if creado else 'ya existía'}")


@click.command("crear-admin-academia")
@click.option("--academia", "academia_nombre", required=True)
@click.option("--username", required=True)
@click.option("--email", required=True)
@with_appcontext
def crear_admin_academia(academia_nombre: str, username: str, email: str):
    """Crea de forma idempotente un ADMIN para una academia ya existente."""
    username = username.strip()
    email = email.strip()
    academia_nombre = academia_nombre.strip()

    if academia_nombre != ACADEMIA_ADMIN_OBJETIVO:
        raise click.ClickException(
            f"Este comando solo permite la academia '{ACADEMIA_ADMIN_OBJETIVO}'. "
            "No se realizó ningún cambio."
        )

    usuario = User.query.filter_by(username=username).first()
    if usuario:
        _mostrar_resultado_usuario(usuario, creado=False)
        return

    academia = Academia.query.filter_by(nombre=academia_nombre).first()
    if not academia:
        raise click.ClickException(
            f"No existe la academia '{academia_nombre}'. No se realizó ningún cambio."
        )

    rol_admin = Role.query.filter_by(name="ADMIN").first()
    if not rol_admin:
        raise click.ClickException(
            "No existe el rol ADMIN. No se realizó ningún cambio."
        )

    usuario_con_email = User.query.filter_by(email=email).first()
    if usuario_con_email:
        raise click.ClickException(
            f"El email '{email}' ya pertenece al usuario "
            f"'{usuario_con_email.username}'. No se realizó ningún cambio."
        )

    password = os.environ.get(PASSWORD_ENV_ADMIN_ACADEMIA)
    if not password:
        raise click.ClickException(
            f"La variable de entorno {PASSWORD_ENV_ADMIN_ACADEMIA} no está definida "
            "o está vacía. "
            "No se realizó ningún cambio."
        )

    usuario = User(
        username=username,
        email=email,
        is_active=True,
        academia_id=academia.id,
    )
    usuario.set_password(password)
    usuario.roles.append(rol_admin)
    db.session.add(usuario)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    _mostrar_resultado_usuario(usuario, creado=True)


@click.group("finanzas")
def finanzas_cli():
    """Comandos financieros."""


@finanzas_cli.command("generar-pensiones")
@click.option("--academia-id", required=True, type=int)
@click.option("--periodo", required=True)
@with_appcontext
def generar_pensiones(academia_id: int, periodo: str):
    try:
        parsear_periodo(periodo)
        resumen = generar_obligaciones_mensuales(academia_id=academia_id, periodo=periodo)
        db.session.commit()
    except FinanzasError as exc:
        db.session.rollback()
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Periodo: {resumen.periodo}")
    click.echo(f"Academia: {resumen.academia_id}")
    click.echo(f"Alumnos evaluados: {resumen.evaluados}")
    click.echo(f"Obligaciones creadas: {resumen.creados}")
    click.echo(f"Ya existentes: {resumen.existentes}")
    click.echo(f"Sin plan financiero: {resumen.sin_plan}")
    click.echo(f"Errores: {len(resumen.errores)}")
    for error in resumen.errores:
        click.echo(f"- Alumno {error['alumno_id']}: {error['error']}")


def register_cli(app):
    app.cli.add_command(seed_karate_categorias)
    app.cli.add_command(seed_academia)
    app.cli.add_command(crear_admin_academia)
    app.cli.add_command(finanzas_cli)
