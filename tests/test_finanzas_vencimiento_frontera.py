import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.finanzas import ObligacionFinanciera, PagoAplicacion, PagoFinanciero
from app.services.finanzas import cartera
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.pagos import aplicar_pago, registrar_pago
from app.services.finanzas.vencimientos import analizar_vencimiento_obligacion
from test_finanzas_cartera import crear_plan_y_obligacion, crear_obligacion_manual, fijar_vencimiento, login


HOY = date(2026, 9, 10)


@pytest.mark.parametrize("vencimiento", [date(2026, 2, 28), HOY, date(2026, 12, 31)])
@pytest.mark.parametrize("desfase,condicion,dias,bucket", [
    (-1, "VIGENTE", 0, "NO_VENCIDA"),
    (0, "VENCIDA", 0, "VENCE_HOY"),
    (1, "VENCIDA", 1, "1_30"),
    (2, "VENCIDA", 2, "1_30"),
])
def test_frontera_general_y_dias_no_negativos(vencimiento, desfase, condicion, dias, bucket):
    analisis = analizar_vencimiento_obligacion(fecha_vencimiento=vencimiento,
        saldo=Decimal("40.00"), estado_financiero="PARCIAL",
        fecha_referencia=vencimiento + timedelta(days=desfase))
    assert (analisis.condicion, analisis.dias_atraso, analisis.bucket_antiguedad) == (condicion, dias, bucket)


def test_sin_fecha_conserva_semantica():
    analisis = analizar_vencimiento_obligacion(fecha_vencimiento=None,
        saldo=Decimal("40.00"), estado_financiero="PENDIENTE", fecha_referencia=HOY)
    assert (analisis.condicion, analisis.dias_atraso, analisis.bucket_antiguedad) == (
        "SIN_VENCIMIENTO", 0, "SIN_VENCIMIENTO")


@pytest.mark.parametrize("estado,saldo", [("PAGADA", "0"), ("ANULADA", "60"), ("PENDIENTE", "0")])
def test_sin_deuda_actual_no_es_vencida(estado, saldo):
    analisis = analizar_vencimiento_obligacion(fecha_vencimiento=HOY,
        saldo=Decimal(saldo), estado_financiero=estado, fecha_referencia=HOY)
    assert analisis.condicion != "VENCIDA"
    assert analisis.dias_atraso == 0
    assert analisis.bucket_antiguedad == "NO_VENCIDA"


def congelar_hoy(monkeypatch):
    class FechaControlada(date):
        @classmethod
        def today(cls):
            return HOY
    monkeypatch.setattr(cartera, "date", FechaControlada)


def datos_financieros():
    return {
        modelo.__tablename__: [tuple(getattr(item, columna.name) for columna in modelo.__table__.columns)
                              for item in modelo.query.order_by(modelo.id).all()]
        for modelo in (ObligacionFinanciera, PagoFinanciero, PagoAplicacion)
    }


@pytest.mark.parametrize("pagado,estado", [("0", "PENDIENTE"), ("20", "PARCIAL"), ("60", "PAGADA")])
def test_cartera_kpi_estado_cuenta_y_ui_en_fecha_limite(app, db, base_data, monkeypatch, pagado, estado):
    obligacion = crear_plan_y_obligacion(db, base_data)
    fijar_vencimiento(db, obligacion, HOY)
    if Decimal(pagado):
        pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id,
            fecha_pago=HOY, valor=Decimal(pagado), medio_pago="EFECTIVO")
        aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id,
            obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal(pagado))
        db.session.commit()
    antes = datos_financieros()
    saldo = Decimal("60") - Decimal(pagado)
    resumen = cartera.obtener_resumen_cartera_academia(academia_id=obligacion.academia_id, fecha_referencia=HOY)
    assert resumen.saldo_vencido == resumen.saldo_vence_hoy == saldo
    assert resumen.saldo_vigente == resumen.saldo_1_30 == 0
    assert resumen.cantidad_alumnos_con_saldo_vencido == resumen.cantidad_obligaciones_vencidas == int(saldo > 0)
    assert resumen.cantidad_obligaciones_pagadas == int(estado == "PAGADA")
    filas = cartera.obtener_cartera_alumnos(academia_id=obligacion.academia_id, fecha_referencia=HOY, vencidos=True)
    assert len(filas) == int(saldo > 0)
    if filas:
        assert filas[0].saldo_vencido == saldo and filas[0].dias_atraso_max == 0
    cuenta = cartera.obtener_estado_cuenta_alumno(academia_id=obligacion.academia_id,
        alumno_id=obligacion.alumno_id, fecha_referencia=HOY)
    assert cuenta.obligaciones[0].estado_derivado == estado
    assert cuenta.obligaciones[0].dias_atraso == 0
    assert (cuenta.obligaciones[0].condicion_temporal == "VENCIDA") == (saldo > 0)

    congelar_hoy(monkeypatch)
    client = app.test_client()
    login(client, base_data["admin_a"])
    response = client.get(f"/finanzas/alumnos/{obligacion.alumno_id}/estado-cuenta")
    assert response.status_code == 200
    fila = next(row for row in re.findall(r"<tr>.*?</tr>", response.text, re.S) if "Pension 2026-09" in row)
    assert estado in fila and "10/09/2026" in fila
    assert "VIGENTE" not in fila
    if saldo:
        assert "VENCIDA" in fila and "0 días" in fila
    else:
        assert "VENCIDA" not in fila and "Sin saldo pendiente" in fila
    response = client.get("/finanzas/cartera?saldo=vencidos")
    assert response.status_code == 200
    assert f'Saldo vencido</small>\n        <h4 class="mb-0">$ {saldo:.2f}</h4>' in response.text
    assert f'Alumnos con deuda vencida</small>\n        <h4 class="mb-0">{int(saldo > 0)}</h4>' in response.text
    if saldo:
        fila = next(row for row in re.findall(r"<tr>.*?</tr>", response.text, re.S) if "Perez Carlos" in row)
        assert "<td>0</td>" in fila
    db.session.expire_all()
    assert datos_financieros() == antes


