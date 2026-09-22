# app/cli.py
import os

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.models.academia import Academia
from app.models.sucursal import Sucursal
from app.models.user import User
from app.models.role import Role

from app.models.categoria import Categoria
from app.models.categoriascompetencia import CategoriaCompetencia

from app.services.finanzas import (
    FinanzasError,
    generar_obligaciones_mensuales,
    parsear_periodo,
)

from app.services.catalogos_competencia import (
    asegurar_categorias_competencia_base,
)


ACADEMIA_ADMIN_OBJETIVO = "Borjas Lions"
PASSWORD_ENV_ADMIN_ACADEMIA = "DOJOMANAGER_NEW_USER_PASSWORD"


# ============================================================
# SEED CATEGORÍAS DE COMPETENCIA
# ============================================================

@click.command("seed-karate-categorias")
@click.option("--academia-id", required=True, type=int)
@with_appcontext
def seed_karate_categorias(academia_id: int):
    """
    Carga/repara de forma idempotente el catálogo base
    de categorías de competencia para una academia.
    """

    academia = db.session.get(Academia, academia_id)

    if not academia:
        raise click.ClickException(
            f"No existe una academia con id={academia_id}."
        )

    try:
        resultado = asegurar_categorias_competencia_base(
            academia_id
        )

        db.session.commit()

    except Exception as exc:
        db.session.rollback()

        raise click.ClickException(
            f"No fue posible cargar las categorías: {exc}"
        ) from exc

    click.echo("")
    click.echo("✅ Catálogo de categorías procesado correctamente.")
    click.echo(f"Academia ID: {academia.id}")
    click.echo(f"Academia: {academia.nombre}")
    click.echo(
        f"Categorías creadas: "
        f"{resultado.get('creadas', 0)}"
    )
    click.echo(
        f"Categorías actualizadas: "
        f"{resultado.get('actualizadas', 0)}"
    )
    click.echo(
        f"Sin cambios: "
        f"{resultado.get('sin_cambios', 0)}"
    )
    click.echo(
        f"Total catálogo base: "
        f"{resultado.get('total_catalogo', 0)}"
    )


# ============================================================
# CREACIÓN / REPARACIÓN DE ACADEMIA
# ============================================================

@click.command("seed-academia")
@click.option("--academia", required=True)
@click.option("--ciudad", default="")
@click.option("--sucursal", default="Matriz")
@click.option("--direccion", default="")
@click.option("--username", required=True)
@click.option("--email", required=True)
@click.option("--password", required=True)
@with_appcontext
def seed_academia(
    academia,
    ciudad,
    sucursal,
    direccion,
    username,
    email,
    password,
):
    """
    Crea o repara una academia base.

    Incluye:
    - academia;
    - catálogo de categorías de competencia;
    - sucursal;
    - rol SUPERADMIN;
    - usuario administrador.

    La carga de categorías es idempotente.
    """

    try:

        # ====================================================
        # 1) ACADEMIA
        # ====================================================

        a = Academia.query.filter_by(
            nombre=academia
        ).first()

        academia_creada = False

        if not a:
            a = Academia(
                nombre=academia,
                ciudad=ciudad,
                activo=True,
            )

            db.session.add(a)
            db.session.flush()

            academia_creada = True

        # ====================================================
        # 2) CATÁLOGO DE CATEGORÍAS DE COMPETENCIA
        # ====================================================
        #
        # Se ejecuta tanto para academias nuevas como existentes.
        #
        # Esto permite:
        # - crear las 192 categorías si faltan;
        # - reparar una academia antigua;
        # - ejecutar seed-academia varias veces sin duplicarlas.
        # ====================================================

        resultado_categorias = (
            asegurar_categorias_competencia_base(
                a.id
            )
        )

        # ====================================================
        # 3) SUCURSAL
        # ====================================================

        s = Sucursal.query.filter_by(
            academia_id=a.id,
            nombre=sucursal,
        ).first()

        if not s:
            s = Sucursal(
                nombre=sucursal,
                direccion=direccion,
                activo=True,
                academia_id=a.id,
            )

            db.session.add(s)
            db.session.flush()

        # ====================================================
        # 4) ROL SUPERADMIN
        # ====================================================

        r = Role.query.filter_by(
            name="SUPERADMIN"
        ).first()

        if not r:
            r = Role(
                name="SUPERADMIN",
                description="Acceso total",
            )

            db.session.add(r)
            db.session.flush()

        # ====================================================
        # 5) USUARIO ADMINISTRADOR
        # ====================================================

        u = User.query.filter(
            (User.username == username)
            | (User.email == email)
        ).first()

        if not u:
            u = User(
                username=username,
                email=email,
                is_active=True,
                academia_id=a.id,
                sucursal_id=s.id,
            )

            u.set_password(password)

            db.session.add(u)
            db.session.flush()

        if r not in u.roles:
            u.roles.append(r)

        # ====================================================
        # COMMIT ÚNICO
        # ====================================================

        db.session.commit()

    except Exception as exc:
        db.session.rollback()

        raise click.ClickException(
            f"No fue posible completar seed-academia: {exc}"
        ) from exc

    # ========================================================
    # RESULTADO
    # ========================================================

    click.echo("")
    click.echo("✅ Academia procesada correctamente.")

    click.echo(
        f"Academia: {a.nombre} "
        f"(id={a.id})"
    )

    click.echo(
        "Estado academia: "
        + (
            "creada"
            if academia_creada
            else "ya existente"
        )
    )

    click.echo(
        f"Sucursal: {s.nombre} "
        f"(id={s.id})"
    )

    click.echo(
        f"Admin: {u.username} "
        f"(id={u.id})"
    )

    click.echo("")
    click.echo("Categorías de competencia:")

    click.echo(
        f"  creadas: "
        f"{resultado_categorias.get('creadas', 0)}"
    )

    click.echo(
        f"  actualizadas: "
        f"{resultado_categorias.get('actualizadas', 0)}"
    )

    click.echo(
        f"  sin cambios: "
        f"{resultado_categorias.get('sin_cambios', 0)}"
    )

    click.echo(
        f"  total catálogo: "
        f"{resultado_categorias.get('total_catalogo', 0)}"
    )


