from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.alumno import Alumno
from app.models.finanzas import (
    FrecuenciaEntrenamiento,
    ObligacionFinanciera,
    PagoAplicacion,
    PagoFinanciero,
    PlanFinanciero,
    TarifaPlan,
    Tarifario,
)
from app.services.finanzas.asignaciones import asignar_plan_financiero
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.obligaciones import generar_obligaciones_mensuales
from app.services.finanzas.pagos import (
    anular_pago,
    aplicar_pago,
    aplicar_pago_a_obligaciones,
    calcular_saldo_obligacion,
    calcular_saldo_pago,
    calcular_total_aplicado_pago,
    calcular_total_pagado_obligacion,
    obtener_estado_pago_obligacion,
    registrar_pago,
)


def crear_plan_base(db, base_data, alumno_key="alumno_a1", valor="60.00", codigo="REGULAR"):
    academia_id = base_data["academia_a"].id
    plan = PlanFinanciero(academia_id=academia_id, codigo=codigo, nombre=codigo)
    frecuencia = FrecuenciaEntrenamiento(academia_id=academia_id, codigo=f"D3_{codigo}", nombre="3 dias", dias_semana=3)
    tarifario = Tarifario(
        academia_id=academia_id,
        nombre=f"Tarifario {codigo}",
        fecha_inicio_vigencia=date(2026, 1, 1),
        estado="VIGENTE",
        moneda="USD",
    )
    db.session.add_all([plan, frecuencia, tarifario])
    db.session.flush()
    tarifa = TarifaPlan(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        valor_base=Decimal(valor),
    )
    db.session.add(tarifa)
    db.session.commit()
    asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data[alumno_key].id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        fecha_inicio=date(2026, 1, 1),
    )
    db.session.commit()
    return academia_id


def crear_obligacion(db, base_data, periodo="2026-09", valor="60.00", alumno_key="alumno_a1"):
    academia_id = crear_plan_base(db, base_data, alumno_key=alumno_key, valor=valor, codigo=f"PLAN_{periodo.replace('-', '_')}_{alumno_key}")
    generar_obligaciones_mensuales(academia_id=academia_id, periodo=periodo)
    db.session.commit()
    return ObligacionFinanciera.query.filter_by(
        academia_id=academia_id,
        alumno_id=base_data[alumno_key].id,
        periodo=periodo,
        tipo_obligacion="PENSION",
    ).one()


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


def test_registrar_pago_valido(db, base_data):
    pago = registrar_pago(
        academia_id=base_data["academia_a"].id,
        alumno_id=base_data["alumno_a1"].id,
        fecha_pago=date(2026, 9, 5),
        valor=Decimal("60.00"),
        medio_pago="efectivo",
        referencia="REC-1",
    )
    db.session.commit()

    assert pago.id is not None
    assert pago.valor == Decimal("60.00")
    assert pago.medio_pago == "EFECTIVO"
    assert pago.estado == "REGISTRADO"


def test_rechazar_pago_menor_o_igual_cero(db, base_data):
    with pytest.raises(FinanzasError, match="mayor a cero"):
        registrar_pago(
            academia_id=base_data["academia_a"].id,
            alumno_id=base_data["alumno_a1"].id,
            fecha_pago=date(2026, 9, 5),
            valor=Decimal("0.00"),
            medio_pago="EFECTIVO",
        )


def test_aplicar_pago_completo_a_obligacion(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(
        academia_id=obligacion.academia_id,
        alumno_id=obligacion.alumno_id,
        fecha_pago=date(2026, 9, 5),
        valor=Decimal("60.00"),
        medio_pago="TRANSFERENCIA",
    )
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("60.00"))
    db.session.commit()

    assert calcular_saldo_pago(academia_id=obligacion.academia_id, pago_id=pago.id) == Decimal("0.00")
    assert calcular_saldo_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == Decimal("0.00")
    assert obtener_estado_pago_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == "PAGADA"


def test_aplicar_pago_parcial(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(
        academia_id=obligacion.academia_id,
        alumno_id=obligacion.alumno_id,
        fecha_pago=date(2026, 9, 5),
        valor=Decimal("30.00"),
        medio_pago="EFECTIVO",
    )
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("30.00"))
    db.session.commit()

    assert calcular_saldo_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == Decimal("30.00")
    assert obtener_estado_pago_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == "PARCIAL"


