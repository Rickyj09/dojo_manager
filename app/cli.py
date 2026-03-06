# app/cli.py
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


def register_cli(app):
    app.cli.add_command(seed_karate_categorias)
    app.cli.add_command(seed_academia)