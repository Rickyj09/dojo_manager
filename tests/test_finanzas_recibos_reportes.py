from datetime import date
from decimal import Decimal

from app.extensions import db as _db
from app.models.finanzas import ObligacionFinanciera
from app.services.finanzas.pagos import (
    anular_pago,
    aplicar_pago_a_obligaciones,
    registrar_pago,
)


def login(client, user):
    response = client.post(
        "/auth/login",
        data={
            "username": user.username,
            "password": "secret",
        },
    )
    assert response.status_code == 302


def crear_pago(
    base_data,
    *,
    academia_key="academia_a",
    alumno_key="alumno_a1",
    valor="50.00",
    medio_pago="EFECTIVO",
    referencia=None,
    observacion=None,
):
    pago = registrar_pago(
        academia_id=base_data[academia_key].id,
        alumno_id=base_data[alumno_key].id,
        fecha_pago=date(2026, 9, 5),
        valor=Decimal(valor),
        medio_pago=medio_pago,
        moneda="USD",
        referencia=referencia,
        observacion=observacion,
    )

    _db.session.commit()
    return pago


def crear_obligacion(
    base_data,
    *,
    alumno_key="alumno_a1",
    valor="50.00",
    periodo="2026-09",
    concepto="Pension septiembre",
):
    valor_decimal = Decimal(valor)

    obligacion = ObligacionFinanciera(
        academia_id=base_data["academia_a"].id,
        alumno_id=base_data[alumno_key].id,
        alumno_plan_financiero_id=None,
        periodo=periodo,
        tipo_obligacion="PENSION",
        concepto=concepto,
        origen="TEST_RECIBO",
        fecha_emision=date(2026, 9, 1),
        fecha_vencimiento=date(2026, 9, 7),
        tarifa_base_snapshot=valor_decimal,
        porcentaje_descuento_snapshot=None,
        valor_descuento_snapshot=Decimal("0.00"),
        valor_final_snapshot=valor_decimal,
        moneda_snapshot="USD",
        estado="PENDIENTE",
    )

    _db.session.add(obligacion)
    _db.session.commit()

    return obligacion


def test_admin_puede_ver_recibo(app, db, base_data):
    pago = crear_pago(
        base_data,
        valor="75.50",
        medio_pago="TRANSFERENCIA",
        referencia="TRX-001",
        observacion="Pago mensual",
    )

    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(
        f"/finanzas/pagos/{pago.id}/recibo"
    )

    assert response.status_code == 200
    assert b"Recibo interno de pago" in response.data

    numero = f"REC-{pago.id:06d}".encode()
    assert numero in response.data

    assert base_data["academia_a"].nombre.encode() in response.data
    assert base_data["alumno_a1"].nombres.encode() in response.data
    assert base_data["alumno_a1"].apellidos.encode() in response.data

    assert b"TRANSFERENCIA" in response.data
    assert b"TRX-001" in response.data
    assert b"Pago mensual" in response.data
    assert b"USD" in response.data
    assert b"75.50" in response.data


def test_recibo_muestra_numero_deterministico(app, db, base_data):
    pago = crear_pago(base_data)

    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(
        f"/finanzas/pagos/{pago.id}/recibo"
    )

    assert response.status_code == 200

    numero_esperado = f"REC-{pago.id:06d}".encode()
    assert numero_esperado in response.data


def test_recibo_pago_sin_aplicaciones(app, db, base_data):
    pago = crear_pago(
        base_data,
        valor="50.00",
    )

    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(
        f"/finanzas/pagos/{pago.id}/recibo"
    )

    assert response.status_code == 200

    assert (
        b"Este pago todav\xc3\xada no tiene aplicaciones."
        in response.data
    )

    assert b"50.00" in response.data
    assert b"0.00" in response.data


def test_recibo_muestra_aplicaciones(app, db, base_data):
    obligacion = crear_obligacion(
        base_data,
        valor="60.00",
        periodo="2026-09",
        concepto="Pension septiembre",
    )

    pago = crear_pago(
        base_data,
        valor="60.00",
        medio_pago="TRANSFERENCIA",
        referencia="BANCO-2026-001",
    )

    aplicar_pago_a_obligaciones(
        academia_id=pago.academia_id,
        pago_id=pago.id,
        aplicaciones=[
            {
                "obligacion_financiera_id": obligacion.id,
                "valor_aplicado": Decimal("40.00"),
            }
        ],
    )

    _db.session.commit()

    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(
        f"/finanzas/pagos/{pago.id}/recibo"
    )

    assert response.status_code == 200
    assert b"2026-09" in response.data
    assert b"PENSION" in response.data
    assert b"Pension septiembre" in response.data
    assert b"40.00" in response.data
    assert b"20.00" in response.data


def test_pago_anulado_conserva_recibo(app, db, base_data):
    pago = crear_pago(
        base_data,
        valor="35.00",
    )

    anular_pago(
        academia_id=pago.academia_id,
        pago_id=pago.id,
    )
    _db.session.commit()

    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(
        f"/finanzas/pagos/{pago.id}/recibo"
    )

    assert response.status_code == 200
    assert b"PAGO ANULADO" in response.data
    assert b"ANULADO" in response.data

    numero = f"REC-{pago.id:06d}".encode()
    assert numero in response.data


def test_otro_tenant_no_puede_ver_recibo(app, db, base_data):
    pago = crear_pago(
        base_data,
        academia_key="academia_b",
        alumno_key="alumno_b1",
    )

    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(
        f"/finanzas/pagos/{pago.id}/recibo"
    )

    assert response.status_code == 404


def test_profesor_puede_ver_recibo_alumno_visible(
    app,
    db,
    base_data,
):
    pago = crear_pago(base_data)

    client = app.test_client()
    login(client, base_data["profesor_a"])

    response = client.get(
        f"/finanzas/pagos/{pago.id}/recibo"
    )

    assert response.status_code == 200

    numero = f"REC-{pago.id:06d}".encode()
    assert numero in response.data


def test_detalle_pago_enlaza_recibo(app, db, base_data):
    pago = crear_pago(base_data)

    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(
        f"/finanzas/pagos/{pago.id}"
    )

    assert response.status_code == 200
    assert b"Ver recibo" in response.data

    ruta = (
        f"/finanzas/pagos/{pago.id}/recibo"
    ).encode()

    assert ruta in response.data


def test_recibo_indica_documento_no_tributario(
    app,
    db,
    base_data,
):
    pago = crear_pago(base_data)

    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(
        f"/finanzas/pagos/{pago.id}/recibo"
    )

    assert response.status_code == 200

    assert (
        b"No constituye factura ni comprobante tributario."
        in response.data
    )