def test_varios_pagos_sobre_una_obligacion(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.00")
    pago_1 = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("25.00"), medio_pago="EFECTIVO")
    pago_2 = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 6), valor=Decimal("35.00"), medio_pago="DEPOSITO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago_1.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("25.00"))
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago_2.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("35.00"))
    db.session.commit()

    assert calcular_total_pagado_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == Decimal("60.00")
    assert obtener_estado_pago_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == "PAGADA"


def test_un_pago_aplicado_a_varias_obligaciones(db, base_data):
    obligacion_1 = crear_obligacion(db, base_data, periodo="2026-09", valor="40.00")
    obligacion_2 = crear_obligacion_manual(db, obligacion_1, periodo="2026-10", valor="35.00")
    pago = registrar_pago(academia_id=obligacion_1.academia_id, alumno_id=obligacion_1.alumno_id, fecha_pago=date(2026, 10, 5), valor=Decimal("100.00"), medio_pago="TRANSFERENCIA")

    aplicar_pago(academia_id=obligacion_1.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion_1.id, valor_aplicado=Decimal("40.00"))
    aplicar_pago(academia_id=obligacion_1.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion_2.id, valor_aplicado=Decimal("35.00"))
    db.session.commit()

    assert calcular_total_aplicado_pago(academia_id=obligacion_1.academia_id, pago_id=pago.id) == Decimal("75.00")
    assert calcular_saldo_pago(academia_id=obligacion_1.academia_id, pago_id=pago.id) == Decimal("25.00")


def test_obligacion_pendiente(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.00")

    assert obtener_estado_pago_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == "PENDIENTE"


def test_impedir_sobreaplicar_obligacion(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("70.00"), medio_pago="EFECTIVO")

    with pytest.raises(FinanzasError, match="saldo de la obligacion"):
        aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("70.00"))


def test_impedir_usar_mas_saldo_del_disponible_en_pago(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("30.00"), medio_pago="EFECTIVO")

    with pytest.raises(FinanzasError, match="saldo disponible"):
        aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("40.00"))


def test_impedir_aplicar_pago_anulado(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("30.00"), medio_pago="EFECTIVO")
    anular_pago(academia_id=obligacion.academia_id, pago_id=pago.id)
    db.session.commit()

    with pytest.raises(FinanzasError, match="pago anulado"):
        aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("10.00"))


def test_impedir_aplicar_sobre_obligacion_anulada(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.00")
    obligacion.estado = "ANULADA"
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("30.00"), medio_pago="EFECTIVO")
    db.session.commit()

    with pytest.raises(FinanzasError, match="obligacion anulada"):
        aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("10.00"))


def test_aislamiento_entre_academias(db, base_data):
    obligacion_a = crear_obligacion(db, base_data, valor="60.00")
    pago_a = registrar_pago(academia_id=obligacion_a.academia_id, alumno_id=obligacion_a.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("60.00"), medio_pago="EFECTIVO")

    with pytest.raises(FinanzasError, match="Pago no pertenece"):
        aplicar_pago(
            academia_id=base_data["academia_b"].id,
            pago_id=pago_a.id,
            obligacion_financiera_id=obligacion_a.id,
            valor_aplicado=Decimal("10.00"),
        )


def test_mantener_decimal_numeric_correctamente(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.25")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("20.10"), medio_pago="TARJETA")
    aplicacion = aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("20.10"))
    db.session.commit()

    assert isinstance(pago.valor, Decimal)
    assert isinstance(aplicacion.valor_aplicado, Decimal)
    assert calcular_saldo_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == Decimal("40.15")


