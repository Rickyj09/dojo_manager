from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.alumno import Alumno
from app.models.finanzas import (
    AlumnoPlanFinanciero,
    ConfiguracionFinanciera,
    FrecuenciaEntrenamiento,
    ObligacionFinanciera,
    PlanFinanciero,
    TarifaPlan,
    Tarifario,
)
from app.services.finanzas.asignaciones import asignar_plan_financiero
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.obligaciones import generar_obligaciones_mensuales, parsear_periodo
from app.services.finanzas.vencimientos import calcular_fecha_vencimiento_pension


def crear_plan(db, academia_id, codigo="REGULAR"):
    plan = PlanFinanciero(academia_id=academia_id, codigo=codigo, nombre=codigo)
    db.session.add(plan)
    db.session.flush()
    return plan


def crear_frecuencia(db, academia_id, codigo="D3", dias=3):
    frecuencia = FrecuenciaEntrenamiento(
        academia_id=academia_id,
        codigo=codigo,
        nombre=f"{dias} dias",
        dias_semana=dias,
    )
    db.session.add(frecuencia)
    db.session.flush()
    return frecuencia


def crear_tarifario(db, academia_id):
    tarifario = Tarifario(
        academia_id=academia_id,
        nombre="Tarifario pension",
        fecha_inicio_vigencia=date(2026, 1, 1),
        estado="VIGENTE",
        moneda="USD",
    )
    db.session.add(tarifario)
    db.session.flush()
    return tarifario


def crear_tarifa(db, academia_id, tarifario, plan, frecuencia, valor="60.00"):
    tarifa = TarifaPlan(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        valor_base=Decimal(valor),
    )
    db.session.add(tarifa)
    db.session.flush()
    return tarifa


def preparar_asignacion(db, base_data, alumno_key="alumno_a1", valor="60.00"):
    academia_id = base_data["academia_a"].id
    plan = crear_plan(db, academia_id)
    frecuencia = crear_frecuencia(db, academia_id)
    tarifario = crear_tarifario(db, academia_id)
    crear_tarifa(db, academia_id, tarifario, plan, frecuencia, valor)
    db.session.commit()
    asignacion = asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data[alumno_key].id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        fecha_inicio=date(2026, 1, 1),
        usuario_id=base_data["admin_a"].id,
    )
    db.session.commit()
    return academia_id, asignacion


def test_genera_pension_correctamente(db, base_data):
    academia_id, _asignacion = preparar_asignacion(db, base_data)

    resumen = generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    obligacion = ObligacionFinanciera.query.filter_by(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        periodo="2026-09",
        tipo_obligacion="PENSION",
    ).one()
    assert resumen.evaluados == 2
    assert resumen.creados == 1
    assert resumen.sin_plan == 1
    assert obligacion.concepto == "Pension 2026-09"
    assert obligacion.estado == "PENDIENTE"
    assert obligacion.fecha_emision == date(2026, 9, 1)
    assert obligacion.fecha_vencimiento is None


def test_dia_10_genera_vencimiento_dia_10(db, base_data):
    academia_id, _asignacion = preparar_asignacion(db, base_data)
    db.session.add(ConfiguracionFinanciera(academia_id=academia_id, dia_vencimiento_pension=10))
    db.session.commit()

    generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    obligacion = ObligacionFinanciera.query.filter_by(academia_id=academia_id, periodo="2026-09").one()
    assert obligacion.fecha_vencimiento == date(2026, 9, 10)


@pytest.mark.parametrize(
    "periodo,fecha_esperada",
    [
        ("2026-01", date(2026, 1, 31)),
        ("2026-04", date(2026, 4, 30)),
        ("2026-02", date(2026, 2, 28)),
        ("2028-02", date(2028, 2, 29)),
    ],
)
def test_dia_31_usa_ultimo_dia_valido_del_mes(periodo, fecha_esperada):
    assert calcular_fecha_vencimiento_pension(periodo, 31) == fecha_esperada


def test_configuracion_null_deja_fecha_vencimiento_null(db, base_data):
    academia_id, _asignacion = preparar_asignacion(db, base_data)
    db.session.add(ConfiguracionFinanciera(academia_id=academia_id, dia_vencimiento_pension=None))
    db.session.commit()

    generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    obligacion = ObligacionFinanciera.query.filter_by(academia_id=academia_id, periodo="2026-09").one()
    assert obligacion.fecha_vencimiento is None


