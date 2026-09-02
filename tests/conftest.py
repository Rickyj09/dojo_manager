from datetime import date
from decimal import Decimal
import os

import pytest

from app import create_app
from app.extensions import db as _db
from app.models.academia import Academia
from app.models.alumno import Alumno
from app.models.categoria import Categoria
from app.models.categoriascompetencia import CategoriaCompetencia
from app.models.grado import Grado
from app.models.medalla import Medalla
from app.models.pago import Pago
from app.models.participacion import Participacion
from app.models.role import Role
from app.models.sucursal import Sucursal
from app.models.torneo import Torneo
from app.models.user import User


@pytest.fixture(scope="session")
def app():
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    test_app = create_app()
    test_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
    )

    with test_app.app_context():
        with test_app.test_request_context():
            _db.create_all()
            yield test_app
            _db.session.remove()
            _db.drop_all()


@pytest.fixture()
def db(app):
    with app.app_context():
        with app.test_request_context():
            yield _db
            _db.session.rollback()
            for table in reversed(_db.metadata.sorted_tables):
                _db.session.execute(table.delete())
            _db.session.commit()


@pytest.fixture()
def base_data(db):
    academia_a = Academia(nombre="Academia A", ciudad="Quito", activo=True)
    academia_b = Academia(nombre="Academia B", ciudad="Guayaquil", activo=True)
    db.session.add_all([academia_a, academia_b])
    db.session.flush()

    admin_role = Role(name="ADMIN", description="Administracion")
    profesor_role = Role(name="PROFESOR", description="Profesor")
    db.session.add_all([admin_role, profesor_role])
    db.session.flush()

    sucursal_a = Sucursal(nombre="Matriz A", academia_id=academia_a.id, activo=True)
    sucursal_b = Sucursal(nombre="Matriz B", academia_id=academia_b.id, activo=True)
    db.session.add_all([sucursal_a, sucursal_b])
    db.session.flush()

    categoria_a = Categoria(nombre="Infantil", academia_id=academia_a.id, orden=1)
    categoria_b = Categoria(nombre="Infantil", academia_id=academia_b.id, orden=1)
    grado_a = Grado(nombre="Blanco", tipo="KUP", orden=1, academia_id=academia_a.id)
    grado_b = Grado(nombre="Blanco", tipo="KUP", orden=1, academia_id=academia_b.id)
    medalla_a = Medalla(nombre="Oro", orden=1, academia_id=academia_a.id)
    db.session.add_all([categoria_a, categoria_b, grado_a, grado_b, medalla_a])
    db.session.flush()

    admin_a = User(
        username="admin_a",
        email="admin_a@example.com",
        academia_id=academia_a.id,
        sucursal_id=sucursal_a.id,
    )
    admin_a.set_password("secret")
    admin_a.roles.append(admin_role)

    admin_b = User(
        username="admin_b",
        email="admin_b@example.com",
        academia_id=academia_b.id,
        sucursal_id=sucursal_b.id,
    )
    admin_b.set_password("secret")
    admin_b.roles.append(admin_role)

    profesor_a = User(
        username="profesor_a",
        email="profesor_a@example.com",
        academia_id=academia_a.id,
        sucursal_id=sucursal_a.id,
    )
    profesor_a.set_password("secret")
    profesor_a.roles.append(profesor_role)
    db.session.add_all([admin_a, admin_b, profesor_a])
    db.session.flush()

    alumno_a1 = Alumno(
        nombres="Carlos",
        apellidos="Perez",
        fecha_nacimiento=date(2012, 5, 10),
        genero="M",
        categoria_id=categoria_a.id,
        sucursal_id=sucursal_a.id,
        academia_id=academia_a.id,
        grado_id=grado_a.id,
    )
    alumno_a2 = Alumno(
        nombres="Maria",
        apellidos="Perez",
        fecha_nacimiento=date(2014, 7, 20),
        genero="F",
        categoria_id=categoria_a.id,
        sucursal_id=sucursal_a.id,
        academia_id=academia_a.id,
        grado_id=grado_a.id,
    )
    alumno_b1 = Alumno(
        nombres="Ana",
        apellidos="Lopez",
        fecha_nacimiento=date(2013, 3, 15),
        genero="F",
        categoria_id=categoria_b.id,
        sucursal_id=sucursal_b.id,
        academia_id=academia_b.id,
        grado_id=grado_b.id,
    )
    db.session.add_all([alumno_a1, alumno_a2, alumno_b1])
    db.session.flush()

    pago_a = Pago(
        academia_id=academia_a.id,
        alumno_id=alumno_a1.id,
        sucursal_id=sucursal_a.id,
        monto=Decimal("60.00"),
        fecha_pago=date(2026, 9, 1),
        mes=9,
        anio=2026,
        metodo="EFECTIVO",
    )

    torneo_a = Torneo(
        academia_id=academia_a.id,
        nombre="Copa Test",
        ciudad="Quito",
        fecha=date(2026, 9, 15),
        precio_poomsae=Decimal("30.00"),
        precio_combate=Decimal("35.00"),
        precio_ambas=Decimal("50.00"),
    )
    db.session.add_all([pago_a, torneo_a])
    db.session.flush()

    categoria_competencia_a = CategoriaCompetencia(
        academia_id=academia_a.id,
        modalidad="COMBATE",
        sexo="M",
        edad_min=10,
        edad_max=14,
        peso_min=0,
        peso_max=80,
        nombre="Combate test",
        activo=True,
    )
    db.session.add(categoria_competencia_a)
    db.session.flush()

    participacion_a = Participacion(
        academia_id=academia_a.id,
        alumno_id=alumno_a1.id,
        torneo_id=torneo_a.id,
        categoria_id=categoria_competencia_a.id,
        modalidad="COMBATE",
        valor_evento=Decimal("35.00"),
        pagado_evento=False,
    )
    db.session.add(participacion_a)
    db.session.commit()

    return {
        "academia_a": academia_a,
        "academia_b": academia_b,
        "admin_a": admin_a,
        "admin_b": admin_b,
        "profesor_a": profesor_a,
        "alumno_a1": alumno_a1,
        "alumno_a2": alumno_a2,
        "alumno_b1": alumno_b1,
        "pago_a": pago_a,
        "torneo_a": torneo_a,
        "participacion_a": participacion_a,
    }
