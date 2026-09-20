from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.finanzas import (
    AlumnoPlanFinanciero, ObligacionFinanciera, PagoAplicacion, PagoFinanciero,
    PlanFinanciero, ReglaDescuento, TarifaPlan,
)
from app.models.role import Role
from app.models.sucursal import Sucursal
from app.services.finanzas.asignaciones import asignar_plan_financiero
from app.services.finanzas.obligaciones import generar_obligaciones_mensuales
from test_finanzas_tarifarios_ui import catalogo, cliente  # Fixtures/helpers de Fase A.
from app.services.finanzas.familias import (
    asignar_alumno_a_familia,
    crear_grupo_familiar,
)

def url(base_data, alumno="alumno_a1"):
    return f"/finanzas/alumnos/{base_data[alumno].id}/configuracion"


def datos(catalogo, **cambios):
    _, plan, frecuencia, _ = catalogo["a"]
    resultado = dict(plan_id=plan.id, frecuencia_id=frecuencia.id,
                     fecha_inicio=date.today().isoformat(), asignacion_actual_id="0")
    resultado.update(cambios)
    return resultado


def test_admin_abre_consulta_tarifa_y_guarda(app, db, base_data, catalogo):
    client = cliente(app, base_data["admin_a"])
    formulario = client.get(url(base_data))
    assert formulario.status_code == 200
    assert 'todavía no tiene configuración financiera' in formulario.text
    assert 'name="csrf_token"' in formulario.text
    consulta = client.post(url(base_data), data=datos(catalogo, accion="consultar"))
    assert consulta.status_code == 200
    assert 'value="USD 50.00"' in consulta.text and "Tarifario a" in consulta.text
    assert 'id="importe" readonly' in consulta.text
    assert AlumnoPlanFinanciero.query.count() == 0
    response = client.post(url(base_data), data=datos(
        catalogo, valor_base="0.01", tarifa_base_snapshot="0.01", valor_final_snapshot="0.01",
        academia_id=base_data["academia_b"].id, alumno_id=base_data["alumno_b1"].id,
        created_by_id=base_data["admin_b"].id,
    ))
    assert response.status_code == 302
    asignacion = AlumnoPlanFinanciero.query.one()
    assert asignacion.tarifa_base_snapshot == asignacion.valor_final_snapshot == Decimal("50.00")
    assert asignacion.tarifa_plan_id == catalogo["a"][3].id
    assert asignacion.tarifario_id == catalogo["a"][0].id
    assert asignacion.academia_id == base_data["academia_a"].id
    assert asignacion.alumno_id == base_data["alumno_a1"].id
    assert asignacion.created_by_id == base_data["admin_a"].id
    assert 'Configuración financiera guardada correctamente.' in client.get(response.location).text


@pytest.mark.parametrize("indice", [1, 2, 3])
def test_catalogos_inactivos_no_utilizables(app, db, base_data, catalogo, indice):
    referencia = catalogo["a"][indice]
    referencia.activo = False
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    form = client.get(url(base_data)).text
    if indice in (1, 2):
        assert referencia.nombre not in form
    response = client.post(url(base_data), data=datos(catalogo))
    assert response.status_code == 200
    assert 'alert-danger' in response.text
    assert AlumnoPlanFinanciero.query.count() == 0


def test_combinacion_sin_tarifa_no_guarda(app, db, base_data, catalogo):
    plan = PlanFinanciero(academia_id=base_data["academia_a"].id, codigo="SIN", nombre="Sin tarifa")
    db.session.add(plan)
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    response = client.post(url(base_data), data=datos(catalogo, plan_id=plan.id))
    assert "No existe una tarifa activa para el plan y frecuencia seleccionados." in response.text
    assert AlumnoPlanFinanciero.query.count() == 0


@pytest.mark.parametrize("estado", ["BORRADOR", "CERRADO", "FUTURO", "VENCIDO", "AUSENTE", "SOLAPADO"])
def test_tarifario_invalido_no_guarda(app, db, base_data, catalogo, estado):
    tarifario = catalogo["a"][0]
    if estado == "FUTURO":
        tarifario.fecha_inicio_vigencia = date.today() + timedelta(days=1)
    elif estado == "VENCIDO":
        tarifario.fecha_inicio_vigencia = date.today() - timedelta(days=3)
        tarifario.fecha_fin_vigencia = date.today() - timedelta(days=1)
    elif estado == "AUSENTE":
        db.session.delete(catalogo["a"][3])
        db.session.delete(tarifario)
    elif estado == "SOLAPADO":
        from app.models.finanzas import Tarifario
        db.session.add(Tarifario(academia_id=tarifario.academia_id, nombre="Solapado", estado="VIGENTE", fecha_inicio_vigencia=date.today()))
    else:
        tarifario.estado = estado
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    response = client.post(url(base_data), data=datos(catalogo))
    assert response.status_code == 200 and 'alert-danger' in response.text
    assert AlumnoPlanFinanciero.query.count() == 0