@pytest.mark.parametrize("dia_invalido", [0, 32])
def test_dia_vencimiento_invalido_rechazado(db, base_data, dia_invalido):
    with pytest.raises(ValueError, match="entre 1 y 31"):
        ConfiguracionFinanciera(
            academia_id=base_data["academia_a"].id,
            dia_vencimiento_pension=dia_invalido,
        )


def test_generacion_repetida_no_actualiza_vencimiento_existente(db, base_data):
    academia_id, _asignacion = preparar_asignacion(db, base_data)

    generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.add(ConfiguracionFinanciera(academia_id=academia_id, dia_vencimiento_pension=10))
    db.session.commit()
    generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    obligacion = ObligacionFinanciera.query.filter_by(academia_id=academia_id, periodo="2026-09").one()
    assert obligacion.fecha_vencimiento is None


def test_copia_snapshots_desde_alumno_plan_financiero(db, base_data):
    academia_id, asignacion = preparar_asignacion(db, base_data, valor="75.00")

    generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    obligacion = ObligacionFinanciera.query.filter_by(alumno_plan_financiero_id=asignacion.id).one()
    assert obligacion.tarifa_base_snapshot == asignacion.tarifa_base_snapshot
    assert obligacion.porcentaje_descuento_snapshot == asignacion.descuento_porcentaje_snapshot
    assert obligacion.valor_descuento_snapshot == asignacion.descuento_valor_snapshot
    assert obligacion.valor_final_snapshot == asignacion.valor_final_snapshot
    assert obligacion.moneda_snapshot == asignacion.moneda_snapshot


def test_conserva_decimal(db, base_data):
    academia_id, _asignacion = preparar_asignacion(db, base_data, valor="60.25")

    generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    obligacion = ObligacionFinanciera.query.filter_by(alumno_id=base_data["alumno_a1"].id).one()
    assert isinstance(obligacion.valor_final_snapshot, Decimal)
    assert obligacion.valor_final_snapshot == Decimal("60.25")


def test_generacion_repetida_no_duplica(db, base_data):
    academia_id, _asignacion = preparar_asignacion(db, base_data)

    resumen_1 = generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()
    resumen_2 = generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    assert resumen_1.creados == 1
    assert resumen_2.creados == 0
    assert resumen_2.existentes == 1
    assert ObligacionFinanciera.query.filter_by(academia_id=academia_id, periodo="2026-09").count() == 1


def test_dos_periodos_diferentes_generan_dos_obligaciones(db, base_data):
    academia_id, _asignacion = preparar_asignacion(db, base_data)

    generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-10")
    db.session.commit()

    assert ObligacionFinanciera.query.filter_by(academia_id=academia_id, alumno_id=base_data["alumno_a1"].id).count() == 2


def test_dos_alumnos_generan_obligaciones_independientes(db, base_data):
    academia_id, _ = preparar_asignacion(db, base_data, alumno_key="alumno_a1", valor="60.00")
    plan = PlanFinanciero.query.filter_by(academia_id=academia_id, codigo="REGULAR").one()
    frecuencia = FrecuenciaEntrenamiento.query.filter_by(academia_id=academia_id, codigo="D3").one()
    asignar_plan_financiero(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a2"].id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        fecha_inicio=date(2026, 1, 1),
    )
    db.session.commit()

    resumen = generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    assert resumen.creados == 2
    assert ObligacionFinanciera.query.filter_by(academia_id=academia_id, periodo="2026-09").count() == 2


def test_alumno_sin_plan_no_genera_importe_inventado(db, base_data):
    academia_id = base_data["academia_a"].id

    resumen = generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    assert resumen.evaluados == 2
    assert resumen.creados == 0
    assert resumen.sin_plan == 2
    assert ObligacionFinanciera.query.filter_by(academia_id=academia_id).count() == 0


