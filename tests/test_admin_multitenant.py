from flask import g

import app.routes.admin as admin_routes
from app.models import Alumno, Asistencia, Role, Sucursal, User


def cliente(app, usuario):
    """
    Crea un cliente autenticado reutilizando el patrón de los tests
    existentes de branding.
    """
    g.pop("_login_user", None)

    client = app.test_client()

    with client.session_transaction() as sesion:
        sesion["_user_id"] = str(usuario.id)
        sesion["_fresh"] = True

    return client


def profesor_de_academia(academia_id):
    return (
        User.query
        .filter(
            User.academia_id == academia_id,
            User.roles.any(Role.name == "PROFESOR"),
        )
        .first()
    )


def obtener_o_crear_superadmin(db):
    role = Role.query.filter_by(name="SUPERADMIN").first()

    if role is None:
        role = Role(
            name="SUPERADMIN",
            description="Superadministrador",
        )
        db.session.add(role)
        db.session.commit()

    return role


def test_dashboard_admin_muestra_solo_totales_de_su_academia(
    app,
    db,
    base_data,
    monkeypatch,
):
    admin_a = base_data["admin_a"]
    academia_id = admin_a.academia_id

    capturado = {}

    def render_falso(template, **contexto):
        capturado["template"] = template
        capturado.update(contexto)
        return "OK"

    monkeypatch.setattr(
        admin_routes,
        "render_template",
        render_falso,
    )

    response = cliente(
        app,
        admin_a,
    ).get("/admin/")

    assert response.status_code == 200
    assert capturado["template"] == "admin/dashboard.html"

    assert capturado["total_alumnos"] == (
        Alumno.query
        .filter_by(academia_id=academia_id)
        .count()
    )

    assert capturado["total_sucursales"] == (
        Sucursal.query
        .filter_by(academia_id=academia_id)
        .count()
    )

    assert capturado["total_usuarios"] == (
        User.query
        .filter_by(academia_id=academia_id)
        .count()
    )


def test_dashboard_cambia_totales_segun_tenant(
    app,
    db,
    base_data,
    monkeypatch,
):
    admin_a = base_data["admin_a"]
    admin_b = base_data["admin_b"]

    contextos = []

    def render_falso(template, **contexto):
        contextos.append(
            {
                "template": template,
                **contexto,
            }
        )
        return "OK"

    monkeypatch.setattr(
        admin_routes,
        "render_template",
        render_falso,
    )

    response_a = cliente(
        app,
        admin_a,
    ).get("/admin/")

    assert response_a.status_code == 200

    contexto_a = contextos[-1]

    assert contexto_a["total_alumnos"] == (
        Alumno.query
        .filter_by(academia_id=admin_a.academia_id)
        .count()
    )

    assert contexto_a["total_sucursales"] == (
        Sucursal.query
        .filter_by(academia_id=admin_a.academia_id)
        .count()
    )

    assert contexto_a["total_usuarios"] == (
        User.query
        .filter_by(academia_id=admin_a.academia_id)
        .count()
    )

    response_b = cliente(
        app,
        admin_b,
    ).get("/admin/")

    assert response_b.status_code == 200

    contexto_b = contextos[-1]

    assert contexto_b["total_alumnos"] == (
        Alumno.query
        .filter_by(academia_id=admin_b.academia_id)
        .count()
    )

    assert contexto_b["total_sucursales"] == (
        Sucursal.query
        .filter_by(academia_id=admin_b.academia_id)
        .count()
    )

    assert contexto_b["total_usuarios"] == (
        User.query
        .filter_by(academia_id=admin_b.academia_id)
        .count()
    )


def test_listado_usuarios_no_muestra_otro_tenant(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]
    admin_b = base_data["admin_b"]

    response = cliente(
        app,
        admin_a,
    ).get("/admin/usuarios")

    assert response.status_code == 200

    assert admin_a.username in response.text
    assert admin_b.username not in response.text


def test_admin_no_puede_editar_usuario_de_otro_tenant(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]
    admin_b = base_data["admin_b"]

    response = cliente(
        app,
        admin_a,
    ).get(
        f"/admin/usuarios/{admin_b.id}/editar"
    )

    assert response.status_code == 404


def test_admin_no_puede_resetear_password_de_otro_tenant(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]
    admin_b = base_data["admin_b"]

    response = cliente(
        app,
        admin_a,
    ).get(
        f"/admin/usuarios/{admin_b.id}/reset-password"
    )

    assert response.status_code == 404


def test_admin_no_puede_eliminar_usuario_de_otro_tenant(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]
    admin_b = base_data["admin_b"]

    usuario_b_id = admin_b.id

    response = cliente(
        app,
        admin_a,
    ).post(
        f"/admin/usuarios/{usuario_b_id}/eliminar"
    )

    assert response.status_code == 404

    assert db.session.get(
        User,
        usuario_b_id,
    ) is not None