def test_resuelve_por_fecha_inicio_inclusiva(app, db, base_data, catalogo):
    fecha = date.today() + timedelta(days=15)
    catalogo["a"][0].fecha_inicio_vigencia = fecha
    catalogo["a"][0].fecha_fin_vigencia = fecha
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    assert client.post(url(base_data), data=datos(catalogo, fecha_inicio=fecha.isoformat())).status_code == 302
    assert AlumnoPlanFinanciero.query.one().fecha_inicio == fecha


@pytest.mark.parametrize("campo,indice", [("plan_id", 1), ("frecuencia_id", 2), ("tarifario_id", 0), ("tarifa_plan_id", 3)])
def test_rechaza_referencias_tenant_b(app, db, base_data, catalogo, campo, indice):
    client = cliente(app, base_data["admin_a"])
    form = client.get(url(base_data)).text
    assert "Plan b" not in form and "Frecuencia b" not in form and "Tarifario b" not in form
    response = client.post(url(base_data), data=datos(catalogo, **{campo: catalogo["b"][indice].id}))
    assert response.status_code == 200 and 'alert-danger' in response.text
    assert AlumnoPlanFinanciero.query.count() == 0


@pytest.mark.parametrize("metodo", ["get", "post"])
def test_alumno_y_asignacion_ajenos_inaccesibles(app, db, base_data, catalogo, metodo):
    tarifario, plan, frecuencia, _ = catalogo["b"]
    ajena = asignar_plan_financiero(academia_id=tarifario.academia_id, alumno_id=base_data["alumno_b1"].id,
                                  plan_id=plan.id, frecuencia_id=frecuencia.id, fecha_inicio=date.today())
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    assert getattr(client, metodo)(url(base_data, "alumno_b1"), data=datos(catalogo)).status_code == 404
    assert client.get(f"/alumnos/{base_data['alumno_b1'].id}/perfil").status_code == 404
    assert client.post(url(base_data), data=datos(catalogo, asignacion_actual_id=ajena.id)).status_code == 200
    db.session.refresh(ajena)
    assert ajena.estado == "ACTIVO" and ajena.fecha_fin is None
    assert AlumnoPlanFinanciero.query.count() == 1


def test_duplicado_y_formulario_desactualizado_no_crean_otro_activo(app, db, base_data, catalogo):
    client = cliente(app, base_data["admin_a"])
    assert client.post(url(base_data), data=datos(catalogo)).status_code == 302
    response = client.post(url(base_data), data=datos(catalogo, fecha_inicio=(date.today() + timedelta(days=1)).isoformat()))
    assert "configuración financiera cambió" in response.text
    assert AlumnoPlanFinanciero.query.count() == 1
    actual = AlumnoPlanFinanciero.query.one()
    response = client.post(url(base_data), data=datos(catalogo, asignacion_actual_id=actual.id))
    assert "debe iniciar despues" in response.text
    assert actual.estado == "ACTIVO" and actual.fecha_fin is None