def test_impedir_referencias_cruzadas_entre_alumnos(db, base_data):
    obligacion_juan = crear_obligacion(db, base_data, alumno_key="alumno_a1", valor="60.00")
    pago_maria = registrar_pago(
        academia_id=obligacion_juan.academia_id,
        alumno_id=base_data["alumno_a2"].id,
        fecha_pago=date(2026, 9, 5),
        valor=Decimal("60.00"),
        medio_pago="EFECTIVO",
    )
    db.session.commit()

    with pytest.raises(FinanzasError, match="no pertenece al alumno"):
        aplicar_pago(
            academia_id=obligacion_juan.academia_id,
            pago_id=pago_maria.id,
            obligacion_financiera_id=obligacion_juan.id,
            valor_aplicado=Decimal("10.00"),
        )


def test_bloquear_anulacion_de_pago_con_aplicaciones(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("20.00"), medio_pago="EFECTIVO")
    aplicar_pago(academia_id=obligacion.academia_id, pago_id=pago.id, obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("20.00"))
    db.session.commit()

    with pytest.raises(FinanzasError, match="pago con aplicaciones"):
        anular_pago(academia_id=obligacion.academia_id, pago_id=pago.id)


def test_constraint_aplicacion_valor_positivo(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("20.00"), medio_pago="EFECTIVO")

    with pytest.raises((IntegrityError, ValueError)):
        aplicacion = PagoAplicacion(
            academia_id=obligacion.academia_id,
            pago_id=pago.id,
            obligacion_financiera_id=obligacion.id,
            valor_aplicado=Decimal("0.00"),
        )
        db.session.add(aplicacion)
        db.session.flush()


def test_modelo_pago_financiero_no_reemplaza_pago_legacy(db, base_data):
    pago = registrar_pago(
        academia_id=base_data["academia_a"].id,
        alumno_id=base_data["alumno_a1"].id,
        fecha_pago=date(2026, 9, 5),
        valor=Decimal("60.00"),
        medio_pago="OTRO",
    )
    db.session.commit()

    assert PagoFinanciero.query.filter_by(id=pago.id).one().valor == Decimal("60.00")


def test_aplicar_multiples_obligaciones_atomicamente(db, base_data):
    obligacion_1 = crear_obligacion(db, base_data, periodo="2026-09", valor="40.00")
    obligacion_2 = crear_obligacion_manual(db, obligacion_1, periodo="2026-10", valor="35.00")
    pago = registrar_pago(academia_id=obligacion_1.academia_id, alumno_id=obligacion_1.alumno_id, fecha_pago=date(2026, 10, 5), valor=Decimal("75.00"), medio_pago="TRANSFERENCIA")

    creadas = aplicar_pago_a_obligaciones(
        academia_id=obligacion_1.academia_id,
        pago_id=pago.id,
        aplicaciones=[
            {"obligacion_financiera_id": obligacion_1.id, "valor_aplicado": "40.00"},
            {"obligacion_financiera_id": obligacion_2.id, "valor_aplicado": "35.00"},
        ],
    )
    db.session.commit()

    assert len(creadas) == 2
    assert calcular_saldo_pago(academia_id=obligacion_1.academia_id, pago_id=pago.id) == Decimal("0.00")
    assert obtener_estado_pago_obligacion(academia_id=obligacion_1.academia_id, obligacion_financiera_id=obligacion_1.id) == "PAGADA"
    assert obtener_estado_pago_obligacion(academia_id=obligacion_2.academia_id, obligacion_financiera_id=obligacion_2.id) == "PAGADA"


def test_lote_suma_superior_a_saldo_pago_no_persiste_nada(db, base_data):
    obligacion_1 = crear_obligacion(db, base_data, periodo="2026-09", valor="40.00")
    obligacion_2 = crear_obligacion_manual(db, obligacion_1, periodo="2026-10", valor="35.00")
    pago = registrar_pago(academia_id=obligacion_1.academia_id, alumno_id=obligacion_1.alumno_id, fecha_pago=date(2026, 10, 5), valor=Decimal("50.00"), medio_pago="TRANSFERENCIA")

    with pytest.raises(FinanzasError, match="saldo disponible"):
        aplicar_pago_a_obligaciones(
            academia_id=obligacion_1.academia_id,
            pago_id=pago.id,
            aplicaciones=[
                {"obligacion_financiera_id": obligacion_1.id, "valor_aplicado": "40.00"},
                {"obligacion_financiera_id": obligacion_2.id, "valor_aplicado": "35.00"},
            ],
        )

    assert PagoAplicacion.query.filter_by(academia_id=obligacion_1.academia_id, pago_id=pago.id).count() == 0


