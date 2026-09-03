from datetime import date
from decimal import Decimal

import pytest

from app.models.finanzas import (
    FrecuenciaEntrenamiento,
    ObligacionFinanciera,
    PagoAplicacion,
    PagoFinanciero,
    PlanFinanciero,
    TarifaPlan,
    Tarifario,
)
from app.models.pago import Pago
from app.models.sucursal import Sucursal
from app.services.finanzas.asignaciones import asignar_plan_financiero
from app.services.finanzas.cartera import (
    obtener_cartera_alumnos,
    obtener_estado_cuenta_alumno,
    obtener_resumen_cartera_academia,
)
from app.services.finanzas.obligaciones import generar_obligaciones_mensuales
from app.services.finanzas.pagos import aplicar_pago, calcular_saldo_obligacion, calcular_saldo_pago, registrar_pago
from app.services.finanzas.vencimientos import (
    CONDICION_SIN_VENCIMIENTO,
    CONDICION_VENCIDA,
    CONDICION_VIGENTE,
    clasificar_antiguedad_cartera,
)


def login(client, user):
    response = client.post(
        "/auth/login",
        data={"username": user.username, "password": "secret"},
    )
    assert response.status_code == 302


def crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a1", periodo="2026-09", valor="60.00", codigo="REGULAR"):
    academia_id = base_data["academia_a"].id
    plan = PlanFinanciero(academia_id=academia_id, codigo=f"{codigo}_{alumno_key}_{periodo}", nombre=codigo)
    frecuencia = FrecuenciaEntrenamiento(academia_id=academia_id, codigo=f"D3_{codigo}_{alumno_key}_{periodo}", nombre="3 dias", dias_semana=3)
    tarifario = Tarifario(academia_id=academia_id, nombre=f"Tarifario {codigo}", fecha_inicio_vigencia=date(2026, 1, 1), estado="VIGENTE", moneda="USD")
    db.session.add_all([plan, frecuencia, tarifario])
    db.session.flush()
    tarifa = TarifaPlan(academia_id=academia_id, tarifario_id=tarifario.id, plan_id=plan.id, frecuencia_id=frecuencia.id, valor_base=Decimal(valor))
    db.session.add(tarifa)
    db.session.commit()
    asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data[alumno_key].id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        tarifario_id=tarifario.id,
        fecha_inicio=date(2026, 1, 1),
    )
    db.session.commit()
    generar_obligaciones_mensuales(academia_id=academia_id, periodo=periodo)
    db.session.commit()
    return ObligacionFinanciera.query.filter_by(academia_id=academia_id, alumno_id=base_data[alumno_key].id, periodo=periodo).one()


def crear_obligacion_manual(db, obligacion_ref, periodo, valor):
    obligacion = ObligacionFinanciera(
        academia_id=obligacion_ref.academia_id,
        alumno_id=obligacion_ref.alumno_id,
        alumno_plan_financiero_id=obligacion_ref.alumno_plan_financiero_id,
        periodo=periodo,
        tipo_obligacion="PENSION",
        concepto=f"Pension {periodo}",
        origen="TEST",
        fecha_emision=date(int(periodo[:4]), int(periodo[5:]), 1),
        tarifa_base_snapshot=Decimal(valor),
        valor_descuento_snapshot=Decimal("0.00"),
        valor_final_snapshot=Decimal(valor),
        moneda_snapshot="USD",
        estado="PENDIENTE",
    )
    db.session.add(obligacion)
    db.session.flush()
    return obligacion


def fijar_vencimiento(db, obligacion, fecha_vencimiento):
    obligacion.fecha_vencimiento = fecha_vencimiento
    db.session.commit()
    return obligacion