def test_cambio_conserva_historial_obligaciones_pagos_y_aplicaciones(app, db, base_data, catalogo):
    client = cliente(app, base_data["admin_a"])
    inicio = date.today().replace(day=1)
    assert client.post(url(base_data), data=datos(catalogo, fecha_inicio=inicio.isoformat())).status_code == 302
    anterior = AlumnoPlanFinanciero.query.one()
    generar_obligaciones_mensuales(academia_id=anterior.academia_id, periodo=inicio.strftime("%Y-%m"))
    obligacion = ObligacionFinanciera.query.one()
    pago = PagoFinanciero(academia_id=anterior.academia_id, alumno_id=anterior.alumno_id, fecha_pago=inicio,
                         valor=Decimal("20.00"), moneda="USD", medio_pago="EFECTIVO")
    db.session.add(pago)
    db.session.flush()
    aplicacion = PagoAplicacion(academia_id=anterior.academia_id, pago_id=pago.id,
                               obligacion_financiera_id=obligacion.id, valor_aplicado=Decimal("20.00"))
    db.session.add(aplicacion)
    plan = PlanFinanciero(academia_id=anterior.academia_id, codigo="COMPETIDOR", nombre="Competidor")
    db.session.add(plan)
    db.session.flush()
    db.session.add(TarifaPlan(academia_id=anterior.academia_id, tarifario_id=catalogo["a"][0].id,
                             plan_id=plan.id, frecuencia_id=catalogo["a"][2].id, valor_base=Decimal("80.00")))
    db.session.commit()
    def snapshot(obj):
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    historicos = [(obj, snapshot(obj)) for obj in (obligacion, pago, aplicacion)]
    fecha = inicio + timedelta(days=1)
    assert client.post(url(base_data), data=datos(catalogo, plan_id=plan.id, fecha_inicio=fecha.isoformat(),
                                                asignacion_actual_id=anterior.id)).status_code == 302
    db.session.refresh(anterior)
    assert anterior.estado == "FINALIZADO" and anterior.fecha_fin == inicio
    assert anterior.tarifa_base_snapshot == anterior.valor_final_snapshot == Decimal("50.00")
    nueva = AlumnoPlanFinanciero.query.filter_by(estado="ACTIVO").one()
    assert nueva.plan_id == plan.id and nueva.valor_final_snapshot == Decimal("80.00")
    assert AlumnoPlanFinanciero.query.count() == 2
    for obj, antes in historicos:
        db.session.refresh(obj)
        assert snapshot(obj) == antes
    assert ObligacionFinanciera.query.count() == 1
    html = client.get(url(base_data)).text
    assert "Historial de configuraciones" in html and "FINALIZADO" in html and "Competidor" in html


def test_cambio_invalido_no_finaliza_anterior(app, db, base_data, catalogo):
    client = cliente(app, base_data["admin_a"])
    client.post(url(base_data), data=datos(catalogo))
    anterior = AlumnoPlanFinanciero.query.one()
    catalogo["a"][3].activo = False
    db.session.commit()
    client.post(url(base_data), data=datos(catalogo, asignacion_actual_id=anterior.id,
                                         fecha_inicio=(date.today() + timedelta(days=1)).isoformat()))
    db.session.refresh(anterior)
    assert anterior.estado == "ACTIVO" and anterior.fecha_fin is None
    assert AlumnoPlanFinanciero.query.count() == 1


def test_perfil_listado_filtros_y_enlace_estado_cuenta(app, db, base_data, catalogo):
    client = cliente(app, base_data["admin_a"])
    client.post(url(base_data), data=datos(catalogo))
    perfil = client.get(f"/alumnos/{base_data['alumno_a1'].id}/perfil")
    assert perfil.status_code == 200
    for texto in ("Configuración financiera", "Plan a", "Frecuencia a", "Tarifario a", "USD 50.00", "ACTIVA", "Editar configuración"):
        assert texto in perfil.text
    estado = f"/finanzas/alumnos/{base_data['alumno_a1'].id}/estado-cuenta"
    assert f'href="{estado}"' in perfil.text and client.get(estado).status_code == 200
    sin = client.get(f"/alumnos/{base_data['alumno_a2'].id}/perfil")
    assert 'todavía no tiene configuración financiera' in sin.text and 'Asignar plan financiero' in sin.text
    listado = client.get("/finanzas/asignaciones")
    assert listado.status_code == 200 and 'href="/finanzas/asignaciones"' in listado.text
    assert "Perez Carlos" in listado.text and "Perez Maria" in listado.text and "Lopez Ana" not in listado.text
    con = client.get("/finanzas/asignaciones?estado=con").text
    sin = client.get("/finanzas/asignaciones?estado=sin").text
    assert "Perez Carlos" in con and "Perez Maria" not in con
    assert "Perez Maria" in sin and "Perez Carlos" not in sin


def test_profesor_solo_lee_y_respeta_sucursal(app, db, base_data, catalogo):
    client = cliente(app, base_data["profesor_a"])
    assert client.get(url(base_data)).status_code == 200
    assert "Guardar asignación" not in client.get(url(base_data)).text
    assert client.post(url(base_data), data=datos(catalogo)).status_code == 403
    assert client.post(url(base_data), data=datos(catalogo, accion="consultar")).status_code == 403
    sucursal = Sucursal(academia_id=base_data["academia_a"].id, nombre="Otra sucursal")
    db.session.add(sucursal)
    db.session.flush()
    base_data["alumno_a2"].sucursal_id = sucursal.id
    db.session.commit()
    assert client.get(url(base_data, "alumno_a2")).status_code == 403
    listado = client.get("/finanzas/asignaciones").text
    assert "Perez Carlos" in listado and "Perez Maria" not in listado and "Lopez Ana" not in listado
    assert "Asignar plan financiero" not in listado
    assert AlumnoPlanFinanciero.query.count() == 0


