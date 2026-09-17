import re
from datetime import date
from decimal import Decimal

import pytest
from flask import g
from sqlalchemy import event

from app.models.finanzas import AlumnoPlanFinanciero, ConfiguracionFinanciera, ObligacionFinanciera
from app.models.role import Role
from app.services.finanzas.asignaciones import asignar_plan_financiero
from app.services.finanzas.obligaciones import generar_obligaciones_mensuales
from test_finanzas_obligaciones import (
    preparar_asignacion, crear_plan, crear_frecuencia, crear_tarifario, crear_tarifa,
)
from test_finanzas_tarifarios_ui import cliente


URL = "/finanzas/generar-obligaciones"


def previa(client, periodo="2026-09", **extra):
    return client.post(URL, data=dict(periodo=periodo, accion="previsualizar", **extra))


def formulario(client, periodo="2026-09"):
    response = previa(client, periodo)
    assert response.status_code == 200
    token = re.search(r'name="vista_previa" value="([^"]+)"', response.text)
    assert token, response.text
    return dict(periodo=periodo, accion="generar", vista_previa=token[1])


def contador(response, nombre, valor):
    assert f'id="{nombre}">{valor}</dd>' in response.text


def test_admin_pantalla_y_navegacion(app, db, base_data):
    client = cliente(app, base_data["admin_a"])
    response = client.get(URL)
    assert response.status_code == 200
    assert 'name="csrf_token"' in response.text
    assert 'type="month"' in response.text
    assert URL in client.get("/admin/").text
    assert 'name="vista_previa"' not in response.text


def test_profesor_no_puede_generar_ni_previsualizar(app, db, base_data):
    client = cliente(app, base_data["profesor_a"])
    assert client.get(URL).status_code == 403
    assert previa(client).status_code == 403
    assert client.post(URL, data=dict(periodo="2026-09", accion="generar")).status_code == 403
    assert URL not in client.get("/finanzas/cartera").text
    assert ObligacionFinanciera.query.count() == 0


def test_superadmin_y_sin_academia(app, db, base_data):
    usuario = base_data["admin_a"]
    usuario.roles = [Role(name="SUPERADMIN")]
    db.session.commit()
    client = cliente(app, usuario)
    assert client.get(URL).status_code == 200
    usuario.academia_id = None
    db.session.commit()
    assert client.get(URL).status_code == 403


