from datetime import date

import pytest

from app.models.finanzas import PagoFinanciero
from app.models.role import Role
from app.models.sucursal import Sucursal
from app.models.user import User
from app.services.finanzas.pagos import registrar_pago


def login(client, user):
    response = client.post(
        "/auth/login",
        data={"username": user.username, "password": "secret"},
    )
    assert response.status_code == 302


def crear_usuario(db, *, base_data, username, rol, academia_key="academia_a", sucursal_id=None):
    academia = base_data[academia_key]
    role = Role.query.filter_by(name=rol).first()
    if role is None:
        role = Role(name=rol, description=rol)
        db.session.add(role)
        db.session.flush()
    usuario = User(
        username=username,
        email=f"{username}@example.com",
        academia_id=academia.id,
        sucursal_id=sucursal_id or base_data["admin_a"].sucursal_id,
    )
    usuario.set_password("secret")
    usuario.roles.append(role)
    db.session.add(usuario)
    db.session.commit()
    return usuario


@pytest.mark.parametrize("rol", ["ADMIN", "SUPERADMIN"])
def test_roles_administrativos_pueden_acceder_a_cartera(app, db, base_data, rol):
    usuario = base_data["admin_a"]
    if rol == "SUPERADMIN":
        usuario.roles = [Role(name="SUPERADMIN", description="Acceso total")]
        db.session.commit()
    client = app.test_client()
    login(client, usuario)

    response = client.get("/finanzas/cartera")

    assert response.status_code == 200
    assert b"Cartera financiera" in response.data


@pytest.mark.parametrize("rol", ["COACH", "MONITOR"])
def test_roles_sin_permiso_financiero_no_acceden_ni_ven_menu(app, db, base_data, rol):
    usuario = crear_usuario(db, base_data=base_data, username=rol.lower(), rol=rol)
    client = app.test_client()
    login(client, usuario)

    cartera = client.get("/finanzas/cartera")
    configuracion = client.get("/finanzas/configuracion")
    dashboard = client.get("/admin/")

    assert cartera.status_code == 403
    assert configuracion.status_code == 403
    assert b"Finanzas" not in dashboard.data


def test_navegacion_financiera_muestra_solo_opciones_implementadas(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get("/admin/")

    assert response.status_code == 200
    assert b"Finanzas" in response.data
    assert b"Operaci" in response.data
    assert b"Cartera" in response.data
    assert b"Configuraci" in response.data
    assert b"Pol" in response.data
    assert b"Planes financieros" in response.data
    assert b"Frecuencias" in response.data
    assert b"Tarifarios" in response.data
    assert b"Generar pensiones" not in response.data


def test_profesor_lectura_sucursal_y_menu_sin_administracion(app, db, base_data):
    sucursal_secundaria = Sucursal(
        nombre="Sucursal secundaria A",
        academia_id=base_data["academia_a"].id,
        activo=True,
    )
    db.session.add(sucursal_secundaria)
    db.session.commit()
    client = app.test_client()
    login(client, base_data["profesor_a"])

    cartera = client.get("/finanzas/cartera")
    configuracion = client.get("/finanzas/configuracion")
    alumno_ajeno_sucursal = client.get(
        f"/finanzas/alumnos/{base_data['alumno_a1'].id}/estado-cuenta"
    )

    assert cartera.status_code == 200
    assert configuracion.status_code == 403
    assert alumno_ajeno_sucursal.status_code == 200
    assert b"Pol" not in cartera.data
    assert sucursal_secundaria.id != base_data["profesor_a"].sucursal_id


def test_profesor_no_puede_consultar_alumno_de_otra_sucursal(app, db, base_data):
    sucursal_secundaria = Sucursal(
        nombre="Sucursal secundaria A",
        academia_id=base_data["academia_a"].id,
        activo=True,
    )
    db.session.add(sucursal_secundaria)
    db.session.flush()
    alumno = base_data["alumno_a2"]
    alumno.sucursal_id = sucursal_secundaria.id
    db.session.commit()
    client = app.test_client()
    login(client, base_data["profesor_a"])

    response = client.get(f"/finanzas/alumnos/{alumno.id}/estado-cuenta")

    assert response.status_code == 403


def test_tenant_no_puede_consultar_pago_financiero_de_otra_academia(app, db, base_data):
    pago = registrar_pago(
        academia_id=base_data["academia_b"].id,
        alumno_id=base_data["alumno_b1"].id,
        fecha_pago=date(2026, 9, 7),
        valor="25.00",
        medio_pago="EFECTIVO",
    )
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/pagos/{pago.id}")

    assert response.status_code == 404


def test_post_financiero_sin_csrf_es_rechazado(app, db, base_data, monkeypatch):
    pago_antes = PagoFinanciero.query.count()
    client = app.test_client()
    login(client, base_data["admin_a"])
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)

    response = client.post(
        f"/finanzas/alumnos/{base_data['alumno_a1'].id}/pagos/nuevo",
        data={
            "fecha_pago": "2026-09-07",
            "valor": "25.00",
            "moneda": "USD",
            "medio_pago": "EFECTIVO",
        },
    )

    assert response.status_code == 400
    assert PagoFinanciero.query.count() == pago_antes