# ============================================================
# UTILIDAD MOSTRAR USUARIO
# ============================================================

def _mostrar_resultado_usuario(
    usuario: User,
    creado: bool,
) -> None:
    """Imprime el resultado del alta sin revelar información sensible."""

    academia = usuario.academia

    roles = (
        ", ".join(
            sorted(
                rol.name
                for rol in usuario.roles
            )
        )
        or "SIN ROL"
    )

    click.echo(
        f"username: {usuario.username}"
    )

    click.echo(
        f"user id: {usuario.id}"
    )

    click.echo(
        f"academia_id: {usuario.academia_id}"
    )

    click.echo(
        f"academia: "
        f"{academia.nombre if academia else 'SIN ACADEMIA'}"
    )

    click.echo(
        f"rol: {roles}"
    )

    click.echo(
        f"estado: "
        f"{'activo' if usuario.is_active else 'inactivo'}"
    )

    click.echo(
        f"resultado: "
        f"{'creado' if creado else 'ya existía'}"
    )


# ============================================================
# CREAR ADMIN PARA BORJAS LIONS
# ============================================================

@click.command("crear-admin-academia")
@click.option(
    "--academia",
    "academia_nombre",
    required=True,
)
@click.option(
    "--username",
    required=True,
)
@click.option(
    "--email",
    required=True,
)
@with_appcontext
def crear_admin_academia(
    academia_nombre: str,
    username: str,
    email: str,
):
    """
    Crea de forma idempotente un ADMIN
    para una academia ya existente.
    """

    username = username.strip()
    email = email.strip()
    academia_nombre = academia_nombre.strip()

    if academia_nombre != ACADEMIA_ADMIN_OBJETIVO:
        raise click.ClickException(
            f"Este comando solo permite la academia "
            f"'{ACADEMIA_ADMIN_OBJETIVO}'. "
            "No se realizó ningún cambio."
        )

    usuario = User.query.filter_by(
        username=username
    ).first()

    if usuario:
        _mostrar_resultado_usuario(
            usuario,
            creado=False,
        )
        return

    academia = Academia.query.filter_by(
        nombre=academia_nombre
    ).first()

    if not academia:
        raise click.ClickException(
            f"No existe la academia "
            f"'{academia_nombre}'. "
            "No se realizó ningún cambio."
        )

    rol_admin = Role.query.filter_by(
        name="ADMIN"
    ).first()

    if not rol_admin:
        raise click.ClickException(
            "No existe el rol ADMIN. "
            "No se realizó ningún cambio."
        )

    usuario_con_email = User.query.filter_by(
        email=email
    ).first()

    if usuario_con_email:
        raise click.ClickException(
            f"El email '{email}' ya pertenece "
            f"al usuario "
            f"'{usuario_con_email.username}'. "
            "No se realizó ningún cambio."
        )

    password = os.environ.get(
        PASSWORD_ENV_ADMIN_ACADEMIA
    )

    if not password:
        raise click.ClickException(
            f"La variable de entorno "
            f"{PASSWORD_ENV_ADMIN_ACADEMIA} "
            "no está definida o está vacía. "
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

    _mostrar_resultado_usuario(
        usuario,
        creado=True,
    )


# ============================================================
# FINANZAS
# ============================================================

@click.group("finanzas")
def finanzas_cli():
    """Comandos financieros."""


@finanzas_cli.command("generar-pensiones")
@click.option(
    "--academia-id",
    required=True,
    type=int,
)
@click.option(
    "--periodo",
    required=True,
)
@with_appcontext
def generar_pensiones(
    academia_id: int,
    periodo: str,
):
    try:
        parsear_periodo(periodo)

        resumen = generar_obligaciones_mensuales(
            academia_id=academia_id,
            periodo=periodo,
        )

        db.session.commit()

    except FinanzasError as exc:
        db.session.rollback()

        raise click.ClickException(
            str(exc)
        ) from exc

    click.echo(
        f"Periodo: {resumen.periodo}"
    )

    click.echo(
        f"Academia: {resumen.academia_id}"
    )

    click.echo(
        f"Alumnos evaluados: "
        f"{resumen.evaluados}"
    )

    click.echo(
        f"Obligaciones creadas: "
        f"{resumen.creados}"
    )

    click.echo(
        f"Ya existentes: "
        f"{resumen.existentes}"
    )

    click.echo(
        f"Sin plan financiero: "
        f"{resumen.sin_plan}"
    )

    click.echo(
        f"Errores: "
        f"{len(resumen.errores)}"
    )

    for error in resumen.errores:
        click.echo(
            f"- Alumno "
            f"{error['alumno_id']}: "
            f"{error['error']}"
        )


# ============================================================
# REGISTRO CLI
# ============================================================

def register_cli(app):
    app.cli.add_command(
        seed_karate_categorias
    )

    app.cli.add_command(
        seed_academia
    )

    app.cli.add_command(
        crear_admin_academia
    )

    app.cli.add_command(
        finanzas_cli
    )