def test_previa_no_escribe_y_reporta_elegibles_omitidos(app, db, base_data):
    preparar_asignacion(db, base_data)
    client = cliente(app, base_data["admin_a"])
    escrituras = []
    def observar(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in ("INSERT", "UPDATE", "DELETE"):
            escrituras.append(statement)
    event.listen(db.engine, "before_cursor_execute", observar)
    try:
        response = previa(client)
    finally:
        event.remove(db.engine, "before_cursor_execute", observar)
    assert not escrituras
    assert ObligacionFinanciera.query.count() == ConfiguracionFinanciera.query.count() == 0
    for nombre, valor in [("evaluados", 2), ("con-plan", 1), ("omitidos", 1), ("nuevas", 1), ("existentes", 0)]:
        contador(response, nombre, valor)
    assert "USD 60.00" in response.text and "Perez Maria" in response.text
    assert "Lopez Ana" not in response.text


def test_generacion_resumen_cartera_estado_cuenta_y_reintento(app, db, base_data):
    academia, asignacion = preparar_asignacion(db, base_data)
    db.session.add(ConfiguracionFinanciera(academia_id=academia, dia_vencimiento_pension=7))
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    form = formulario(client)
    form.update(academia_id=base_data["academia_b"].id, alumno_id=base_data["alumno_b1"].id, valor_final_snapshot="0.01")
    response = client.post(URL, data=form)
    assert response.status_code == 200 and "Generación completada" in response.text
    for nombre, valor in [("nuevas", 1), ("existentes", 0), ("omitidos", 1)]:
        contador(response, nombre, valor)
    assert "USD 60.00" in response.text and "07/09/2026" in response.text
    obligacion = ObligacionFinanciera.query.one()
    assert obligacion.academia_id == academia
    assert obligacion.alumno_plan_financiero_id == asignacion.id
    assert obligacion.valor_final_snapshot == Decimal("60.00")
    assert obligacion.fecha_vencimiento == date(2026, 9, 7)
    assert obligacion.fecha_emision == date(2026, 9, 1)
    assert obligacion.tipo_obligacion == "PENSION"
    cartera = client.get("/finanzas/cartera?periodo=2026-09")
    cuenta = client.get(f"/finanzas/alumnos/{base_data['alumno_a1'].id}/estado-cuenta")
    assert cartera.status_code == cuenta.status_code == 200
    assert "60.00" in cartera.text and "Perez" in cartera.text
    assert "Pension 2026-09" in cuenta.text and "60.00" in cuenta.text
    repetida = client.post(URL, data=form)
    contador(repetida, "nuevas", 0)
    contador(repetida, "existentes", 1)
    contador(previa(client), "existentes", 1)
    assert ObligacionFinanciera.query.count() == 1


def test_historico_finalizado_y_futuro_importes_inmutables(app, db, base_data):
    academia, anterior = preparar_asignacion(db, base_data, valor="40.00")
    tarifa = anterior.tarifa_plan
    tarifa.valor_base = Decimal("60.00")
    db.session.commit()
    nueva = asignar_plan_financiero(academia_id=academia, alumno_id=anterior.alumno_id,
        plan_id=anterior.plan_id, frecuencia_id=anterior.frecuencia_id, fecha_inicio=date(2026, 10, 1))
    db.session.commit()
    assert anterior.estado == "FINALIZADO"
    client = cliente(app, base_data["admin_a"])
    septiembre = formulario(client)
    assert "USD 40.00" in previa(client).text
    assert client.post(URL, data=septiembre).status_code == 200
    assert client.post(URL, data=formulario(client, "2026-10")).status_code == 200
    assert ObligacionFinanciera.query.filter_by(periodo="2026-09").one().valor_final_snapshot == Decimal("40.00")
    assert ObligacionFinanciera.query.filter_by(periodo="2026-10").one().valor_final_snapshot == Decimal("60.00")
    tarifa.valor_base = nueva.valor_final_snapshot = Decimal("90.00")
    anterior.valor_final_snapshot = Decimal("80.00")
    db.session.commit()
    client.post(URL, data=septiembre)
    assert ObligacionFinanciera.query.filter_by(periodo="2026-09").one().valor_final_snapshot == Decimal("40.00")
    assert ObligacionFinanciera.query.filter_by(periodo="2026-10").one().valor_final_snapshot == Decimal("60.00")


@pytest.mark.parametrize("estado,inicio", [("ACTIVO", date(2026, 10, 1)), ("CANCELADO", date(2026, 1, 1))])
def test_no_usa_asignacion_futura_o_cancelada(app, db, base_data, estado, inicio):
    _, asignacion = preparar_asignacion(db, base_data)
    asignacion.estado, asignacion.fecha_inicio = estado, inicio
    db.session.commit()
    response = previa(cliente(app, base_data["admin_a"]))
    contador(response, "nuevas", 0)
    contador(response, "omitidos", 2)


def test_tenant_no_ve_ni_genera_obligaciones_ajenas(app, db, base_data):
    preparar_asignacion(db, base_data)
    academia = base_data["academia_b"].id
    plan, frecuencia, tarifario = crear_plan(db, academia), crear_frecuencia(db, academia), crear_tarifario(db, academia)
    crear_tarifa(db, academia, tarifario, plan, frecuencia, "987.65")
    db.session.commit()
    asignar_plan_financiero(academia_id=academia, alumno_id=base_data["alumno_b1"].id,
        plan_id=plan.id, frecuencia_id=frecuencia.id, fecha_inicio=date(2026, 1, 1))
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    response = previa(client, academia_id=academia)
    contador(response, "evaluados", 2)
    assert "987.65" not in response.text and "Lopez Ana" not in response.text
    client.post(URL, data=formulario(client))
    assert ObligacionFinanciera.query.filter_by(academia_id=academia).count() == 0
    generar_obligaciones_mensuales(academia_id=academia, periodo="2026-09")
    db.session.commit()
    contador(previa(client), "existentes", 1)


@pytest.mark.parametrize("periodo", ["", "2026-13", "2026-00", "0000-09", "2026-9", "septiembre", "2026-09-01", "２０２６-09"])
def test_periodo_invalido(app, db, base_data, periodo):
    response = previa(cliente(app, base_data["admin_a"]), periodo)
    assert response.status_code == 400 and "YYYY-MM" in response.text
    assert ObligacionFinanciera.query.count() == 0


def test_validaciones_vista_previa_concepto_y_csrf(app, db, base_data, monkeypatch):
    preparar_asignacion(db, base_data)
    client = cliente(app, base_data["admin_a"])
    assert client.post(URL, data=dict(periodo="2026-09", accion="generar")).status_code == 400
    form = formulario(client)
    assert client.post(URL, data={**form, "periodo": "2026-10"}).status_code == 400
    assert client.post(URL, data={**form, "concepto": "MATRICULA"}).status_code == 400
    assert client.post(URL, data={**form, "vista_previa": "falsificado"}).status_code == 400
    # La fixture mantiene un app_context externo: limpiar el usuario cacheado
    # simula el contexto independiente de cada solicitud real.
    g.pop("_login_user", None)
    otro = cliente(app, base_data["admin_b"])
    g.pop("_login_user", None)
    assert otro.post(URL, data=form).status_code == 400
    g.pop("_login_user", None)
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    assert client.post(URL, data=form).status_code == 400
    token = re.search(r'name="csrf_token" value="([^"]+)"', client.get(URL).text)[1]
    assert client.post(URL, data={**form, "csrf_token": token}).status_code == 200
    assert ObligacionFinanciera.query.count() == 1


def test_sin_alumnos_activos_y_sin_configuracion(app, db, base_data):
    client = cliente(app, base_data["admin_a"])
    response = previa(client)
    contador(response, "omitidos", 2)
    assert "serán omitidos" in response.text
    for key in ("alumno_a1", "alumno_a2"):
        base_data[key].activo = False
    db.session.commit()
    response = previa(client)
    contador(response, "evaluados", 0)
    assert "No hay alumnos elegibles" in response.text


def test_configuracion_invalida_se_omite_y_sin_vencimiento(app, db, base_data):
    _, asignacion = preparar_asignacion(db, base_data)
    client = cliente(app, base_data["admin_a"])
    form = formulario(client)
    asignacion.moneda_snapshot = ""
    db.session.commit()
    response = client.post(URL, data=form)
    contador(response, "omitidos", 2)
    assert ObligacionFinanciera.query.count() == 0
    asignacion.moneda_snapshot = "USD"
    db.session.commit()
    response = client.post(URL, data=form)
    assert "Sin vencimiento configurado" in response.text
    assert ObligacionFinanciera.query.one().fecha_vencimiento is None


def test_error_interno_revierte_lote_sin_exponer_sql(app, db, base_data, monkeypatch):
    from app.services.finanzas import obligaciones
    preparar_asignacion(db, base_data)
    client = cliente(app, base_data["admin_a"])
    form = formulario(client)
    original = obligaciones._crear_obligacion_pension
    def fallar(**kwargs):
        original(**kwargs)
        raise RuntimeError("SQL secreto")
    monkeypatch.setattr(obligaciones, "_crear_obligacion_pension", fallar)
    response = client.post(URL, data=form)
    assert response.status_code == 500 and "No se guardaron obligaciones" in response.text
    assert "SQL secreto" not in response.text
    assert ObligacionFinanciera.query.count() == 0


def test_dos_solicitudes_concurrentes_no_duplican(app, db, base_data, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine
    preparar_asignacion(db, base_data)
    original = db.engine
    temporal = create_engine(f"sqlite:///{(tmp_path / 'generacion.db').as_posix()}", connect_args={"timeout": 10})
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
    def generar():
        with app.test_client() as client:
            assert client.post("/auth/login", data=dict(username="admin_a", password="secret")).status_code == 302
            form = formulario(client)
            barrera.wait(timeout=10)
            response = client.post(URL, data=form)
            return response.status_code, response.text
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: generar(), range(2)))
        assert [status for status, _ in resultados] == [200, 200]
        assert sum('id="nuevas">1</dd>' in html for _, html in resultados) == 1
        assert sum('id="existentes">1</dd>' in html for _, html in resultados) == 1
        assert ObligacionFinanciera.query.count() == 1
    finally:
        db.session.remove()
        db.engines[None] = original
        temporal.dispose()