def test_superadmin_requiere_academia(app, db, base_data, catalogo):
    usuario = base_data["admin_a"]
    usuario.roles = [Role(name="SUPERADMIN")]
    db.session.commit()
    client = cliente(app, usuario)
    assert client.post(url(base_data), data=datos(catalogo)).status_code == 302
    assert client.get(url(base_data, "alumno_b1")).status_code == 404
    usuario.academia_id = None
    db.session.commit()
    assert client.get("/finanzas/asignaciones").status_code == 403
    assert client.get(url(base_data)).status_code == 403
    assert client.post(url(base_data), data=datos(catalogo)).status_code == 403


def test_csrf_obligatorio(app, db, base_data, catalogo, monkeypatch):
    client = cliente(app, base_data["admin_a"])
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    assert client.post(url(base_data), data=datos(catalogo)).status_code == 400
    assert 'name="csrf_token"' in client.get(url(base_data)).text
    assert AlumnoPlanFinanciero.query.count() == 0


@pytest.mark.parametrize("cambios", [{"fecha_inicio": "no-fecha"}, {"plan_id": "abc"}, {"frecuencia_id": ""},
                                     {"asignacion_actual_id": "abc"}, {"asignacion_actual_id": ""}])
def test_datos_invalidos_sin_errores_internos(app, db, base_data, catalogo, cambios):
    client = cliente(app, base_data["admin_a"])
    response = client.post(url(base_data), data=datos(catalogo, **cambios))
    assert response.status_code == 200 and 'alert-danger' in response.text
    assert AlumnoPlanFinanciero.query.count() == 0


def test_ui_no_aplica_descuentos_existentes(app, db, base_data, catalogo):
    db.session.add(ReglaDescuento(academia_id=base_data["academia_a"].id, codigo="BECA", nombre="Beca",
                                 tipo="BECA", porcentaje=Decimal("50.00"), activo=True))
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    assert client.post(url(base_data), data=datos(catalogo)).status_code == 302
    asignacion = AlumnoPlanFinanciero.query.one()
    assert asignacion.valor_final_snapshot == Decimal("50.00")
    assert asignacion.descuento_valor_snapshot == Decimal("0.00")
    assert asignacion.regla_descuento_id is None and asignacion.grupo_familiar_id is None


