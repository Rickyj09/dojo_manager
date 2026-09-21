from decimal import Decimal

import pytest

from app.models.finanzas import ReglaDescuento
from app.services.finanzas.descuentos import guardar_regla_descuento


def cliente(app, usuario):
    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={
            "username": usuario.username,
            "password": "secret",
        },
    )
    assert response.status_code == 302
    return client


def datos_regla(**cambios):
    datos = {
        "codigo": "HERMANOS-2",
        "nombre": "Hermanos 2",
        "tipo": "HERMANOS",
        "porcentaje": "10.00",
        "valor_fijo": "",
        "cantidad_minima": "2",
        "decimales_redondeo": "2",
        "vigencia_desde": "",
        "vigencia_hasta": "",
    }
    datos.update(cambios)
    return datos


def crear_regla(
    db,
    academia_id,
    codigo="HERMANOS-2",
    nombre="Hermanos 2",
    tipo="HERMANOS",
    porcentaje="10.00",
    valor_fijo="",
    cantidad_minima="2",
    activo=True,
):
    regla = guardar_regla_descuento(
        academia_id=academia_id,
        datos=datos_regla(
            codigo=codigo,
            nombre=nombre,
            tipo=tipo,
            porcentaje=porcentaje,
            valor_fijo=valor_fijo,
            cantidad_minima=cantidad_minima,
        ),
    )
    regla.activo = activo
    db.session.commit()
    return regla


