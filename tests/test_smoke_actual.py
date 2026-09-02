from decimal import Decimal

from app.models.academia import Academia
from app.models.alumno import Alumno
from app.models.pago import Pago
from app.models.participacion import Participacion
from app.models.torneo import Torneo
from app.models.user import User


def test_app_inicia_en_modo_testing(app):
    assert app.config["TESTING"] is True
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"


def test_usuario_puede_asociarse_a_academia(base_data):
    assert base_data["admin_a"].academia_id == base_data["academia_a"].id
    assert base_data["admin_b"].academia_id == base_data["academia_b"].id


def test_alumno_pertenece_a_academia(base_data):
    alumno = base_data["alumno_a1"]
    assert alumno.academia_id == base_data["academia_a"].id
    assert alumno.sucursal.academia_id == base_data["academia_a"].id


def test_aislamiento_basico_academia_a_y_b(db, base_data):
    alumnos_a = Alumno.query.filter_by(academia_id=base_data["academia_a"].id).all()
    alumnos_b = Alumno.query.filter_by(academia_id=base_data["academia_b"].id).all()

    assert {alumno.id for alumno in alumnos_a} == {
        base_data["alumno_a1"].id,
        base_data["alumno_a2"].id,
    }
    assert {alumno.id for alumno in alumnos_b} == {base_data["alumno_b1"].id}


def test_modelos_actuales_principales_pueden_crearse(db, base_data):
    assert Academia.query.count() == 2
    assert User.query.count() == 3
    assert Alumno.query.count() == 3


def test_pago_actual_puede_persistirse(base_data):
    pago = base_data["pago_a"]

    assert pago.id is not None
    assert pago.monto == Decimal("60.00")
    assert pago.mes == 9
    assert pago.anio == 2026


def test_torneo_y_participacion_actuales_pueden_persistirse(base_data):
    torneo = base_data["torneo_a"]
    participacion = base_data["participacion_a"]

    assert Torneo.query.filter_by(id=torneo.id).one().precio_combate == Decimal("35.00")
    assert Participacion.query.filter_by(id=participacion.id).one().valor_evento == Decimal("35.00")
    assert participacion.alumno_id == base_data["alumno_a1"].id
