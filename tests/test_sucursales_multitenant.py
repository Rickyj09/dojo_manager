from app.models.sucursal import Sucursal
from test_finanzas_tarifarios_ui import cliente


def crear_sucursales_tenants(
    db,
    base_data,
):
    sucursal_a = Sucursal(
        nombre="Sucursal exclusiva Tenant A",
        direccion="Direccion A",
        academia_id=base_data["academia_a"].id,
        activo=True,
    )

    sucursal_b = Sucursal(
        nombre="Sucursal exclusiva Tenant B",
        direccion="Direccion B",
        academia_id=base_data["academia_b"].id,
        activo=True,
    )

    db.session.add_all(
        [
            sucursal_a,
            sucursal_b,
        ]
    )

    db.session.commit()

    return (
        sucursal_a,
        sucursal_b,
    )


def test_admin_lista_solo_sucursales_de_su_academia(
    app,
    db,
    base_data,
):
    sucursal_a, sucursal_b = (
        crear_sucursales_tenants(
            db,
            base_data,
        )
    )

    client = cliente(
        app,
        base_data["admin_a"],
    )

    response = client.get(
        "/sucursales/"
    )

    assert response.status_code == 200

    texto = response.get_data(
        as_text=True,
    )

    assert sucursal_a.nombre in texto
    assert sucursal_b.nombre not in texto


def test_admin_no_puede_editar_sucursal_otro_tenant(
    app,
    db,
    base_data,
):
    _, sucursal_b = (
        crear_sucursales_tenants(
            db,
            base_data,
        )
    )

    client = cliente(
        app,
        base_data["admin_a"],
    )

    response = client.get(
        f"/sucursales/{sucursal_b.id}/editar"
    )

    assert response.status_code == 404

    response = client.post(
        f"/sucursales/{sucursal_b.id}/editar",
        data={
            "nombre": "Intento alteracion",
            "direccion": "Hack",
            "academia_id": (
                base_data["academia_a"].id
            ),
            "activo": "on",
        },
    )

    assert response.status_code == 404

    db.session.refresh(
        sucursal_b
    )

    assert (
        sucursal_b.nombre
        == "Sucursal exclusiva Tenant B"
    )


def test_admin_no_puede_eliminar_sucursal_otro_tenant(
    app,
    db,
    base_data,
):
    _, sucursal_b = (
        crear_sucursales_tenants(
            db,
            base_data,
        )
    )

    sucursal_b_id = sucursal_b.id

    client = cliente(
        app,
        base_data["admin_a"],
    )

    response = client.post(
        f"/sucursales/{sucursal_b_id}/eliminar"
    )

    assert response.status_code == 404

    assert (
        db.session.get(
            Sucursal,
            sucursal_b_id,
        )
        is not None
    )


def test_admin_no_puede_forzar_academia_al_crear_sucursal(
    app,
    db,
    base_data,
):
    client = cliente(
        app,
        base_data["admin_a"],
    )

    response = client.post(
        "/sucursales/nuevo",
        data={
            "nombre": "Sucursal creada por Admin A",
            "direccion": "Direccion demo",
            "academia_id": str(
                base_data["academia_b"].id
            ),
            "activo": "on",
        },
    )

    assert response.status_code == 302

    sucursal = (
        Sucursal.query
        .filter_by(
            nombre="Sucursal creada por Admin A"
        )
        .one()
    )

    assert (
        sucursal.academia_id
        == base_data["academia_a"].id
    )


def test_profesor_no_puede_administrar_sucursales(
    app,
    db,
    base_data,
):
    client = cliente(
        app,
        base_data["profesor_a"],
    )

    assert (
        client.get(
            "/sucursales/"
        ).status_code
        == 403
    )

    assert (
        client.get(
            "/sucursales/nuevo"
        ).status_code
        == 403
    )