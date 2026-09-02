from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.finanzas import (
    FrecuenciaEntrenamiento,
    PlanFinanciero,
    ReglaDescuento,
    TarifaPlan,
    Tarifario,
)
from app.services.finanzas.tarifas import calcular_tarifa, redondear_dinero


def _crear_tarifario_base(db, academia_id):
    tarifario = Tarifario(
        academia_id=academia_id,
        nombre="Tarifario 2026-2027",
        fecha_inicio_vigencia=date(2026, 9, 1),
        estado="VIGENTE",
        moneda="USD",
    )
    db.session.add(tarifario)
    db.session.flush()
    return tarifario


def _crear_plan(db, academia_id, codigo, nombre=None):
    plan = PlanFinanciero(
        academia_id=academia_id,
        codigo=codigo,
        nombre=nombre or codigo.title(),
    )
    db.session.add(plan)
    db.session.flush()
    return plan


def _crear_frecuencia(db, academia_id, codigo, dias):
    frecuencia = FrecuenciaEntrenamiento(
        academia_id=academia_id,
        codigo=codigo,
        nombre=f"{dias} dias",
        dias_semana=dias,
    )
    db.session.add(frecuencia)
    db.session.flush()
    return frecuencia


def _crear_tarifa(db, academia_id, tarifario, plan, frecuencia, valor):
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


def _crear_regla(db, academia_id, codigo, porcentaje, cantidad_minima):
    regla = ReglaDescuento(
        academia_id=academia_id,
        codigo=codigo,
        nombre=codigo,
        tipo="HERMANOS",
        porcentaje=Decimal(porcentaje),
        cantidad_minima=cantidad_minima,
    )
    db.session.add(regla)
    db.session.flush()
    return regla


def test_plan_financiero_aislado_por_academia(db, base_data):
    academia_a_id = base_data["academia_a"].id
    academia_b_id = base_data["academia_b"].id
    _crear_plan(db, academia_a_id, "regular")
    _crear_plan(db, academia_b_id, "desarrollo")
    db.session.commit()

    planes_a = PlanFinanciero.query.filter_by(academia_id=academia_a_id).all()
    planes_b = PlanFinanciero.query.filter_by(academia_id=academia_b_id).all()

    assert [plan.codigo for plan in planes_a] == ["REGULAR"]
    assert [plan.codigo for plan in planes_b] == ["DESARROLLO"]


def test_mismo_codigo_permitido_en_academias_distintas(db, base_data):
    _crear_plan(db, base_data["academia_a"].id, "REGULAR")
    _crear_plan(db, base_data["academia_b"].id, "regular")
    db.session.commit()

    assert PlanFinanciero.query.filter_by(codigo="REGULAR").count() == 2


def test_mismo_codigo_prohibido_dentro_de_la_misma_academia(db, base_data):
    academia_id = base_data["academia_a"].id
    _crear_plan(db, academia_id, "regular")

    with pytest.raises(IntegrityError):
        _crear_plan(db, academia_id, "REGULAR")


def test_tarifario_aislado_por_academia(db, base_data):
    tarifario_a = _crear_tarifario_base(db, base_data["academia_a"].id)
    tarifario_b = _crear_tarifario_base(db, base_data["academia_b"].id)
    db.session.commit()

    assert tarifario_a.academia_id != tarifario_b.academia_id
    assert Tarifario.query.filter_by(academia_id=base_data["academia_a"].id).count() == 1


def test_tarifa_plan_no_permite_cruzar_plan_de_otra_academia(db, base_data):
    academia_a_id = base_data["academia_a"].id
    academia_b_id = base_data["academia_b"].id
    tarifario_a = _crear_tarifario_base(db, academia_a_id)
    plan_b = _crear_plan(db, academia_b_id, "REGULAR")
    frecuencia_a = _crear_frecuencia(db, academia_a_id, "D3", 3)
    tarifa = TarifaPlan(
        academia_id=academia_a_id,
        tarifario_id=tarifario_a.id,
        plan_id=plan_b.id,
        frecuencia_id=frecuencia_a.id,
        valor_base=Decimal("60.00"),
    )
    db.session.add(tarifa)

    with pytest.raises(ValueError, match="otra academia"):
        db.session.commit()


def test_tarifa_plan_no_permite_cruzar_frecuencia_de_otra_academia(db, base_data):
    academia_a_id = base_data["academia_a"].id
    academia_b_id = base_data["academia_b"].id
    tarifario_a = _crear_tarifario_base(db, academia_a_id)
    plan_a = _crear_plan(db, academia_a_id, "REGULAR")
    frecuencia_b = _crear_frecuencia(db, academia_b_id, "D3", 3)
    tarifa = TarifaPlan(
        academia_id=academia_a_id,
        tarifario_id=tarifario_a.id,
        plan_id=plan_a.id,
        frecuencia_id=frecuencia_b.id,
        valor_base=Decimal("60.00"),
    )
    db.session.add(tarifa)

    with pytest.raises(ValueError, match="otra academia"):
        db.session.commit()


def test_valor_financiero_usa_decimal(db, base_data):
    academia_id = base_data["academia_a"].id
    tarifario = _crear_tarifario_base(db, academia_id)
    plan = _crear_plan(db, academia_id, "REGULAR")
    frecuencia = _crear_frecuencia(db, academia_id, "D2", 2)
    _crear_tarifa(db, academia_id, tarifario, plan, frecuencia, "55.00")
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
    )

    assert isinstance(resultado.tarifa_base, Decimal)
    assert resultado.valor_final == Decimal("55.00")


