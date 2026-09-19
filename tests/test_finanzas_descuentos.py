from decimal import Decimal

import pytest

from app.services.finanzas.descuentos import (
    alternar_regla_descuento,
    guardar_regla_descuento,
)
from app.services.finanzas.familias import FinanzasError


def datos_regla(**cambios):
    datos = {
        "codigo": "HERMANOS-2",
        "nombre": "Hermanos 2",
        "tipo": "HERMANOS",
        "porcentaje": "10.00",
        "valor_fijo": "",
        "cantidad_minima": "2",
        "decimales_redondeo": "2",
        "requiere_autorizacion": False,
        "vigencia_desde": "",
        "vigencia_hasta": "",
    }
    datos.update(cambios)
    return datos


def test_crear_regla_porcentaje(db, base_data):
    regla = guardar_regla_descuento(
        academia_id=base_data["academia_a"].id,
        datos=datos_regla(),
    )
    db.session.commit()

    assert regla.codigo == "HERMANOS_2"
    assert regla.tipo == "HERMANOS"
    assert regla.porcentaje == Decimal("10.00")
    assert regla.valor_fijo is None
    assert regla.cantidad_minima == 2
    assert regla.activo is True


def test_crear_regla_valor_fijo(db, base_data):
    regla = guardar_regla_descuento(
        academia_id=base_data["academia_a"].id,
        datos=datos_regla(
            codigo="BECA-FIJA",
            nombre="Beca fija",
            tipo="BECA",
            porcentaje="",
            valor_fijo="20.00",
            cantidad_minima="99",
        ),
    )
    db.session.commit()

    assert regla.tipo == "BECA"
    assert regla.porcentaje is None
    assert regla.valor_fijo == Decimal("20.00")
    assert regla.cantidad_minima is None


@pytest.mark.parametrize(
    "cambios",
    [
        {"porcentaje": "", "valor_fijo": ""},
        {"porcentaje": "10", "valor_fijo": "5"},
        {"porcentaje": "0"},
        {"porcentaje": "-1"},
        {"porcentaje": "101"},
        {"valor_fijo": "-1", "porcentaje": ""},
        {"valor_fijo": "0", "porcentaje": ""},
    ],
)
def test_rechaza_modo_descuento_invalido(
    db,
    base_data,
    cambios,
):
    with pytest.raises(FinanzasError):
        guardar_regla_descuento(
            academia_id=base_data["academia_a"].id,
            datos=datos_regla(**cambios),
        )


@pytest.mark.parametrize(
    "cantidad",
    ["", "0", "1"],
)
def test_hermanos_requiere_minimo_dos(
    db,
    base_data,
    cantidad,
):
    with pytest.raises(FinanzasError, match="al menos 2"):
        guardar_regla_descuento(
            academia_id=base_data["academia_a"].id,
            datos=datos_regla(
                cantidad_minima=cantidad,
            ),
        )


def test_beca_ignora_cantidad_minima(db, base_data):
    regla = guardar_regla_descuento(
        academia_id=base_data["academia_a"].id,
        datos=datos_regla(
            codigo="BECA-20",
            nombre="Beca",
            tipo="BECA",
            cantidad_minima="10",
        ),
    )

    assert regla.cantidad_minima is None


def test_rechaza_tipo_invalido(db, base_data):
    with pytest.raises(FinanzasError, match="tipo"):
        guardar_regla_descuento(
            academia_id=base_data["academia_a"].id,
            datos=datos_regla(tipo="DESCONOCIDO"),
        )


def test_rechaza_fechas_incoherentes(db, base_data):
    with pytest.raises(FinanzasError, match="fecha final"):
        guardar_regla_descuento(
            academia_id=base_data["academia_a"].id,
            datos=datos_regla(
                vigencia_desde="2026-10-01",
                vigencia_hasta="2026-09-01",
            ),
        )


@pytest.mark.parametrize("decimales", ["-1", "5"])
def test_rechaza_decimales_fuera_de_rango(
    db,
    base_data,
    decimales,
):
    with pytest.raises(FinanzasError, match="entre 0 y 4"):
        guardar_regla_descuento(
            academia_id=base_data["academia_a"].id,
            datos=datos_regla(
                decimales_redondeo=decimales,
            ),
        )


def test_editar_no_cambia_codigo(db, base_data):
    regla = guardar_regla_descuento(
        academia_id=base_data["academia_a"].id,
        datos=datos_regla(),
    )
    db.session.flush()

    guardar_regla_descuento(
        academia_id=base_data["academia_a"].id,
        regla=regla,
        datos=datos_regla(
            codigo="MANIPULADO",
            nombre="Nueva descripción",
            porcentaje="15.00",
        ),
    )

    assert regla.codigo == "HERMANOS_2"
    assert regla.nombre == "Nueva descripción"
    assert regla.porcentaje == Decimal("15.00")


def test_alternar_activo(db, base_data):
    regla = guardar_regla_descuento(
        academia_id=base_data["academia_a"].id,
        datos=datos_regla(),
    )

    assert regla.activo is True

    alternar_regla_descuento(
        academia_id=base_data["academia_a"].id,
        regla=regla,
    )
    assert regla.activo is False

    alternar_regla_descuento(
        academia_id=base_data["academia_a"].id,
        regla=regla,
    )
    assert regla.activo is True