def test_admin_lista_solo_reglas_de_su_academia(
    app,
    db,
    base_data,
):
    regla_a = crear_regla(
        db,
        base_data["academia_a"].id,
        codigo="HERMANOS-A",
        nombre="Regla Academia A",
    )

    regla_b = crear_regla(
        db,
        base_data["academia_b"].id,
        codigo="HERMANOS-B",
        nombre="Regla Academia B",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.get("/finanzas/descuentos")

    assert response.status_code == 200
    assert regla_a.nombre.encode() in response.data
    assert regla_b.nombre.encode() not in response.data
    assert b"Nueva regla" in response.data


def test_admin_crea_regla_porcentaje(
    app,
    db,
    base_data,
):
    client = cliente(app, base_data["admin_a"])

    response = client.post(
        "/finanzas/descuentos/nueva",
        data=datos_regla(
            academia_id=str(base_data["academia_b"].id),
        ),
    )

    assert response.status_code == 302
    assert response.location.endswith("/finanzas/descuentos")

    regla = ReglaDescuento.query.filter_by(
        codigo="HERMANOS_2",
    ).one()

    assert regla.academia_id == base_data["academia_a"].id
    assert regla.tipo == "HERMANOS"
    assert regla.porcentaje == Decimal("10.00")
    assert regla.valor_fijo is None
    assert regla.cantidad_minima == 2
    assert regla.activo is True


def test_admin_crea_beca_valor_fijo(
    app,
    db,
    base_data,
):
    client = cliente(app, base_data["admin_a"])

    response = client.post(
        "/finanzas/descuentos/nueva",
        data=datos_regla(
            codigo="BECA-FIJA",
            nombre="Beca fija",
            tipo="BECA",
            porcentaje="",
            valor_fijo="20.00",
            cantidad_minima="99",
            requiere_autorizacion="1",
        ),
    )

    assert response.status_code == 302

    regla = ReglaDescuento.query.filter_by(
        codigo="BECA_FIJA",
    ).one()

    assert regla.tipo == "BECA"
    assert regla.porcentaje is None
    assert regla.valor_fijo == Decimal("20.00")
    assert regla.cantidad_minima is None
    assert regla.requiere_autorizacion is True


@pytest.mark.parametrize(
    "cambios",
    [
        {
            "porcentaje": "",
            "valor_fijo": "",
        },
        {
            "porcentaje": "10",
            "valor_fijo": "5",
        },
        {
            "tipo": "HERMANOS",
            "cantidad_minima": "1",
        },
        {
            "tipo": "DESCONOCIDO",
        },
        {
            "porcentaje": "101",
        },
        {
            "vigencia_desde": "2026-10-01",
            "vigencia_hasta": "2026-09-01",
        },
        {
            "decimales_redondeo": "5",
        },
    ],
)
def test_ui_rechaza_reglas_invalidas(
    app,
    db,
    base_data,
    cambios,
):
    client = cliente(app, base_data["admin_a"])

    response = client.post(
        "/finanzas/descuentos/nueva",
        data=datos_regla(**cambios),
    )

    assert response.status_code == 200

    assert ReglaDescuento.query.filter_by(
        academia_id=base_data["academia_a"].id,
    ).count() == 0


def test_codigo_duplicado_mismo_tenant_es_rechazado(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id

    crear_regla(
        db,
        academia_id,
        codigo="HERMANOS-2",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        "/finanzas/descuentos/nueva",
        data=datos_regla(
            nombre="Otra regla",
        ),
    )

    assert response.status_code == 200

    assert ReglaDescuento.query.filter_by(
        academia_id=academia_id,
        codigo="HERMANOS_2",
    ).count() == 1


def test_mismo_codigo_permitido_en_otro_tenant(
    app,
    db,
    base_data,
):
    crear_regla(
        db,
        base_data["academia_b"].id,
        codigo="HERMANOS-2",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        "/finanzas/descuentos/nueva",
        data=datos_regla(),
    )

    assert response.status_code == 302

    assert ReglaDescuento.query.filter_by(
        codigo="HERMANOS_2",
    ).count() == 2


def test_busqueda_por_codigo_y_nombre(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id

    crear_regla(
        db,
        academia_id,
        codigo="HERMANOS-2",
        nombre="Descuento hermanos",
    )

    crear_regla(
        db,
        academia_id,
        codigo="BECA-20",
        nombre="Beca excelencia",
        tipo="BECA",
        porcentaje="20.00",
        cantidad_minima="",
    )

    client = cliente(app, base_data["admin_a"])

    codigo = client.get(
        "/finanzas/descuentos?q=HERMANOS"
    )

    assert b"Descuento hermanos" in codigo.data
    assert b"Beca excelencia" not in codigo.data

    nombre = client.get(
        "/finanzas/descuentos?q=excelencia"
    )

    assert b"Beca excelencia" in nombre.data
    assert b"Descuento hermanos" not in nombre.data


def test_filtro_por_tipo(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id

    crear_regla(
        db,
        academia_id,
        codigo="HERMANOS-2",
        nombre="Regla hermanos",
    )

    crear_regla(
        db,
        academia_id,
        codigo="BECA-20",
        nombre="Regla beca",
        tipo="BECA",
        porcentaje="20",
        cantidad_minima="",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.get(
        "/finanzas/descuentos?tipo=BECA"
    )

    assert b"Regla beca" in response.data
    assert b"Regla hermanos" not in response.data


def test_filtro_por_estado(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id

    crear_regla(
        db,
        academia_id,
        codigo="REGLA-ACTIVA",
        nombre="Regla Activa",
        activo=True,
    )

    crear_regla(
        db,
        academia_id,
        codigo="REGLA-INACTIVA",
        nombre="Regla Inactiva",
        activo=False,
    )

    client = cliente(app, base_data["admin_a"])

    activas = client.get(
        "/finanzas/descuentos?estado=activas"
    )

    assert b"Regla Activa" in activas.data
    assert b"Regla Inactiva" not in activas.data

    inactivas = client.get(
        "/finanzas/descuentos?estado=inactivas"
    )

    assert b"Regla Inactiva" in inactivas.data
    assert b"Regla Activa" not in inactivas.data


def test_edicion_no_permite_cambiar_codigo(
    app,
    db,
    base_data,
):
    regla = crear_regla(
        db,
        base_data["academia_a"].id,
        codigo="HERMANOS-2",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        f"/finanzas/descuentos/{regla.id}/editar",
        data=datos_regla(
            codigo="MANIPULADO",
            nombre="Hermanos actualizado",
            porcentaje="15.00",
        ),
    )

    assert response.status_code == 302

    db.session.refresh(regla)

    assert regla.codigo == "HERMANOS_2"
    assert regla.nombre == "Hermanos actualizado"
    assert regla.porcentaje == Decimal("15.00")


def test_editar_puede_cambiar_tipo_y_limpia_cantidad(
    app,
    db,
    base_data,
):
    regla = crear_regla(
        db,
        base_data["academia_a"].id,
    )

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        f"/finanzas/descuentos/{regla.id}/editar",
        data=datos_regla(
            tipo="BECA",
            nombre="Beca especial",
            cantidad_minima="50",
        ),
    )

    assert response.status_code == 302

    db.session.refresh(regla)

    assert regla.tipo == "BECA"
    assert regla.cantidad_minima is None


def test_academia_no_puede_editar_regla_ajena(
    app,
    db,
    base_data,
):
    regla_b = crear_regla(
        db,
        base_data["academia_b"].id,
        codigo="REGLA-B",
    )

    client = cliente(app, base_data["admin_a"])

    assert client.get(
        f"/finanzas/descuentos/{regla_b.id}/editar"
    ).status_code == 404

    assert client.post(
        f"/finanzas/descuentos/{regla_b.id}/editar",
        data=datos_regla(),
    ).status_code == 404

    assert client.post(
        (
            f"/finanzas/descuentos/"
            f"{regla_b.id}/alternar-activo"
        ),
    ).status_code == 404


def test_admin_puede_desactivar_y_reactivar(
    app,
    db,
    base_data,
):
    regla = crear_regla(
        db,
        base_data["academia_a"].id,
    )

    client = cliente(app, base_data["admin_a"])

    url = (
        f"/finanzas/descuentos/"
        f"{regla.id}/alternar-activo"
    )

    response = client.post(url)
    assert response.status_code == 302

    db.session.refresh(regla)
    assert regla.activo is False

    response = client.post(url)
    assert response.status_code == 302

    db.session.refresh(regla)
    assert regla.activo is True


def test_profesor_no_administra_descuentos(
    app,
    db,
    base_data,
):
    regla = crear_regla(
        db,
        base_data["academia_a"].id,
    )

    client = cliente(app, base_data["profesor_a"])

    urls_get = [
        "/finanzas/descuentos",
        "/finanzas/descuentos/nueva",
        f"/finanzas/descuentos/{regla.id}/editar",
    ]

    for url in urls_get:
        assert client.get(url).status_code == 403

    assert client.post(
        "/finanzas/descuentos/nueva",
        data=datos_regla(),
    ).status_code == 403

    assert client.post(
        f"/finanzas/descuentos/{regla.id}/editar",
        data=datos_regla(),
    ).status_code == 403

    assert client.post(
        (
            f"/finanzas/descuentos/"
            f"{regla.id}/alternar-activo"
        ),
    ).status_code == 403


def test_sidebar_admin_muestra_descuentos(
    app,
    db,
    base_data,
):
    client = cliente(app, base_data["admin_a"])

    response = client.get("/finanzas/cartera")

    assert response.status_code == 200
    assert b'href="/finanzas/descuentos"' in response.data


def test_sidebar_profesor_no_muestra_descuentos(
    app,
    db,
    base_data,
):
    client = cliente(app, base_data["profesor_a"])

    response = client.get("/finanzas/cartera")

    assert response.status_code == 200
    assert b'href="/finanzas/descuentos"' not in response.data


def test_csrf_protege_mutaciones(
    app,
    db,
    base_data,
    monkeypatch,
):
    regla = crear_regla(
        db,
        base_data["academia_a"].id,
    )

    client = cliente(app, base_data["admin_a"])

    monkeypatch.setitem(
        app.config,
        "WTF_CSRF_ENABLED",
        True,
    )

    assert client.post(
        "/finanzas/descuentos/nueva",
        data=datos_regla(),
    ).status_code == 400

    assert client.post(
        f"/finanzas/descuentos/{regla.id}/editar",
        data=datos_regla(),
    ).status_code == 400

    assert client.post(
        (
            f"/finanzas/descuentos/"
            f"{regla.id}/alternar-activo"
        ),
    ).status_code == 400

    assert b'name="csrf_token"' in client.get(
        "/finanzas/descuentos/nueva"
    ).data

    assert b'name="csrf_token"' in client.get(
        f"/finanzas/descuentos/{regla.id}/editar"
    ).data

    listado = client.get("/finanzas/descuentos")

    assert listado.status_code == 200
    assert b'name="csrf_token"' in listado.data
def test_formulario_hermanos_muestra_cantidad_minima(
    app,
    db,
    base_data,
):
    regla = crear_regla(
        db,
        base_data["academia_a"].id,
        codigo="HERMANOS-UI",
        nombre="Hermanos UI",
        tipo="HERMANOS",
        cantidad_minima="2",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.get(
        f"/finanzas/descuentos/{regla.id}/editar"
    )

    assert response.status_code == 200

    texto = response.get_data(as_text=True)

    assert 'id="tipo_descuento"' in texto
    assert 'value="HERMANOS"' in texto
    assert 'id="grupo_cantidad_minima"' in texto
    assert 'id="cantidad_minima"' in texto
    assert 'min="2"' in texto
    assert "d-none" not in texto.split(
        'id="grupo_cantidad_minima"'
    )[0].split("<div")[-1]
    assert "js/descuento_form.js" in texto


def test_formulario_beca_oculta_cantidad_minima(
    app,
    db,
    base_data,
):
    regla = crear_regla(
        db,
        base_data["academia_a"].id,
        codigo="BECA-UI",
        nombre="Beca UI",
        tipo="BECA",
        porcentaje="50.00",
        cantidad_minima="",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.get(
        f"/finanzas/descuentos/{regla.id}/editar"
    )

    assert response.status_code == 200

    texto = response.get_data(as_text=True)

    assert 'id="tipo_descuento"' in texto
    assert 'value="BECA"' in texto
    assert (
        'class="col-md-3 d-none"\n'
        '        id="grupo_cantidad_minima"'
        in texto
    )
    assert 'id="cantidad_minima"' in texto
    assert "disabled" in texto
    assert "js/descuento_form.js" in texto