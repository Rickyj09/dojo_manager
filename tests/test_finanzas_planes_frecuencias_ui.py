from app.models.finanzas import FrecuenciaEntrenamiento, PlanFinanciero
from app.models.role import Role
from app.models.user import User


def login(client, user):
    response = client.post("/auth/login", data={"username": user.username, "password": "secret"})
    assert response.status_code == 302


def crear_usuario(db, base_data, rol):
    role = Role.query.filter_by(name=rol).first()
    if role is None:
        role = Role(name=rol, description=rol)
        db.session.add(role)
        db.session.flush()
    user = User(
        username=f"{rol.lower()}_finanzas",
        email=f"{rol.lower()}_finanzas@example.com",
        academia_id=base_data["academia_a"].id,
        sucursal_id=base_data["admin_a"].sucursal_id,
    )
    user.set_password("secret")
    user.roles.append(role)
    db.session.add(user)
    db.session.commit()
    return user


def crear_plan(db, academia_id, codigo="REGULAR"):
    plan = PlanFinanciero(academia_id=academia_id, codigo=codigo, nombre=f"Plan {codigo}", orden=1)
    db.session.add(plan)
    db.session.commit()
    return plan


def crear_frecuencia(db, academia_id, codigo="D3"):
    frecuencia = FrecuenciaEntrenamiento(
        academia_id=academia_id, codigo=codigo, nombre=f"Frecuencia {codigo}", dias_semana=3
    )
    db.session.add(frecuencia)
    db.session.commit()
    return frecuencia


def test_admin_lista_solo_planes_de_su_academia(app, db, base_data):
    crear_plan(db, base_data["academia_a"].id, "A")
    crear_plan(db, base_data["academia_b"].id, "B")
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get("/finanzas/planes")

    assert response.status_code == 200
    assert b"Plan A" in response.data
    assert b"Plan B" not in response.data


def test_admin_crea_y_edita_plan(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    crear = client.post("/finanzas/planes/nuevo", data={"codigo": "regular", "nombre": "Regular", "orden": "2"})
    plan = PlanFinanciero.query.filter_by(academia_id=base_data["academia_a"].id, codigo="REGULAR").one()
    editar = client.post(
        f"/finanzas/planes/{plan.id}/editar",
        data={"codigo": "regular_plus", "nombre": "Regular Plus", "objetivo": "Formación", "orden": "3"},
    )

    assert crear.status_code == 302
    assert editar.status_code == 302
    assert plan.codigo == "REGULAR_PLUS"
    assert plan.nombre == "Regular Plus"
    assert plan.objetivo == "Formación"
    assert plan.orden == 3


def test_plan_de_otro_tenant_no_se_consulta_ni_modifica(app, db, base_data):
    plan = crear_plan(db, base_data["academia_b"].id)
    client = app.test_client()
    login(client, base_data["admin_a"])

    get_response = client.get(f"/finanzas/planes/{plan.id}/editar")
    post_response = client.post(f"/finanzas/planes/{plan.id}/editar", data={"codigo": "CAMBIO", "nombre": "Cambio", "orden": "0"})

    assert get_response.status_code == 404
    assert post_response.status_code == 404
    assert db.session.get(PlanFinanciero, plan.id).codigo == "REGULAR"


def test_superadmin_administra_plan(app, db, base_data):
    user = crear_usuario(db, base_data, "SUPERADMIN")
    client = app.test_client()
    login(client, user)

    response = client.post("/finanzas/planes/nuevo", data={"codigo": "SUPER", "nombre": "Plan super", "orden": "0"})

    assert response.status_code == 302
    assert PlanFinanciero.query.filter_by(academia_id=user.academia_id, codigo="SUPER").count() == 1


def test_roles_no_administrativos_no_crean_ni_editan_plan(app, db, base_data):
    plan = crear_plan(db, base_data["academia_a"].id)
    for rol in ("PROFESOR", "COACH", "MONITOR"):
        user = base_data["profesor_a"] if rol == "PROFESOR" else crear_usuario(db, base_data, rol)
        client = app.test_client()
        login(client, user)
        crear = client.post("/finanzas/planes/nuevo", data={"codigo": rol, "nombre": rol, "orden": "0"})
        editar = client.post(f"/finanzas/planes/{plan.id}/editar", data={"codigo": "CAMBIO", "nombre": "Cambio", "orden": "0"})
        assert crear.status_code == 403
        assert editar.status_code == 403
    assert plan.codigo == "REGULAR"


def test_post_plan_sin_csrf_es_rechazado(app, db, base_data, monkeypatch):
    client = app.test_client()
    login(client, base_data["admin_a"])
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)

    response = client.post("/finanzas/planes/nuevo", data={"codigo": "SIN", "nombre": "Sin token", "orden": "0"})

    assert response.status_code == 400
    assert PlanFinanciero.query.filter_by(codigo="SIN").count() == 0


def test_admin_lista_crea_y_edita_frecuencia(app, db, base_data):
    crear_frecuencia(db, base_data["academia_b"].id, "B2")
    client = app.test_client()
    login(client, base_data["admin_a"])

    listado = client.get("/finanzas/frecuencias")
    crear = client.post("/finanzas/frecuencias/nueva", data={"codigo": "d3", "nombre": "Tres días", "dias_semana": "3"})
    frecuencia = FrecuenciaEntrenamiento.query.filter_by(academia_id=base_data["academia_a"].id, codigo="D3").one()
    editar = client.post(f"/finanzas/frecuencias/{frecuencia.id}/editar", data={"codigo": "d4", "nombre": "Cuatro días", "dias_semana": "4"})

    assert listado.status_code == 200
    assert b"Frecuencia B2" not in listado.data
    assert crear.status_code == 302
    assert editar.status_code == 302
    assert frecuencia.codigo == "D4"
    assert frecuencia.dias_semana == 4


def test_frecuencia_de_otro_tenant_no_se_filtra_ni_modifica(app, db, base_data):
    frecuencia = crear_frecuencia(db, base_data["academia_b"].id)
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(f"/finanzas/frecuencias/{frecuencia.id}/editar", data={"codigo": "CAMBIO", "nombre": "Cambio", "dias_semana": "1"})

    assert response.status_code == 404
    assert db.session.get(FrecuenciaEntrenamiento, frecuencia.id).codigo == "D3"


def test_catalogos_pueden_activarse_y_desactivarse(app, db, base_data):
    plan = crear_plan(db, base_data["academia_a"].id)
    frecuencia = crear_frecuencia(db, base_data["academia_a"].id)
    client = app.test_client()
    login(client, base_data["admin_a"])

    plan_response = client.post(f"/finanzas/planes/{plan.id}/alternar-activo")
    frecuencia_response = client.post(f"/finanzas/frecuencias/{frecuencia.id}/alternar-activo")

    assert plan_response.status_code == 302
    assert frecuencia_response.status_code == 302
    assert plan.activo is False
    assert frecuencia.activo is False


def test_navegacion_muestra_solo_catalogos_implementados(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get("/admin/")

    assert b"Planes financieros" in response.data
    assert b"Frecuencias" in response.data
    assert b"Tarifarios" not in response.data
    assert b"Descuentos" not in response.data