def test_aislamiento_entre_academias(db, base_data):
    academia_a_id, _ = preparar_asignacion(db, base_data)
    academia_b_id = base_data["academia_b"].id
    plan_b = crear_plan(db, academia_b_id)
    frecuencia_b = crear_frecuencia(db, academia_b_id)
    tarifario_b = crear_tarifario(db, academia_b_id)
    crear_tarifa(db, academia_b_id, tarifario_b, plan_b, frecuencia_b, "80.00")
    db.session.commit()
    asignar_plan_financiero(
        academia_id=academia_b_id,
        alumno_id=base_data["alumno_b1"].id,
        plan_id=plan_b.id,
        frecuencia_id=frecuencia_b.id,
        fecha_inicio=date(2026, 1, 1),
    )
    db.session.commit()

    generar_obligaciones_mensuales(academia_id=academia_a_id, periodo="2026-09")
    db.session.commit()

    assert ObligacionFinanciera.query.filter_by(academia_id=academia_a_id).count() == 1
    assert ObligacionFinanciera.query.filter_by(academia_id=academia_b_id).count() == 0


def test_snapshot_historico_no_cambia_si_plan_cambia_despues(db, base_data):
    academia_id, asignacion = preparar_asignacion(db, base_data, valor="60.00")
    generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    asignacion.valor_final_snapshot = Decimal("99.00")
    db.session.commit()

    obligacion = ObligacionFinanciera.query.filter_by(academia_id=academia_id, periodo="2026-09").one()
    assert obligacion.valor_final_snapshot == Decimal("60.00")


def test_validacion_periodo_invalido():
    with pytest.raises(FinanzasError, match="YYYY-MM"):
        parsear_periodo("2026-13")

    with pytest.raises(FinanzasError, match="YYYY-MM"):
        parsear_periodo("septiembre-2026")


def test_cli_periodo_invalido(app):
    runner = app.test_cli_runner()

    result = runner.invoke(args=["finanzas", "generar-pensiones", "--academia-id", "1", "--periodo", "2026-13"])

    assert result.exit_code != 0
    assert "YYYY-MM" in result.output


def test_constraint_idempotencia(db, base_data):
    academia_id, asignacion = preparar_asignacion(db, base_data)
    obligacion_1 = ObligacionFinanciera(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        alumno_plan_financiero_id=asignacion.id,
        periodo="2026-09",
        tipo_obligacion="PENSION",
        concepto="Pension 2026-09",
        origen="TEST",
        fecha_emision=date(2026, 9, 1),
        tarifa_base_snapshot=Decimal("60.00"),
        valor_descuento_snapshot=Decimal("0.00"),
        valor_final_snapshot=Decimal("60.00"),
        moneda_snapshot="USD",
        estado="PENDIENTE",
    )
    obligacion_2 = ObligacionFinanciera(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        alumno_plan_financiero_id=asignacion.id,
        periodo="2026-09",
        tipo_obligacion="PENSION",
        concepto="Pension 2026-09 duplicada",
        origen="TEST",
        fecha_emision=date(2026, 9, 1),
        tarifa_base_snapshot=Decimal("60.00"),
        valor_descuento_snapshot=Decimal("0.00"),
        valor_final_snapshot=Decimal("60.00"),
        moneda_snapshot="USD",
        estado="PENDIENTE",
    )
    db.session.add_all([obligacion_1, obligacion_2])

    with pytest.raises(IntegrityError):
        db.session.commit()


def test_obligacion_anulada_bloquea_regeneracion_automatica(db, base_data):
    academia_id, asignacion = preparar_asignacion(db, base_data)
    anulada = ObligacionFinanciera(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        alumno_plan_financiero_id=asignacion.id,
        periodo="2026-09",
        tipo_obligacion="PENSION",
        concepto="Pension 2026-09 anulada",
        origen="TEST",
        fecha_emision=date(2026, 9, 1),
        tarifa_base_snapshot=Decimal("60.00"),
        valor_descuento_snapshot=Decimal("0.00"),
        valor_final_snapshot=Decimal("60.00"),
        moneda_snapshot="USD",
        estado="ANULADA",
    )
    db.session.add(anulada)
    db.session.commit()

    resumen = generar_obligaciones_mensuales(academia_id=academia_id, periodo="2026-09")
    db.session.commit()

    assert resumen.creados == 0
    assert resumen.existentes == 1
    assert ObligacionFinanciera.query.filter_by(academia_id=academia_id, periodo="2026-09").count() == 1