def test_lote_con_obligacion_invalida_no_persiste_nada(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="40.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("40.00"), medio_pago="EFECTIVO")

    with pytest.raises(FinanzasError, match="Obligacion no pertenece"):
        aplicar_pago_a_obligaciones(
            academia_id=obligacion.academia_id,
            pago_id=pago.id,
            aplicaciones=[
                {"obligacion_financiera_id": obligacion.id, "valor_aplicado": "10.00"},
                {"obligacion_financiera_id": 999999, "valor_aplicado": "10.00"},
            ],
        )

    assert PagoAplicacion.query.filter_by(academia_id=obligacion.academia_id, pago_id=pago.id).count() == 0


def test_lote_con_obligacion_de_otro_alumno_no_persiste_nada(db, base_data):
    obligacion_juan = crear_obligacion(db, base_data, alumno_key="alumno_a1", valor="40.00")
    obligacion_maria = ObligacionFinanciera(
        academia_id=obligacion_juan.academia_id,
        alumno_id=base_data["alumno_a2"].id,
        periodo="2026-10",
        tipo_obligacion="PENSION",
        concepto="Pension 2026-10",
        origen="TEST",
        fecha_emision=date(2026, 10, 1),
        tarifa_base_snapshot=Decimal("35.00"),
        valor_descuento_snapshot=Decimal("0.00"),
        valor_final_snapshot=Decimal("35.00"),
        moneda_snapshot="USD",
        estado="PENDIENTE",
    )
    db.session.add(obligacion_maria)
    db.session.flush()
    pago = registrar_pago(academia_id=obligacion_juan.academia_id, alumno_id=obligacion_juan.alumno_id, fecha_pago=date(2026, 10, 5), valor=Decimal("75.00"), medio_pago="EFECTIVO")

    with pytest.raises(FinanzasError, match="no pertenece al alumno"):
        aplicar_pago_a_obligaciones(
            academia_id=obligacion_juan.academia_id,
            pago_id=pago.id,
            aplicaciones=[
                {"obligacion_financiera_id": obligacion_juan.id, "valor_aplicado": "40.00"},
                {"obligacion_financiera_id": obligacion_maria.id, "valor_aplicado": "35.00"},
            ],
        )

    assert PagoAplicacion.query.filter_by(academia_id=obligacion_juan.academia_id, pago_id=pago.id).count() == 0


def test_lote_con_obligacion_de_otro_tenant_no_persiste_nada(db, base_data):
    obligacion_a = crear_obligacion(db, base_data, valor="40.00")
    obligacion_b = ObligacionFinanciera(
        academia_id=base_data["academia_b"].id,
        alumno_id=base_data["alumno_b1"].id,
        periodo="2026-09",
        tipo_obligacion="PENSION",
        concepto="Pension 2026-09",
        origen="TEST",
        fecha_emision=date(2026, 9, 1),
        tarifa_base_snapshot=Decimal("35.00"),
        valor_descuento_snapshot=Decimal("0.00"),
        valor_final_snapshot=Decimal("35.00"),
        moneda_snapshot="USD",
        estado="PENDIENTE",
    )
    db.session.add(obligacion_b)
    db.session.flush()
    pago = registrar_pago(academia_id=obligacion_a.academia_id, alumno_id=obligacion_a.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("75.00"), medio_pago="EFECTIVO")

    with pytest.raises(FinanzasError, match="Obligacion no pertenece"):
        aplicar_pago_a_obligaciones(
            academia_id=obligacion_a.academia_id,
            pago_id=pago.id,
            aplicaciones=[
                {"obligacion_financiera_id": obligacion_a.id, "valor_aplicado": "40.00"},
                {"obligacion_financiera_id": obligacion_b.id, "valor_aplicado": "35.00"},
            ],
        )

    assert PagoAplicacion.query.filter_by(academia_id=obligacion_a.academia_id, pago_id=pago.id).count() == 0


def test_lote_con_pago_anulado_no_persiste_nada(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="40.00")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor=Decimal("40.00"), medio_pago="EFECTIVO")
    anular_pago(academia_id=obligacion.academia_id, pago_id=pago.id)
    db.session.commit()

    with pytest.raises(FinanzasError, match="pago anulado"):
        aplicar_pago_a_obligaciones(
            academia_id=obligacion.academia_id,
            pago_id=pago.id,
            aplicaciones=[{"obligacion_financiera_id": obligacion.id, "valor_aplicado": "40.00"}],
        )

    assert PagoAplicacion.query.filter_by(academia_id=obligacion.academia_id, pago_id=pago.id).count() == 0