def test_aging_separa_cero_dias_y_conserva_suma_vencida(db, base_data):
    hoy = crear_plan_y_obligacion(db, base_data, valor="60.00")
    hoy.fecha_vencimiento = HOY
    ayer = crear_obligacion_manual(db, hoy, "2026-08", "20.00")
    ayer.fecha_vencimiento = HOY - timedelta(days=1)
    futura = crear_obligacion_manual(db, hoy, "2026-10", "30.00")
    futura.fecha_vencimiento = HOY + timedelta(days=1)
    crear_obligacion_manual(db, hoy, "2026-11", "40.00")
    db.session.commit()
    resumen = cartera.obtener_resumen_cartera_academia(academia_id=hoy.academia_id, fecha_referencia=HOY)
    assert resumen.saldo_vence_hoy == Decimal("60.00")
    assert resumen.saldo_1_30 == Decimal("20.00")
    assert resumen.saldo_sin_vencimiento == Decimal("40.00")
    assert resumen.saldo_vigente == Decimal("70.00")
    assert resumen.saldo_vencido == Decimal("80.00")
    assert resumen.saldo_vencido == sum((resumen.saldo_vence_hoy, resumen.saldo_1_30,
        resumen.saldo_31_60, resumen.saldo_61_90, resumen.saldo_mas_90))
    assert resumen.cantidad_obligaciones_vencidas == 2
    assert resumen.cantidad_alumnos_con_saldo_vencido == 1


def test_frontera_aislada_por_academia(db, base_data):
    obligacion_a = crear_plan_y_obligacion(db, base_data)
    fijar_vencimiento(db, obligacion_a, HOY)
    obligacion_b = ObligacionFinanciera(academia_id=base_data["academia_b"].id,
        alumno_id=base_data["alumno_b1"].id, periodo="2026-09", tipo_obligacion="PENSION",
        concepto="Pension B", fecha_emision=date(2026, 9, 1), fecha_vencimiento=date(2026, 9, 23),
        tarifa_base_snapshot=Decimal("99"), valor_descuento_snapshot=Decimal("0"),
        valor_final_snapshot=Decimal("99"), moneda_snapshot="USD", estado="PENDIENTE")
    db.session.add(obligacion_b)
    db.session.commit()
    resumen_a = cartera.obtener_resumen_cartera_academia(academia_id=obligacion_a.academia_id, fecha_referencia=HOY)
    resumen_b = cartera.obtener_resumen_cartera_academia(academia_id=obligacion_b.academia_id, fecha_referencia=HOY)
    assert resumen_a.saldo_vencido == Decimal("60")
    assert resumen_a.cantidad_alumnos_con_saldo_vencido == 1
    assert resumen_b.saldo_vencido == resumen_b.cantidad_alumnos_con_saldo_vencido == 0
    assert resumen_b.saldo_vigente == Decimal("99")
    resumen_b = cartera.obtener_resumen_cartera_academia(academia_id=obligacion_b.academia_id, fecha_referencia=date(2026, 9, 23))
    assert resumen_b.saldo_vencido == resumen_b.saldo_vence_hoy == Decimal("99")
    assert resumen_b.cantidad_alumnos_con_saldo_vencido == 1
    filas = cartera.obtener_cartera_alumnos(academia_id=obligacion_a.academia_id, fecha_referencia=date(2026, 9, 23), vencidos=True)
    assert [fila.alumno_id for fila in filas] == [obligacion_a.alumno_id]
    with pytest.raises(FinanzasError):
        cartera.obtener_estado_cuenta_alumno(academia_id=obligacion_a.academia_id,
            alumno_id=obligacion_b.alumno_id, fecha_referencia=HOY)


def test_obligaciones_aplicables_y_detalle_pago_muestran_cero_dias(app, db, base_data, monkeypatch):
    obligacion = crear_plan_y_obligacion(db, base_data)
    fijar_vencimiento(db, obligacion, HOY)
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id,
        fecha_pago=HOY, valor=Decimal("10.00"), medio_pago="EFECTIVO")
    db.session.commit()
    aplicables = cartera.obtener_obligaciones_aplicables_pago(academia_id=obligacion.academia_id,
        pago_id=pago.id, fecha_referencia=HOY)
    assert len(aplicables) == 1
    assert aplicables[0].condicion_temporal == "VENCIDA" and aplicables[0].dias_atraso == 0
    congelar_hoy(monkeypatch)
    client = app.test_client()
    login(client, base_data["admin_a"])
    response = client.get(f"/finanzas/pagos/{pago.id}")
    assert response.status_code == 200
    assert "VENCIDA" in response.text and "0 días" in response.text