def test_dos_guardados_concurrentes_solo_crean_una_asignacion(app, db, base_data, catalogo, tmp_path):
    """Dos conexiones SQLite reales, sin compartir la conexión en memoria."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine

    destino = url(base_data)
    formulario = datos(catalogo)
    original = db.engine
    temporal = create_engine(f"sqlite:///{(tmp_path / 'asignaciones.db').as_posix()}", connect_args={"timeout": 10})
    db.metadata.create_all(temporal)
    db.session.commit()
    with original.connect() as origen, temporal.begin() as copia:
        for tabla in db.metadata.sorted_tables:
            filas = [dict(row) for row in origen.execute(tabla.select()).mappings()]
            if filas:
                copia.execute(tabla.insert(), filas)
    db.session.remove()
    db.engines[None] = temporal
    barrera = Barrier(2)

    def guardar():
        with app.test_client() as client:
            assert client.post("/auth/login", data={"username": "admin_a", "password": "secret"}).status_code == 302
            barrera.wait(timeout=10)
            return client.post(destino, data=formulario).status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: guardar(), range(2)))
        assert sorted(resultados) == [200, 302]
        assert AlumnoPlanFinanciero.query.count() == 1
        assert AlumnoPlanFinanciero.query.one().estado == "ACTIVO"
    finally:
        db.session.remove()
        db.engines[None] = original
        temporal.dispose()
def test_ui_aplica_automaticamente_descuento_hermanos(
    app,
    db,
    base_data,
    catalogo,
):
    academia_id = base_data["academia_a"].id

    familia = crear_grupo_familiar(
        academia_id=academia_id,
        codigo="FAM-UI-D4",
        nombre="Familia UI D4",
    )

    for alumno in (
        base_data["alumno_a1"],
        base_data["alumno_a2"],
    ):
        asignar_alumno_a_familia(
            academia_id=academia_id,
            alumno_id=alumno.id,
            grupo_familiar_id=familia.id,
            fecha_inicio=date.today(),
        )

    regla = ReglaDescuento(
        academia_id=academia_id,
        codigo="HERMANOS_2",
        nombre="Hermanos 2",
        tipo="HERMANOS",
        porcentaje=Decimal("10.00"),
        cantidad_minima=2,
        decimales_redondeo=2,
        activo=True,
    )

    db.session.add(regla)
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    consulta = client.post(
        url(base_data),
        data=datos(
            catalogo,
            accion="consultar",
        ),
    )
    texto = " ".join(consulta.text.split())

    assert consulta.status_code == 200
    assert "Familia UI D4" in texto
    assert "HERMANOS_2" in texto
    assert "10.00%" in texto
    assert "USD 45.00" in texto
    assert AlumnoPlanFinanciero.query.count() == 0

    response = client.post(
        url(base_data),
        data=datos(catalogo),
    )

    assert response.status_code == 302

    asignacion = AlumnoPlanFinanciero.query.one()

    assert asignacion.grupo_familiar_id == familia.id
    assert asignacion.regla_descuento_id == regla.id
    assert (
        asignacion.tarifa_base_snapshot
        == Decimal("50.00")
    )
    assert (
        asignacion.descuento_porcentaje_snapshot
        == Decimal("10.00")
    )
    assert (
        asignacion.descuento_valor_snapshot
        == Decimal("5.00")
    )
    assert (
        asignacion.valor_final_snapshot
        == Decimal("45.00")
    )


def test_ui_un_integrante_no_recibe_descuento_hermanos(
    app,
    db,
    base_data,
    catalogo,
):
    academia_id = base_data["academia_a"].id

    familia = crear_grupo_familiar(
        academia_id=academia_id,
        codigo="FAM-UI-UNO",
        nombre="Familia un integrante",
    )

    asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        grupo_familiar_id=familia.id,
        fecha_inicio=date.today(),
    )

    db.session.add(
        ReglaDescuento(
            academia_id=academia_id,
            codigo="HERMANOS_2",
            nombre="Hermanos 2",
            tipo="HERMANOS",
            porcentaje=Decimal("10.00"),
            cantidad_minima=2,
            activo=True,
        )
    )
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        url(base_data),
        data=datos(catalogo),
    )

    assert response.status_code == 302

    asignacion = AlumnoPlanFinanciero.query.one()

    assert asignacion.grupo_familiar_id == familia.id
    assert asignacion.regla_descuento_id is None
    assert asignacion.descuento_valor_snapshot == Decimal("0.00")
    assert asignacion.valor_final_snapshot == Decimal("50.00")

def test_ui_lista_solo_beneficios_explicitos_activos(
    app,
    db,
    base_data,
    catalogo,
):
    academia_id = base_data["academia_a"].id

    beca = ReglaDescuento(
        academia_id=academia_id,
        codigo="BECA_UI",
        nombre="Beca UI",
        tipo="BECA",
        porcentaje=Decimal("50.00"),
        activo=True,
    )

    inactiva = ReglaDescuento(
        academia_id=academia_id,
        codigo="CONVENIO_OFF",
        nombre="Convenio inactivo",
        tipo="CONVENIO",
        porcentaje=Decimal("20.00"),
        activo=False,
    )

    hermanos = ReglaDescuento(
        academia_id=academia_id,
        codigo="HERMANOS_UI",
        nombre="Hermanos UI",
        tipo="HERMANOS",
        porcentaje=Decimal("10.00"),
        cantidad_minima=2,
        activo=True,
    )

    db.session.add_all([beca, inactiva, hermanos])
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    texto = client.get(url(base_data)).text

    assert 'value="AUTO"' in texto
    assert 'value="NINGUNO"' in texto
    assert f'value="REGLA:{beca.id}"' in texto
    assert f'value="REGLA:{inactiva.id}"' not in texto
    assert f'value="REGLA:{hermanos.id}"' not in texto


def test_ui_beca_explicita_reemplaza_hermanos_preview_y_guardado(
    app,
    db,
    base_data,
    catalogo,
):
    academia_id = base_data["academia_a"].id

    familia = crear_grupo_familiar(
        academia_id=academia_id,
        codigo="FAM-D6",
        nombre="Familia D6",
    )

    for alumno in (
        base_data["alumno_a1"],
        base_data["alumno_a2"],
    ):
        asignar_alumno_a_familia(
            academia_id=academia_id,
            alumno_id=alumno.id,
            grupo_familiar_id=familia.id,
            fecha_inicio=date.today(),
        )

    hermanos = ReglaDescuento(
        academia_id=academia_id,
        codigo="HERMANOS_2",
        nombre="Hermanos 2",
        tipo="HERMANOS",
        porcentaje=Decimal("10.00"),
        cantidad_minima=2,
        activo=True,
    )

    beca = ReglaDescuento(
        academia_id=academia_id,
        codigo="BECA_50",
        nombre="Beca 50",
        tipo="BECA",
        porcentaje=Decimal("50.00"),
        activo=True,
    )

    db.session.add_all([hermanos, beca])
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    formulario = datos(
        catalogo,
        beneficio=f"REGLA:{beca.id}",
    )

    consulta = client.post(
        url(base_data),
        data={**formulario, "accion": "consultar"},
    )

    texto = " ".join(consulta.text.split())

    assert consulta.status_code == 200
    assert "Beca 50" in texto
    assert "BECA" in texto
    assert "USD 25.00" in texto
    assert AlumnoPlanFinanciero.query.count() == 0

    response = client.post(
        url(base_data),
        data=formulario,
    )

    assert response.status_code == 302

    asignacion = AlumnoPlanFinanciero.query.one()

    assert asignacion.grupo_familiar_id == familia.id
    assert asignacion.regla_descuento_id == beca.id
    assert asignacion.regla_descuento_id != hermanos.id
    assert asignacion.descuento_valor_snapshot == Decimal("25.00")
    assert asignacion.valor_final_snapshot == Decimal("25.00")


def test_ui_sin_descuento_ignora_hermanos(
    app,
    db,
    base_data,
    catalogo,
):
    academia_id = base_data["academia_a"].id

    familia = crear_grupo_familiar(
        academia_id=academia_id,
        codigo="FAM-D6-SIN",
        nombre="Familia D6 sin descuento",
    )

    for alumno in (
        base_data["alumno_a1"],
        base_data["alumno_a2"],
    ):
        asignar_alumno_a_familia(
            academia_id=academia_id,
            alumno_id=alumno.id,
            grupo_familiar_id=familia.id,
            fecha_inicio=date.today(),
        )

    db.session.add(
        ReglaDescuento(
            academia_id=academia_id,
            codigo="HERMANOS_2",
            nombre="Hermanos 2",
            tipo="HERMANOS",
            porcentaje=Decimal("10.00"),
            cantidad_minima=2,
            activo=True,
        )
    )
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        url(base_data),
        data=datos(
            catalogo,
            beneficio="NINGUNO",
        ),
    )

    assert response.status_code == 302

    asignacion = AlumnoPlanFinanciero.query.one()

    assert asignacion.grupo_familiar_id is None
    assert asignacion.regla_descuento_id is None
    assert asignacion.descuento_valor_snapshot == Decimal("0.00")
    assert asignacion.valor_final_snapshot == Decimal("50.00")


def test_ui_rechaza_beneficio_de_otra_academia(
    app,
    db,
    base_data,
    catalogo,
):
    regla = ReglaDescuento(
        academia_id=base_data["academia_b"].id,
        codigo="BECA_AJENA_UI",
        nombre="Beca ajena",
        tipo="BECA",
        porcentaje=Decimal("50.00"),
        activo=True,
    )

    db.session.add(regla)
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        url(base_data),
        data=datos(
            catalogo,
            beneficio=f"REGLA:{regla.id}",
        ),
    )

    assert response.status_code == 200
    assert "alert-danger" in response.text
    assert AlumnoPlanFinanciero.query.count() == 0


def test_ui_no_permite_seleccionar_hermanos_manualmente(
    app,
    db,
    base_data,
    catalogo,
):
    regla = ReglaDescuento(
        academia_id=base_data["academia_a"].id,
        codigo="HERMANOS_MANUAL",
        nombre="Hermanos manual",
        tipo="HERMANOS",
        porcentaje=Decimal("10.00"),
        cantidad_minima=2,
        activo=True,
    )

    db.session.add(regla)
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        url(base_data),
        data=datos(
            catalogo,
            beneficio=f"REGLA:{regla.id}",
        ),
    )

    assert response.status_code == 200
    assert "alert-danger" in response.text
    assert AlumnoPlanFinanciero.query.count() == 0