def test_regla_10_por_ciento(db, base_data):
    academia_id = base_data["academia_a"].id
    tarifario = _crear_tarifario_base(db, academia_id)
    plan = _crear_plan(db, academia_id, "REGULAR")
    frecuencia = _crear_frecuencia(db, academia_id, "D2", 2)
    _crear_tarifa(db, academia_id, tarifario, plan, frecuencia, "55.00")
    regla = _crear_regla(db, academia_id, "HERMANOS_2", "10.00", 2)
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={"reglas_descuento_ids": [regla.id], "cantidad_alumnos": 2},
    )

    assert resultado.valor_final == Decimal("49.50")
    assert resultado.descuentos_aplicados[0]["descuento"] == Decimal("5.50")


def test_regla_15_por_ciento(db, base_data):
    academia_id = base_data["academia_a"].id
    tarifario = _crear_tarifario_base(db, academia_id)
    plan = _crear_plan(db, academia_id, "REGULAR")
    frecuencia = _crear_frecuencia(db, academia_id, "D2", 2)
    _crear_tarifa(db, academia_id, tarifario, plan, frecuencia, "55.00")
    regla = _crear_regla(db, academia_id, "HERMANOS_3", "15.00", 3)
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
        contexto_descuentos={"reglas_descuento_ids": [regla.id], "cantidad_alumnos": 3},
    )

    assert resultado.valor_final == Decimal("46.75")


def test_redondeo_financiero_definido():
    assert redondear_dinero(Decimal("33.335")) == Decimal("33.34")


def test_borjas_lions_demuestra_necesidad_de_override_oficial():
    valor_matematico = redondear_dinero(Decimal("55.00") * Decimal("0.85"))
    valor_oficial_publicado = Decimal("47.00")

    assert valor_matematico == Decimal("46.75")
    assert valor_matematico != valor_oficial_publicado


def test_tarifario_historico_no_se_modifica_por_calculo(db, base_data):
    academia_id = base_data["academia_a"].id
    tarifario = _crear_tarifario_base(db, academia_id)
    plan = _crear_plan(db, academia_id, "DESARROLLO")
    frecuencia = _crear_frecuencia(db, academia_id, "D4", 4)
    tarifa = _crear_tarifa(db, academia_id, tarifario, plan, frecuencia, "75.00")
    db.session.commit()

    resultado = calcular_tarifa(
        academia_id=academia_id,
        tarifario_id=tarifario.id,
        plan_id=plan.id,
        frecuencia_id=frecuencia.id,
    )

    assert resultado.valor_final == Decimal("75.00")
    assert tarifa.valor_base == Decimal("75.00")
    assert tarifario.fecha_inicio_vigencia == date(2026, 9, 1)


def test_academia_a_no_puede_calcular_tarifa_de_academia_b(db, base_data):
    academia_a_id = base_data["academia_a"].id
    academia_b_id = base_data["academia_b"].id
    tarifario_b = _crear_tarifario_base(db, academia_b_id)
    plan_b = _crear_plan(db, academia_b_id, "REGULAR")
    frecuencia_b = _crear_frecuencia(db, academia_b_id, "D2", 2)
    _crear_tarifa(db, academia_b_id, tarifario_b, plan_b, frecuencia_b, "55.00")
    db.session.commit()

    with pytest.raises(ValueError, match="No existe una tarifa activa"):
        calcular_tarifa(
            academia_id=academia_a_id,
            tarifario_id=tarifario_b.id,
            plan_id=plan_b.id,
            frecuencia_id=frecuencia_b.id,
        )


def test_casos_base_borjas_lions_como_fixture_de_prueba(db, base_data):
    academia_id = base_data["academia_a"].id
    tarifario = _crear_tarifario_base(db, academia_id)
    casos = [
        ("REGULAR", "D2", 2, "55.00"),
        ("REGULAR", "D3", 3, "60.00"),
        ("DESARROLLO", "D4", 4, "75.00"),
        ("PREMIUM", "D3", 3, "95.00"),
        ("PREMIUM_PLUS", "D2", 2, "125.00"),
        ("ELITE", "D5", 5, "75.00"),
    ]

    for plan_codigo, frecuencia_codigo, dias, valor in casos:
        plan = PlanFinanciero.query.filter_by(academia_id=academia_id, codigo=plan_codigo).first()
        if plan is None:
            plan = _crear_plan(db, academia_id, plan_codigo)
        frecuencia = FrecuenciaEntrenamiento.query.filter_by(
            academia_id=academia_id,
            codigo=frecuencia_codigo,
        ).first()
        if frecuencia is None:
            frecuencia = _crear_frecuencia(db, academia_id, frecuencia_codigo, dias)
        _crear_tarifa(db, academia_id, tarifario, plan, frecuencia, valor)

    db.session.commit()

    for plan_codigo, frecuencia_codigo, _dias, valor in casos:
        plan = PlanFinanciero.query.filter_by(academia_id=academia_id, codigo=plan_codigo).one()
        frecuencia = FrecuenciaEntrenamiento.query.filter_by(
            academia_id=academia_id,
            codigo=frecuencia_codigo,
        ).one()
        resultado = calcular_tarifa(
            academia_id=academia_id,
            tarifario_id=tarifario.id,
            plan_id=plan.id,
            frecuencia_id=frecuencia.id,
        )
        assert resultado.valor_final == Decimal(valor)