def test_usuario_nuevo_se_crea_en_academia_del_admin(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]

    role_admin = Role.query.filter_by(
        name="ADMIN"
    ).first()

    assert role_admin is not None

    response = cliente(
        app,
        admin_a,
    ).post(
        "/admin/usuarios/nuevo",
        data={
            "username": "nuevo_admin_a",
            "email": "nuevo_admin_a@example.com",
            "password": "Secret123!",
            "roles": [
                str(role_admin.id),
            ],
        },
    )

    assert response.status_code == 302

    creado = User.query.filter_by(
        username="nuevo_admin_a"
    ).first()

    assert creado is not None
    assert creado.academia_id == admin_a.academia_id


def test_admin_no_puede_asignar_superadmin(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]

    superadmin = obtener_o_crear_superadmin(
        db
    )

    response = cliente(
        app,
        admin_a,
    ).post(
        "/admin/usuarios/nuevo",
        data={
            "username": "intento_superadmin",
            "email": "intento_superadmin@example.com",
            "password": "Secret123!",
            "roles": [
                str(superadmin.id),
            ],
        },
    )

    assert response.status_code == 403

    assert User.query.filter_by(
        username="intento_superadmin"
    ).first() is None


def test_admin_no_puede_editar_catalogo_global_roles(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]

    client = cliente(
        app,
        admin_a,
    )

    assert client.get(
        "/admin/roles/nuevo"
    ).status_code == 403

    role_admin = Role.query.filter_by(
        name="ADMIN"
    ).first()

    assert role_admin is not None

    assert client.get(
        f"/admin/roles/{role_admin.id}/editar"
    ).status_code == 403


def test_profesor_puede_ver_dashboard_pero_no_usuarios(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]

    profesor = profesor_de_academia(
        admin_a.academia_id
    )

    assert profesor is not None

    client = cliente(
        app,
        profesor,
    )

    assert client.get(
        "/admin/"
    ).status_code == 200

    assert client.get(
        "/admin/usuarios"
    ).status_code == 403


def test_admin_no_puede_administrar_usuario_otro_tenant_en_asignar_sucursal(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]
    admin_b = base_data["admin_b"]

    profesor_b = profesor_de_academia(
        admin_b.academia_id
    )

    if profesor_b is None:
        profesor_role = Role.query.filter_by(
            name="PROFESOR"
        ).first()

        assert profesor_role is not None

        profesor_b = User(
            username="profesor_b_seguridad",
            email="profesor_b_seguridad@example.com",
            academia_id=admin_b.academia_id,
            is_active=True,
        )

        profesor_b.set_password(
            "Secret123!"
        )

        profesor_b.roles.append(
            profesor_role
        )

        db.session.add(
            profesor_b
        )
        db.session.commit()

    response = cliente(
        app,
        admin_a,
    ).get(
        f"/admin/usuarios/{profesor_b.id}/asignar-sucursal"
    )

    assert response.status_code == 404


def test_admin_no_puede_asignar_sucursal_de_otro_tenant(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]
    admin_b = base_data["admin_b"]

    profesor_a = profesor_de_academia(
        admin_a.academia_id
    )

    assert profesor_a is not None

    sucursal_b = (
        Sucursal.query
        .filter_by(
            academia_id=admin_b.academia_id,
            activo=True,
        )
        .first()
    )

    assert sucursal_b is not None

    sucursal_original = profesor_a.sucursal_id

    response = cliente(
        app,
        admin_a,
    ).post(
        f"/admin/usuarios/{profesor_a.id}/asignar-sucursal",
        data={
            "sucursal_id": str(
                sucursal_b.id
            ),
        },
    )

    assert response.status_code == 404

    db.session.refresh(
        profesor_a
    )

    assert profesor_a.sucursal_id == sucursal_original


def test_admin_no_puede_consultar_asistencia_sucursal_otro_tenant(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]
    admin_b = base_data["admin_b"]

    sucursal_b = (
        Sucursal.query
        .filter_by(
            academia_id=admin_b.academia_id,
            activo=True,
        )
        .first()
    )

    assert sucursal_b is not None

    response = cliente(
        app,
        admin_a,
    ).get(
        "/admin/asistencias",
        query_string={
            "sucursal_id": sucursal_b.id,
        },
    )

    assert response.status_code == 404


def test_admin_no_puede_guardar_asistencia_sucursal_otro_tenant(
    app,
    db,
    base_data,
):
    admin_a = base_data["admin_a"]
    admin_b = base_data["admin_b"]

    sucursal_b = (
        Sucursal.query
        .filter_by(
            academia_id=admin_b.academia_id,
            activo=True,
        )
        .first()
    )

    assert sucursal_b is not None

    antes = Asistencia.query.filter_by(
        academia_id=admin_b.academia_id,
        sucursal_id=sucursal_b.id,
    ).count()

    response = cliente(
        app,
        admin_a,
    ).post(
        "/admin/asistencias/guardar",
        data={
            "fecha": "2026-09-17",
            "sucursal_id": str(
                sucursal_b.id
            ),
        },
    )

    assert response.status_code == 404

    despues = Asistencia.query.filter_by(
        academia_id=admin_b.academia_id,
        sucursal_id=sucursal_b.id,
    ).count()

    assert despues == antes