def test_lote_con_obligacion_anulada_no_persiste_nada(db, base_data):
    obligacion_1 = crear_obligacion(db, base_data, periodo="2026-09", valor="40.00")
    obligacion_2 = crear_obligacion_manual(db, obligacion_1, periodo="2026-10", valor="35.00")
    obligacion_2.estado = "ANULADA"
    pago = registrar_pago(academia_id=obligacion_1.academia_id, alumno_id=obligacion_1.alumno_id, fecha_pago=date(2026, 10, 5), valor=Decimal("75.00"), medio_pago="EFECTIVO")
    db.session.commit()

    with pytest.raises(FinanzasError, match="obligacion anulada"):
        aplicar_pago_a_obligaciones(
            academia_id=obligacion_1.academia_id,
            pago_id=pago.id,
            aplicaciones=[
                {"obligacion_financiera_id": obligacion_1.id, "valor_aplicado": "40.00"},
                {"obligacion_financiera_id": obligacion_2.id, "valor_aplicado": "35.00"},
            ],
        )

    assert PagoAplicacion.query.filter_by(academia_id=obligacion_1.academia_id, pago_id=pago.id).count() == 0


def test_lote_mantiene_decimal(db, base_data):
    obligacion = crear_obligacion(db, base_data, valor="60.25")
    pago = registrar_pago(academia_id=obligacion.academia_id, alumno_id=obligacion.alumno_id, fecha_pago=date(2026, 9, 5), valor="20.10", medio_pago="TARJETA")

    creadas = aplicar_pago_a_obligaciones(
        academia_id=obligacion.academia_id,
        pago_id=pago.id,
        aplicaciones=[{"obligacion_financiera_id": obligacion.id, "valor_aplicado": "20.10"}],
    )
    db.session.commit()

    assert isinstance(creadas[0].valor_aplicado, Decimal)
    assert calcular_saldo_obligacion(academia_id=obligacion.academia_id, obligacion_financiera_id=obligacion.id) == Decimal("40.15")


def test_registrar_pago_rechaza_valor_no_numerico(db, base_data):
    with pytest.raises(FinanzasError, match="numero valido"):
        registrar_pago(
            academia_id=base_data["academia_a"].id,
            alumno_id=base_data["alumno_a1"].id,
            fecha_pago=date(2026, 9, 5),
            valor="abc",
            medio_pago="EFECTIVO",
        )


def test_registrar_pago_rechaza_mas_de_dos_decimales(db, base_data):
    with pytest.raises(FinanzasError, match="2 decimales"):
        registrar_pago(
            academia_id=base_data["academia_a"].id,
            alumno_id=base_data["alumno_a1"].id,
            fecha_pago=date(2026, 9, 5),
            valor="10.999",
            medio_pago="EFECTIVO",
        )


def test_registrar_pago_rechaza_medio_invalido(db, base_data):
    with pytest.raises(FinanzasError, match="Medio de pago invalido"):
        registrar_pago(
            academia_id=base_data["academia_a"].id,
            alumno_id=base_data["alumno_a1"].id,
            fecha_pago=date(2026, 9, 5),
            valor="10.00",
            medio_pago="CHEQUE",
        )


def test_registrar_pago_rechaza_moneda_invalida(db, base_data):
    with pytest.raises(FinanzasError, match="codigo ISO"):
        registrar_pago(
            academia_id=base_data["academia_a"].id,
            alumno_id=base_data["alumno_a1"].id,
            fecha_pago=date(2026, 9, 5),
            valor="10.00",
            medio_pago="EFECTIVO",
            moneda="US",
        )