def test_academia_sin_obligaciones(db, base_data):
    resumen = obtener_resumen_cartera_academia(academia_id=base_data["academia_a"].id)

    assert resumen.total_obligaciones == Decimal("0.00")
    assert resumen.total_aplicado == Decimal("0.00")
    assert resumen.saldo_pendiente == Decimal("0.00")
    assert resumen.saldo_vencido == Decimal("0.00")
    assert resumen.saldo_vigente == Decimal("0.00")
    assert resumen.cantidad_alumnos_con_saldo == 0


def test_obligacion_pendiente(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")

    estado = obtener_estado_cuenta_alumno(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id)

    assert estado.obligaciones[0].estado_derivado == "PENDIENTE"
    assert estado.saldo_pendiente == Decimal("60.00")
    assert estado.obligaciones[0].condicion_temporal == CONDICION_SIN_VENCIMIENTO


def test_obligacion_parcial(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("20.00"), medio_pago="EFECTIVO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("20.00"))
    db.session.commit()

    estado = obtener_estado_cuenta_alumno(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id)

    assert estado.obligaciones[0].estado_derivado == "PARCIAL"
    assert estado.saldo_pendiente == Decimal("40.00")


def test_obligacion_pagada(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("60.00"), medio_pago="EFECTIVO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("60.00"))
    db.session.commit()

    resumen = obtener_resumen_cartera_academia(academia_id=obligacion.academia_id)

    assert resumen.cantidad_obligaciones_pagadas == 1
    assert resumen.saldo_pendiente == Decimal("0.00")
    assert resumen.saldo_vencido == Decimal("0.00")


def test_obligacion_anulada_excluida_del_saldo(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    obligacion.estado = "ANULADA"
    db.session.commit()

    resumen = obtener_resumen_cartera_academia(academia_id=obligacion.academia_id)
    estado = obtener_estado_cuenta_alumno(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id)

    assert resumen.total_obligaciones == Decimal("0.00")
    assert estado.obligaciones[0].estado_derivado == "ANULADA"


def test_multiples_obligaciones_por_alumno(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, periodo="2026-09", valor="40.00")
    crear_obligacion_manual(db, obligacion, periodo="2026-10", valor="35.00")
    db.session.commit()

    estado = obtener_estado_cuenta_alumno(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id)

    assert estado.total_generado == Decimal("75.00")
    assert estado.saldo_pendiente == Decimal("75.00")


def test_multiples_alumnos(db, base_data):
    obligacion_1 = crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a1", valor="60.00")
    crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a2", valor="40.00", codigo="DESARROLLO")

    resumen = obtener_resumen_cartera_academia(academia_id=obligacion_1.academia_id)
    filas = obtener_cartera_alumnos(academia_id=obligacion_1.academia_id, con_saldo=True)

    assert resumen.saldo_pendiente == Decimal("100.00")
    assert len(filas) == 2


def test_pago_parcialmente_aplicado_y_saldo_sin_aplicar(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("50.00"), medio_pago="EFECTIVO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("20.00"))
    db.session.commit()

    estado = obtener_estado_cuenta_alumno(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id)

    assert estado.saldo_pendiente == Decimal("40.00")
    assert estado.saldo_pagos_sin_aplicar == Decimal("30.00")


def test_pago_sin_aplicar_no_reduce_obligacion(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("50.00"), medio_pago="EFECTIVO")
    db.session.commit()

    estado = obtener_estado_cuenta_alumno(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id)

    assert estado.saldo_pendiente == Decimal("50.00")
    assert estado.saldo_pagos_sin_aplicar == Decimal("50.00")


def test_total_academia_correcto(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="100.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("30.00"), medio_pago="EFECTIVO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("30.00"))
    db.session.commit()

    resumen = obtener_resumen_cartera_academia(academia_id=obligacion.academia_id)

    assert resumen.total_obligaciones == Decimal("100.00")
    assert resumen.total_aplicado == Decimal("30.00")
    assert resumen.saldo_pendiente == Decimal("70.00")
    assert resumen.saldo_sin_vencimiento == Decimal("70.00")


def test_total_alumno_correcto(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="100.00")

    fila = obtener_cartera_alumnos(academia_id=obligacion.academia_id, con_saldo=True)[0]

    assert fila.total_obligaciones == Decimal("100.00")
    assert fila.saldo_pendiente == Decimal("100.00")


def test_aislamiento_entre_academias(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="100.00")

    resumen_b = obtener_resumen_cartera_academia(academia_id=base_data["academia_b"].id)

    assert obligacion.academia_id == base_data["academia_a"].id
    assert resumen_b.total_obligaciones == Decimal("0.00")


def test_decimal_correcto(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.25")

    estado = obtener_estado_cuenta_alumno(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id)

    assert isinstance(estado.total_generado, Decimal)
    assert estado.total_generado == Decimal("60.25")


def test_estado_cuenta_no_incluye_datos_de_otro_alumno(db, base_data):
    obligacion_1 = crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a1", valor="60.00")
    crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a2", valor="40.00", codigo="DESARROLLO")

    estado = obtener_estado_cuenta_alumno(academia_id=obligacion_1.academia_id, alumno_id=base_data["alumno_a1"].id)

    assert len(estado.obligaciones) == 1
    assert estado.total_generado == Decimal("60.00")


def test_estado_cuenta_no_incluye_pago_legacy(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    pago_legacy = Pago(
        academia_id=obligacion.academia_id,
        alumno_id=obligacion.alumno_id,
        sucursal_id=base_data["alumno_a1"].sucursal_id,
        monto=Decimal("60.00"),
        fecha_pago=date(2026, 9, 5),
        mes=10,
        anio=2026,
        metodo="EFECTIVO",
    )
    db.session.add(pago_legacy)
    db.session.commit()

    estado = obtener_estado_cuenta_alumno(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id)

    assert estado.total_pagado == Decimal("0.00")
    assert estado.saldo_pendiente == Decimal("60.00")
    assert estado.pagos == []


def test_vista_cartera_acceso_autorizado_y_listado(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get("/finanzas/cartera")

    assert response.status_code == 200
    assert b"Cartera financiera" in response.data
    assert base_data["alumno_a1"].apellidos.encode() in response.data
    assert b"60.00" in response.data


def test_vista_cartera_filtros_basicos(app, db, base_data):
    crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a1", valor="60.00")
    crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a2", valor="40.00", codigo="DESARROLLO")
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get("/finanzas/cartera?q=Carlos&saldo=con_saldo&periodo=2026-09")

    assert response.status_code == 200
    assert b"Carlos" in response.data
    assert b"Maria" not in response.data


def test_vista_cartera_filtro_vencidos(app, db, base_data):
    obligacion_1 = crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a1", valor="60.00")
    obligacion_2 = crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a2", valor="40.00", codigo="DESARROLLO")
    fijar_vencimiento(db, obligacion_1, date(2026, 1, 1))
    fijar_vencimiento(db, obligacion_2, date(2099, 1, 1))
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get("/finanzas/cartera?saldo=vencidos")

    assert response.status_code == 200
    assert b"Carlos" in response.data
    assert b"Maria" not in response.data


def test_vista_profesor_limita_cartera_a_sucursal(app, db, base_data):
    sucursal_otro = Sucursal(
        nombre="Norte A",
        academia_id=base_data["academia_a"].id,
        activo=True,
    )
    db.session.add(sucursal_otro)
    db.session.flush()
    base_data["alumno_a2"].sucursal_id = sucursal_otro.id
    db.session.commit()
    crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a1", valor="60.00")
    crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a2", valor="40.00", codigo="DESARROLLO")
    client = app.test_client()
    login(client, base_data["profesor_a"])

    response = client.get("/finanzas/cartera")

    assert response.status_code == 200
    assert b"Carlos" in response.data
    assert b"Maria" not in response.data
    assert b"100.00" not in response.data


def test_vista_estado_cuenta(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/alumnos/{obligacion.alumno_id}/estado-cuenta")

    assert response.status_code == 200
    assert b"Estado de cuenta" in response.data
    assert b"Obligaciones" in response.data
    assert b"Pagos" in response.data
    assert b"Sin vencimiento configurado" in response.data


def test_vista_bloquea_alumno_de_otra_academia(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/alumnos/{base_data['alumno_b1'].id}/estado-cuenta")

    assert response.status_code == 404


@pytest.mark.parametrize("estado_esperado,aplicado", [("PENDIENTE", "0.00"), ("PARCIAL", "20.00"), ("PAGADA", "60.00")])
def test_vista_representa_estados(app, db, base_data, estado_esperado, aplicado):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    if Decimal(aplicado) > 0:
        pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal(aplicado), medio_pago="EFECTIVO")
        aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal(aplicado))
        db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/alumnos/{obligacion.alumno_id}/estado-cuenta")

    assert response.status_code == 200
    assert estado_esperado.encode() in response.data


def test_vista_representa_anulada(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    obligacion.estado = "ANULADA"
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/alumnos/{obligacion.alumno_id}/estado-cuenta")

    assert response.status_code == 200
    assert b"ANULADA" in response.data


def test_vista_pago_sin_aplicar_visible(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("50.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/alumnos/{obligacion.alumno_id}/estado-cuenta")

    assert response.status_code == 200
    assert b"Saldo de pagos sin aplicar" in response.data
    assert b"50.00" in response.data


def test_obligacion_antes_del_vencimiento_es_vigente(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    fijar_vencimiento(db, obligacion, date(2026, 9, 10))

    estado = obtener_estado_cuenta_alumno(
        academia_id=obligacion.academia_id,
        alumno_id=obligacion.alumno_id,
        fecha_referencia=date(2026, 9, 9),
    )

    assert estado.obligaciones[0].condicion_temporal == CONDICION_VIGENTE
    assert estado.obligaciones[0].dias_atraso == 0


def test_obligacion_mismo_dia_del_vencimiento_es_vigente(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    fijar_vencimiento(db, obligacion, date(2026, 9, 10))

    estado = obtener_estado_cuenta_alumno(
        academia_id=obligacion.academia_id,
        alumno_id=obligacion.alumno_id,
        fecha_referencia=date(2026, 9, 10),
    )

    assert estado.obligaciones[0].condicion_temporal == CONDICION_VIGENTE


def test_obligacion_un_dia_despues_es_vencida_y_calcula_atraso(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    fijar_vencimiento(db, obligacion, date(2026, 9, 10))

    estado = obtener_estado_cuenta_alumno(
        academia_id=obligacion.academia_id,
        alumno_id=obligacion.alumno_id,
        fecha_referencia=date(2026, 9, 11),
    )

    assert estado.obligaciones[0].condicion_temporal == CONDICION_VENCIDA
    assert estado.obligaciones[0].dias_atraso == 1


def test_obligacion_pagada_no_cuenta_como_vencida(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    fijar_vencimiento(db, obligacion, date(2026, 9, 10))
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 11), valor=Decimal("60.00"), medio_pago="EFECTIVO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("60.00"))
    db.session.commit()

    resumen = obtener_resumen_cartera_academia(
        academia_id=obligacion.academia_id,
        fecha_referencia=date(2026, 9, 20),
    )

    assert resumen.cantidad_obligaciones_vencidas == 0
    assert resumen.saldo_vencido == Decimal("0.00")


def test_obligacion_anulada_no_cuenta_como_vencida(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    obligacion.fecha_vencimiento = date(2026, 9, 10)
    obligacion.estado = "ANULADA"
    db.session.commit()

    resumen = obtener_resumen_cartera_academia(
        academia_id=obligacion.academia_id,
        fecha_referencia=date(2026, 9, 20),
    )

    assert resumen.cantidad_obligaciones_vencidas == 0
    assert resumen.saldo_vencido == Decimal("0.00")


def test_obligacion_parcial_vencida_cuenta_saldo_pendiente(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    fijar_vencimiento(db, obligacion, date(2026, 9, 10))
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 11), valor=Decimal("20.00"), medio_pago="EFECTIVO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("20.00"))
    db.session.commit()

    resumen = obtener_resumen_cartera_academia(
        academia_id=obligacion.academia_id,
        fecha_referencia=date(2026, 9, 20),
    )

    assert resumen.saldo_vencido == Decimal("40.00")
    assert resumen.cantidad_obligaciones_vencidas == 1


def test_obligacion_sin_vencimiento_se_clasifica_separada(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")

    resumen = obtener_resumen_cartera_academia(
        academia_id=obligacion.academia_id,
        fecha_referencia=date(2026, 9, 20),
    )

    assert resumen.saldo_sin_vencimiento == Decimal("60.00")
    assert resumen.saldo_vencido == Decimal("0.00")


@pytest.mark.parametrize(
    "dias,bucket",
    [
        (1, "1_30"),
        (30, "1_30"),
        (31, "31_60"),
        (60, "31_60"),
        (61, "61_90"),
        (90, "61_90"),
        (91, "MAS_90"),
    ],
)
def test_buckets_antiguedad_limites(dias, bucket):
    assert clasificar_antiguedad_cartera(dias) == bucket


def test_antiguedad_suma_buckets_decimal_y_aislamiento(db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.25")
    fijar_vencimiento(db, obligacion, date(2026, 8, 15))
    obligacion_b = ObligacionFinanciera(
        academia_id=base_data["academia_b"].id,
        alumno_id=base_data["alumno_b1"].id,
        periodo="2026-09",
        tipo_obligacion="PENSION",
        concepto="Pension 2026-09",
        origen="TEST",
        fecha_emision=date(2026, 9, 1),
        fecha_vencimiento=date(2026, 8, 1),
        tarifa_base_snapshot=Decimal("99.00"),
        valor_descuento_snapshot=Decimal("0.00"),
        valor_final_snapshot=Decimal("99.00"),
        moneda_snapshot="USD",
        estado="PENDIENTE",
    )
    db.session.add(obligacion_b)
    db.session.commit()

    resumen = obtener_resumen_cartera_academia(
        academia_id=obligacion.academia_id,
        fecha_referencia=date(2026, 9, 15),
    )

    assert resumen.saldo_31_60 == Decimal("60.25")
    assert resumen.saldo_vencido == Decimal("60.25")
    assert isinstance(resumen.saldo_vencido, Decimal)


def test_profesor_aislamiento_sucursal_en_resumen_vencido(app, db, base_data):
    sucursal_otro = Sucursal(nombre="Norte A", academia_id=base_data["academia_a"].id, activo=True)
    db.session.add(sucursal_otro)
    db.session.flush()
    base_data["alumno_a2"].sucursal_id = sucursal_otro.id
    db.session.commit()
    obligacion_1 = crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a1", valor="60.00")
    obligacion_2 = crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a2", valor="40.00", codigo="DESARROLLO")
    fijar_vencimiento(db, obligacion_1, date(2026, 1, 1))
    fijar_vencimiento(db, obligacion_2, date(2026, 1, 1))
    client = app.test_client()
    login(client, base_data["profesor_a"])

    response = client.get("/finanzas/cartera?saldo=vencidos")

    assert response.status_code == 200
    assert b"Carlos" in response.data
    assert b"Maria" not in response.data
    assert b"40.00" not in response.data


def test_vista_estado_cuenta_muestra_vigente_vencida_y_dias(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    fijar_vencimiento(db, obligacion, date(2026, 1, 1))
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/alumnos/{obligacion.alumno_id}/estado-cuenta")

    assert response.status_code == 200
    assert b"VENCIDA" in response.data
    assert b"d\xc3\xadas" in response.data


def test_configuracion_financiera_valida_y_guarda(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post("/finanzas/configuracion", data={"dia_vencimiento_pension": "15"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"15" in response.data


def test_configuracion_financiera_rechaza_dia_invalido(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post("/finanzas/configuracion", data={"dia_vencimiento_pension": "32"})

    assert response.status_code == 200
    assert b"entre 1 y 31" in response.data


def test_profesor_no_puede_configurar_finanzas(app, db, base_data):
    client = app.test_client()
    login(client, base_data["profesor_a"])

    response = client.get("/finanzas/configuracion")

    assert response.status_code == 403


def test_vista_nuevo_pago_get_autorizado(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/alumnos/{base_data['alumno_a1'].id}/pagos/nuevo")

    assert response.status_code == 200
    assert b"Registrar pago" in response.data
    assert b"EFECTIVO" in response.data


def test_vista_nuevo_pago_post_valido_redirige_y_crea_pago(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(
        f"/finanzas/alumnos/{base_data['alumno_a1'].id}/pagos/nuevo",
        data={
            "fecha_pago": "2026-09-05",
            "valor": "100.00",
            "moneda": "USD",
            "medio_pago": "TRANSFERENCIA",
            "referencia": "REC-100",
            "observacion": "Pago de prueba",
        },
    )

    pago = PagoFinanciero.query.filter_by(academia_id=base_data["academia_a"].id, alumno_id=base_data["alumno_a1"].id).one()
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/finanzas/pagos/{pago.id}")
    assert pago.valor == Decimal("100.00")
    assert pago.medio_pago == "TRANSFERENCIA"


@pytest.mark.parametrize("valor", ["0", "-10"])
def test_vista_nuevo_pago_rechaza_valor_no_positivo(app, db, base_data, valor):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(
        f"/finanzas/alumnos/{base_data['alumno_a1'].id}/pagos/nuevo",
        data={"fecha_pago": "2026-09-05", "valor": valor, "moneda": "USD", "medio_pago": "EFECTIVO"},
    )

    assert response.status_code == 200
    assert b"mayor a cero" in response.data
    assert PagoFinanciero.query.filter_by(academia_id=base_data["academia_a"].id).count() == 0


def test_vista_nuevo_pago_rechaza_valor_no_numerico(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(
        f"/finanzas/alumnos/{base_data['alumno_a1'].id}/pagos/nuevo",
        data={"fecha_pago": "2026-09-05", "valor": "abc", "moneda": "USD", "medio_pago": "EFECTIVO"},
    )

    assert response.status_code == 200
    assert b"numero valido" in response.data


def test_vista_nuevo_pago_rechaza_medio_invalido(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(
        f"/finanzas/alumnos/{base_data['alumno_a1'].id}/pagos/nuevo",
        data={"fecha_pago": "2026-09-05", "valor": "10.00", "moneda": "USD", "medio_pago": "CHEQUE"},
    )

    assert response.status_code == 200
    assert b"Medio de pago invalido" in response.data


def test_vista_nuevo_pago_bloquea_alumno_de_otra_academia(app, db, base_data):
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/alumnos/{base_data['alumno_b1'].id}/pagos/nuevo")

    assert response.status_code == 404


def test_profesor_no_puede_registrar_pago(app, db, base_data):
    client = app.test_client()
    login(client, base_data["profesor_a"])

    response = client.get(f"/finanzas/alumnos/{base_data['alumno_a1'].id}/pagos/nuevo")

    assert response.status_code == 403


def test_profesor_no_ve_acciones_de_pago(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("10.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["profesor_a"])

    cartera_response = client.get("/finanzas/cartera")
    estado_response = client.get(f"/finanzas/alumnos/{obligacion.alumno_id}/estado-cuenta")
    detalle_response = client.get(f"/finanzas/pagos/{pago.id}")

    assert cartera_response.status_code == 200
    assert estado_response.status_code == 200
    assert detalle_response.status_code == 200
    assert b"Registrar pago" not in cartera_response.data
    assert b"Registrar pago" not in estado_response.data
    assert b"Aplicar pago" not in detalle_response.data
    assert b"Anular pago" not in detalle_response.data


def test_vista_detalle_pago(app, db, base_data):
    pago = registrar_pago(academia_id=base_data["academia_a"].id, alumno_id=base_data["alumno_a1"].id, fecha_pago=date(2026, 9, 5), valor=Decimal("100.00"), medio_pago="EFECTIVO", referencia="REC-1")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/pagos/{pago.id}")

    assert response.status_code == 200
    assert b"Pago financiero" in response.data
    assert b"REC-1" in response.data
    assert b"Disponible" in response.data


def test_vista_detalle_pago_bloquea_otro_tenant(app, db, base_data):
    pago = registrar_pago(academia_id=base_data["academia_b"].id, alumno_id=base_data["alumno_b1"].id, fecha_pago=date(2026, 9, 5), valor=Decimal("100.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/pagos/{pago.id}")

    assert response.status_code == 404


def test_vista_aplicar_pago_completo(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("50.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(f"/finanzas/pagos/{pago.id}/aplicar", data={f"aplicar_{obligacion.id}": "50.00"})

    assert response.status_code == 302
    assert calcular_saldo_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == Decimal("0.00")
    assert calcular_saldo_pago(academia_id=obligacion.academia_id, pago_id=pago.id) == Decimal("0.00")


def test_vista_aplicar_pago_parcial(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("20.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    client.post(f"/finanzas/pagos/{pago.id}/aplicar", data={f"aplicar_{obligacion.id}": "20.00"})

    assert calcular_saldo_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == Decimal("30.00")


def test_vista_aplicar_pago_a_varias_obligaciones(app, db, base_data):
    obligacion_1 = crear_plan_y_obligacion(db, base_data, periodo="2026-09", valor="50.00")
    obligacion_2 = crear_obligacion_manual(db, obligacion_1, periodo="2026-10", valor="50.00")
    pago = registrar_pago(academia_id=obligacion_1.academia_id, alumno_id=obligacion_1.alumno_id, fecha_pago=date(2026, 10, 5), valor=Decimal("100.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    client.post(
        f"/finanzas/pagos/{pago.id}/aplicar",
        data={f"aplicar_{obligacion_1.id}": "50.00", f"aplicar_{obligacion_2.id}": "50.00"},
    )

    assert PagoAplicacion.query.filter_by(academia_id=obligacion_1.academia_id, pago_id=pago.id).count() == 2
    assert calcular_saldo_pago(academia_id=obligacion_1.academia_id, pago_id=pago.id) == Decimal("0.00")


def test_vista_sobreaplicacion_rechazada_no_persiste(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("100.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(f"/finanzas/pagos/{pago.id}/aplicar", data={f"aplicar_{obligacion.id}": "60.00"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"saldo de la obligacion" in response.data
    assert PagoAplicacion.query.filter_by(academia_id=obligacion.academia_id, pago_id=pago.id).count() == 0


def test_vista_aplicacion_a_obligacion_de_otro_alumno_rechazada(app, db, base_data):
    obligacion_juan = crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a1", valor="50.00")
    obligacion_maria = crear_plan_y_obligacion(db, base_data, alumno_key="alumno_a2", periodo="2026-10", valor="50.00")
    pago = registrar_pago(academia_id=obligacion_juan.academia_id, alumno_id=obligacion_juan.alumno_id, fecha_pago=date(2026, 10, 5), valor=Decimal("100.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(f"/finanzas/pagos/{pago.id}/aplicar", data={f"aplicar_{obligacion_maria.id}": "50.00"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"no pertenece al alumno" in response.data
    assert PagoAplicacion.query.filter_by(academia_id=obligacion_juan.academia_id, pago_id=pago.id).count() == 0


def test_vista_aplicacion_a_obligacion_de_otro_tenant_rechazada(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    obligacion_b = ObligacionFinanciera(
        academia_id=base_data["academia_b"].id,
        alumno_id=base_data["alumno_b1"].id,
        periodo="2026-09",
        tipo_obligacion="PENSION",
        concepto="Pension 2026-09",
        origen="TEST",
        fecha_emision=date(2026, 9, 1),
        tarifa_base_snapshot=Decimal("50.00"),
        valor_descuento_snapshot=Decimal("0.00"),
        valor_final_snapshot=Decimal("50.00"),
        moneda_snapshot="USD",
        estado="PENDIENTE",
    )
    db.session.add(obligacion_b)
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("100.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(f"/finanzas/pagos/{pago.id}/aplicar", data={f"aplicar_{obligacion_b.id}": "50.00"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"Obligacion no pertenece" in response.data
    assert PagoAplicacion.query.filter_by(academia_id=obligacion.academia_id, pago_id=pago.id).count() == 0


def test_vista_pago_sin_saldo_no_acepta_nueva_aplicacion(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    obligacion_2 = crear_obligacion_manual(db, obligacion, periodo="2026-10", valor="50.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("50.00"), medio_pago="EFECTIVO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("50.00"))
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(f"/finanzas/pagos/{pago.id}/aplicar", data={f"aplicar_{obligacion_2.id}": "1.00"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"saldo disponible" in response.data
    assert PagoAplicacion.query.filter_by(academia_id=obligacion.academia_id, pago_id=pago.id).count() == 1


def test_estado_cuenta_y_cartera_reflejan_pago_aplicado(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("50.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    client.post(f"/finanzas/pagos/{pago.id}/aplicar", data={f"aplicar_{obligacion.id}": "20.00"})
    estado = client.get(f"/finanzas/alumnos/{obligacion.alumno_id}/estado-cuenta")
    cartera = client.get("/finanzas/cartera")

    assert b"PARCIAL" in estado.data
    assert b"30.00" in estado.data
    assert b"30.00" in cartera.data


def test_vista_detalle_muestra_saldo_sin_aplicar(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("100.00"), medio_pago="EFECTIVO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("50.00"))
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/pagos/{pago.id}")

    assert response.status_code == 200
    assert b"Disponible" in response.data
    assert b"50.00" in response.data


def test_vista_anular_pago_sin_aplicaciones(app, db, base_data):
    pago = registrar_pago(academia_id=base_data["academia_a"].id, alumno_id=base_data["alumno_a1"].id, fecha_pago=date(2026, 9, 5), valor=Decimal("50.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(f"/finanzas/pagos/{pago.id}/anular")

    assert response.status_code == 302
    assert PagoFinanciero.query.filter_by(id=pago.id).one().estado == "ANULADO"


def test_vista_bloquea_anulacion_con_aplicaciones(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("50.00"), medio_pago="EFECTIVO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("20.00"))
    db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(f"/finanzas/pagos/{pago.id}/anular", follow_redirects=True)

    assert response.status_code == 200
    assert b"No se puede anular este pago porque tiene valores aplicados" in response.data
    assert PagoFinanciero.query.filter_by(id=pago.id).one().estado == "REGISTRADO"


def test_profesor_no_puede_aplicar_ni_anular_pago(app, db, base_data):
    obligacion = crear_plan_y_obligacion(db, base_data, valor="50.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("50.00"), medio_pago="EFECTIVO")
    db.session.commit()
    client = app.test_client()
    login(client, base_data["profesor_a"])

    aplicar_response = client.post(f"/finanzas/pagos/{pago.id}/aplicar", data={f"aplicar_{obligacion.id}": "10.00"})
    anular_response = client.post(f"/finanzas/pagos/{pago.id}/anular")

    assert aplicar_response.status_code == 403
    assert anular_response.status_code == 403
