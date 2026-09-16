from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.finanzas import (
    AlumnoPlanFinanciero, FrecuenciaEntrenamiento, ObligacionFinanciera,
    PlanFinanciero, TarifaPlan, Tarifario,
)
from app.models.role import Role
from app.services.finanzas.asignaciones import asignar_plan_financiero
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.obligaciones import generar_obligaciones_mensuales
from app.services.finanzas.tarifas import calcular_tarifa


@pytest.fixture
def catalogo(db, base_data):
    resultado = {}
    for sufijo in ("a", "b"):
        academia_id = base_data[f"academia_{sufijo}"].id
        plan = PlanFinanciero(academia_id=academia_id, codigo="REGULAR", nombre=f"Plan {sufijo}")
        frecuencia = FrecuenciaEntrenamiento(academia_id=academia_id, codigo="D3", nombre=f"Frecuencia {sufijo}", dias_semana=3)
        tarifario = Tarifario(academia_id=academia_id, nombre=f"Tarifario {sufijo}", estado="VIGENTE", moneda="USD", fecha_inicio_vigencia=date.today().replace(day=1))
        db.session.add_all([plan, frecuencia, tarifario])
        db.session.flush()
        tarifa = TarifaPlan(academia_id=academia_id, tarifario_id=tarifario.id, plan_id=plan.id, frecuencia_id=frecuencia.id, valor_base=Decimal("50.00"))
        db.session.add(tarifa)
        db.session.flush()
        resultado[sufijo] = (tarifario, plan, frecuencia, tarifa)
    db.session.commit()
    return resultado


def cliente(app, usuario):
    client = app.test_client()
    assert client.post("/auth/login", data={"username": usuario.username, "password": "secret"}).status_code == 302
    return client


def datos_tarifario(**cambios):
    datos = dict(nombre="Precios nuevos", descripcion="Academia", moneda="usd", fecha_inicio_vigencia=date.today().isoformat(), fecha_fin_vigencia="", estado="BORRADOR")
    datos.update(cambios)
    return datos


def datos_tarifa(catalogo, **cambios):
    _, plan, frecuencia, _ = catalogo["a"]
    datos = dict(plan_id=str(plan.id), frecuencia_id=str(frecuencia.id), valor_base="65.25", observaciones="Precio inicial", activo="1")
    datos.update(cambios)
    return datos


def url_tarifa(catalogo, accion="editar"):
    tarifario, _, _, tarifa = catalogo["a"]
    return f"/finanzas/tarifarios/{tarifario.id}/tarifas/{tarifa.id}/{accion}"


def test_flujo_web_admin_y_navegacion(app, db, base_data, catalogo):
    client = cliente(app, base_data["admin_a"])
    listado = client.get("/finanzas/tarifarios")
    assert b"Nuevo tarifario" in listado.data
    assert b"Tarifario b" not in listado.data
    assert b'href="/finanzas/tarifarios"' in client.get("/admin/").data
    assert client.get("/finanzas/tarifarios/nuevo").status_code == 200
    response = client.post("/finanzas/tarifarios/nuevo", data=datos_tarifario(academia_id=base_data["academia_b"].id))
    assert response.status_code == 302
    nuevo = Tarifario.query.filter_by(nombre="Precios nuevos").one()
    assert nuevo.academia_id == base_data["academia_a"].id
    assert nuevo.created_by_id == base_data["admin_a"].id
    assert nuevo.moneda == "USD"
    assert response.location.endswith(f"/{nuevo.id}/tarifas")
    assert b"Nueva tarifa" in client.get(response.location).data
    alta = f"/finanzas/tarifarios/{nuevo.id}/tarifas/nueva"
    formulario = client.get(alta)
    assert b"Plan a" in formulario.data and b"Plan b" not in formulario.data
    assert b"Frecuencia b" not in formulario.data
    creado = client.post(alta, data=datos_tarifa(catalogo, academia_id=base_data["academia_b"].id, tarifario_id=catalogo["b"][0].id))
    assert creado.status_code == 302
    tarifa = TarifaPlan.query.filter_by(tarifario_id=nuevo.id).one()
    assert tarifa.academia_id == nuevo.academia_id
    assert tarifa.valor_base == Decimal("65.25")
    detalle = client.get(creado.location)
    assert b"65.25" in detalle.data and b"Plan a" in detalle.data
    assert client.get(f"/finanzas/tarifarios/{nuevo.id}/editar").status_code == 200
    assert client.get(f"/finanzas/tarifarios/{nuevo.id}/tarifas/{tarifa.id}/editar").status_code == 200


@pytest.mark.parametrize("metodo", ["get", "post"])
def test_ids_ajenos_o_tarifa_de_otro_padre_404(app, db, base_data, catalogo, metodo):
    client = cliente(app, base_data["admin_a"])
    ta, _, _, tarifa_a = catalogo["a"]
    tb, _, _, tarifa_b = catalogo["b"]
    urls = [f"/finanzas/tarifarios/{tb.id}/editar", f"/finanzas/tarifarios/{tb.id}/tarifas/nueva", f"/finanzas/tarifarios/{tb.id}/tarifas/{tarifa_b.id}/editar", f"/finanzas/tarifarios/{ta.id}/tarifas/{tarifa_b.id}/editar"]
    for url in urls:
        assert getattr(client, metodo)(url).status_code == 404
    assert client.get(f"/finanzas/tarifarios/{tb.id}/tarifas").status_code == 404
    assert client.post(f"/finanzas/tarifarios/{ta.id}/tarifas/{tarifa_b.id}/alternar-activo").status_code == 404
    assert tarifa_a.activo and tarifa_b.activo


@pytest.mark.parametrize("campo", ["plan_id", "frecuencia_id"])
@pytest.mark.parametrize("inactivo", [False, True])
def test_tarifa_rechaza_referencias_ajenas_o_inactivas(app, db, base_data, catalogo, campo, inactivo):
    idx = 1 if campo == "plan_id" else 2
    referencia = catalogo["a" if inactivo else "b"][idx]
    if inactivo:
        referencia.activo = False
        db.session.commit()
    client = cliente(app, base_data["admin_a"])
    respuesta = client.post(url_tarifa(catalogo), data=datos_tarifa(catalogo, **{campo: referencia.id}))
    assert respuesta.status_code == 200
    assert b"no disponible" in respuesta.data
    assert catalogo["a"][3].valor_base == Decimal("50.00")
    assert catalogo["a"][3].academia_id == base_data["academia_a"].id
    # El mismo control se aplica al alta, incluso manipulando las opciones del formulario.
    response = client.post(f"/finanzas/tarifarios/{catalogo['a'][0].id}/tarifas/nueva", data=datos_tarifa(catalogo, **{campo: referencia.id}))
    assert b"no disponible" in response.data
    assert TarifaPlan.query.count() == 2


@pytest.mark.parametrize("valor", ["", "abc", "-1", "1.001", "NaN", "Infinity", "100000000"])
def test_importe_invalido_no_modifica(app, db, base_data, catalogo, valor):
    client = cliente(app, base_data["admin_a"])
    assert client.post(url_tarifa(catalogo), data=datos_tarifa(catalogo, valor_base=valor)).status_code == 200
    assert catalogo["a"][3].valor_base == Decimal("50.00")


@pytest.mark.parametrize("cambio", [
    {"fecha_inicio_vigencia": "invalida"},
    {"fecha_fin_vigencia": "invalida"},
    {"fecha_inicio_vigencia": "2030-02-02", "fecha_fin_vigencia": "2030-02-01"},
    {"estado": "ACTIVO"}, {"moneda": "US"}, {"nombre": " "},
])
def test_tarifario_rechaza_datos_invalidos(app, db, base_data, cambio):
    client = cliente(app, base_data["admin_a"])
    assert client.post("/finanzas/tarifarios/nuevo", data=datos_tarifario(**cambio)).status_code == 200
    assert Tarifario.query.count() == 0


def test_solapamiento_inclusivo_publicacion_y_cierre(app, db, base_data, catalogo):
    client = cliente(app, base_data["admin_a"])
    tarifario = catalogo["a"][0]
    fin = date.today() + timedelta(days=10)
    tarifario.fecha_fin_vigencia = fin
    db.session.commit()
    response = client.post("/finanzas/tarifarios/nuevo", data=datos_tarifario(estado="VIGENTE", fecha_inicio_vigencia=fin.isoformat()))
    assert b"solapa" in response.data
    response = client.post("/finanzas/tarifarios/nuevo", data=datos_tarifario(estado="VIGENTE", fecha_inicio_vigencia=(fin + timedelta(days=1)).isoformat()))
    assert response.status_code == 302
    nuevo = Tarifario.query.filter_by(nombre="Precios nuevos").one()
    # No se permite extender el anterior sobre el nuevo ni volver a borrador.
    editar = f"/finanzas/tarifarios/{tarifario.id}/editar"
    original = datos_tarifario(nombre=tarifario.nombre, estado="VIGENTE", fecha_inicio_vigencia=tarifario.fecha_inicio_vigencia.isoformat())
    assert b"solapa" in client.post(editar, data=original).data
    assert b"solo puede" in client.post(editar, data={**original, "estado": "BORRADOR"}).data
    assert client.post(editar, data={**original, "estado": "CERRADO", "fecha_fin_vigencia": fin.isoformat()}).status_code == 302
    assert b"solo consulta" in client.post(editar, data=original).data
    assert tarifario.estado == "CERRADO"
    assert nuevo.estado == "VIGENTE"


@pytest.mark.parametrize("estado", ["BORRADOR", "CERRADO", "FUTURO", "VENCIDO"])
def test_servicios_rechazan_tarifario_no_utilizable(app, db, base_data, catalogo, estado):
    tarifario, plan, frecuencia, tarifa = catalogo["a"]
    hoy = date.today()
    if estado == "FUTURO":
        tarifario.fecha_inicio_vigencia = hoy + timedelta(days=1)
    elif estado == "VENCIDO":
        tarifario.fecha_inicio_vigencia = hoy - timedelta(days=2)
        tarifario.fecha_fin_vigencia = hoy - timedelta(days=1)
    else:
        tarifario.estado = estado
    db.session.commit()
    args = dict(academia_id=tarifario.academia_id, tarifario_id=tarifario.id, plan_id=plan.id, frecuencia_id=frecuencia.id)
    with pytest.raises(FinanzasError):
        calcular_tarifa(**args, contexto_descuentos={"fecha": hoy})
    with pytest.raises(FinanzasError):
        asignar_plan_financiero(**args, tarifa_plan_id=tarifa.id, alumno_id=base_data["alumno_a1"].id, fecha_inicio=hoy)
    assert AlumnoPlanFinanciero.query.count() == 0


@pytest.mark.parametrize("indice", [1, 2])
def test_servicios_rechazan_catalogos_inactivos(db, base_data, catalogo, indice):
    tarifario, plan, frecuencia, _ = catalogo["a"]
    catalogo["a"][indice].activo = False
    db.session.commit()
    args = dict(academia_id=tarifario.academia_id, tarifario_id=tarifario.id, plan_id=plan.id, frecuencia_id=frecuencia.id)
    with pytest.raises(FinanzasError, match="no disponible"):
        calcular_tarifa(**args, contexto_descuentos={"fecha": date.today()})
    with pytest.raises(FinanzasError, match="no disponible"):
        asignar_plan_financiero(**args, alumno_id=base_data["alumno_a1"].id, fecha_inicio=date.today())


def test_vigencia_inclusiva_y_borrador_preparable(app, db, base_data, catalogo):
    tarifario, plan, frecuencia, _ = catalogo["a"]
    tarifario.fecha_fin_vigencia = date.today()
    db.session.commit()
    args = dict(academia_id=tarifario.academia_id, tarifario_id=tarifario.id, plan_id=plan.id, frecuencia_id=frecuencia.id)
    for fecha in (tarifario.fecha_inicio_vigencia, tarifario.fecha_fin_vigencia):
        assert calcular_tarifa(**args, contexto_descuentos={"fecha": fecha}).tarifa_base == Decimal("50.00")
    client = cliente(app, base_data["admin_a"])
    response = client.post("/finanzas/tarifarios/nuevo", data=datos_tarifario(estado="BORRADOR", fecha_inicio_vigencia="2099-01-01"))
    nuevo = Tarifario.query.filter_by(nombre="Precios nuevos").one()
    assert response.status_code == 302
    assert client.post(f"/finanzas/tarifarios/{nuevo.id}/tarifas/nueva", data=datos_tarifa(catalogo)).status_code == 302


def test_edicion_precio_desactivacion_y_cierre_conservan_historia(app, db, base_data, catalogo):
    tarifario, plan, frecuencia, tarifa = catalogo["a"]
    inicio = date.today().replace(day=1)
    asignacion = asignar_plan_financiero(academia_id=tarifario.academia_id, alumno_id=base_data["alumno_a1"].id, plan_id=plan.id, frecuencia_id=frecuencia.id, fecha_inicio=inicio)
    generar_obligaciones_mensuales(academia_id=tarifario.academia_id, periodo=inicio.strftime("%Y-%m"))
    db.session.commit()
    obligacion = ObligacionFinanciera.query.filter_by(alumno_plan_financiero_id=asignacion.id).one()
    client = cliente(app, base_data["admin_a"])
    assert client.post(url_tarifa(catalogo), data=datos_tarifa(catalogo, academia_id=base_data["academia_b"].id)).status_code == 302
    assert tarifa.valor_base == Decimal("65.25")
    assert asignacion.valor_final_snapshot == obligacion.valor_final_snapshot == Decimal("50.00")
    otro_plan = PlanFinanciero(academia_id=tarifario.academia_id, codigo="OTRO", nombre="Otro")
    db.session.add(otro_plan)
    db.session.commit()
    assert b"conserva su plan" in client.post(url_tarifa(catalogo), data=datos_tarifa(catalogo, plan_id=otro_plan.id)).data
    assert client.post(url_tarifa(catalogo, "alternar-activo")).status_code == 302
    assert not tarifa.activo
    assert client.post(url_tarifa(catalogo, "alternar-activo")).status_code == 302
    assert tarifa.activo
    editar = f"/finanzas/tarifarios/{tarifario.id}/editar"
    datos = datos_tarifario(nombre=tarifario.nombre, estado="VIGENTE", fecha_inicio_vigencia=inicio.isoformat())
    assert b"conserva su moneda" in client.post(editar, data={**datos, "moneda": "EUR"}).data
    assert client.post(editar, data={**datos, "estado": "CERRADO"}).status_code == 302
    assert b"cerrado o vencido" in client.post(url_tarifa(catalogo), data=datos_tarifa(catalogo)).data
    assert client.post(url_tarifa(catalogo, "alternar-activo")).status_code == 302
    assert tarifa.activo
    for url in (f"/finanzas/tarifarios/{tarifario.id}/eliminar", url_tarifa(catalogo, "eliminar")):
        assert client.post(url).status_code == 404
    assert client.delete(editar).status_code == 405
    assert Tarifario.query.count() == TarifaPlan.query.count() == 2
    assert asignacion.valor_final_snapshot == obligacion.valor_final_snapshot == Decimal("50.00")


def test_duplicado_y_reactivacion_con_referencia_inactiva(app, db, base_data, catalogo):
    tarifario, plan, _, tarifa = catalogo["a"]
    client = cliente(app, base_data["admin_a"])
    assert b"Ya existe" in client.post(f"/finanzas/tarifarios/{tarifario.id}/tarifas/nueva", data=datos_tarifa(catalogo)).data
    client.post(url_tarifa(catalogo, "alternar-activo"))
    plan.activo = False
    db.session.commit()
    response = client.post(url_tarifa(catalogo, "alternar-activo"), follow_redirects=True)
    assert b"no disponible" in response.data
    assert not tarifa.activo


def test_profesor_no_administra(app, db, base_data, catalogo):
    client = cliente(app, base_data["profesor_a"])
    tarifario = catalogo["a"][0]
    urls = ["/finanzas/tarifarios", "/finanzas/tarifarios/nuevo", f"/finanzas/tarifarios/{tarifario.id}/editar", f"/finanzas/tarifarios/{tarifario.id}/tarifas", f"/finanzas/tarifarios/{tarifario.id}/tarifas/nueva", url_tarifa(catalogo)]
    for url in urls:
        assert client.get(url).status_code == 403
    for url in (urls[1], urls[2], urls[4], urls[5], url_tarifa(catalogo, "alternar-activo")):
        assert client.post(url, data=datos_tarifa(catalogo)).status_code == 403
    assert b'href="/finanzas/tarifarios"' not in client.get("/finanzas/cartera").data


def test_csrf_todas_las_mutaciones(app, db, base_data, catalogo, monkeypatch):
    client = cliente(app, base_data["admin_a"])
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    tarifario = catalogo["a"][0]
    urls = ["/finanzas/tarifarios/nuevo", f"/finanzas/tarifarios/{tarifario.id}/editar", f"/finanzas/tarifarios/{tarifario.id}/tarifas/nueva", url_tarifa(catalogo), url_tarifa(catalogo, "alternar-activo")]
    for url in urls:
        assert client.post(url, data=datos_tarifa(catalogo)).status_code == 400
        if not url.endswith("alternar-activo"):
            assert b'name="csrf_token"' in client.get(url).data
    assert Tarifario.query.count() == 2 and TarifaPlan.query.count() == 2


def test_superadmin_requiere_academia_y_no_tiene_selector_global(app, db, base_data, catalogo):
    usuario = base_data["admin_a"]
    usuario.roles = [Role(name="SUPERADMIN", description="Superadmin")]
    db.session.commit()
    client = cliente(app, usuario)
    assert client.post("/finanzas/tarifarios/nuevo", data=datos_tarifario()).status_code == 302
    assert client.get(f"/finanzas/tarifarios/{catalogo['b'][0].id}/editar").status_code == 404
    usuario.academia_id = None
    db.session.commit()
    assert client.get("/finanzas/tarifarios").status_code == 403
    assert client.post("/finanzas/tarifarios/nuevo", data=datos_tarifario()).status_code == 403


def test_editar_tarifario_persiste_campos_sin_cambiar_academia(app, db, base_data, catalogo):
    client = cliente(app, base_data["admin_a"])
    tarifario = catalogo["a"][0]
    autor_original = tarifario.created_by_id
    creacion_original = tarifario.created_at
    inicio = date.today() + timedelta(days=5)
    fin = inicio + timedelta(days=30)
    response = client.post(
        f"/finanzas/tarifarios/{tarifario.id}/editar",
        data=datos_tarifario(
            nombre="Tarifario editado", descripcion="Nueva descripcion", moneda="eur",
            estado="VIGENTE", fecha_inicio_vigencia=inicio.isoformat(),
            fecha_fin_vigencia=fin.isoformat(), academia_id=base_data["academia_b"].id,
            created_by_id=base_data["admin_b"].id,
        ),
    )
    assert response.status_code == 302
    db.session.refresh(tarifario)
    assert (tarifario.nombre, tarifario.descripcion, tarifario.moneda) == ("Tarifario editado", "Nueva descripcion", "EUR")
    assert (tarifario.fecha_inicio_vigencia, tarifario.fecha_fin_vigencia, tarifario.estado) == (inicio, fin, "VIGENTE")
    assert tarifario.academia_id == base_data["academia_a"].id
    assert tarifario.created_by_id == autor_original and tarifario.created_at == creacion_original
    assert catalogo["b"][0].nombre == "Tarifario b"
    assert b"Tarifario editado" in client.get(response.location).data


def test_editar_tarifa_persiste_campos_y_referencias_del_tenant(app, db, base_data, catalogo):
    tarifario, _, _, tarifa = catalogo["a"]
    plan = PlanFinanciero(academia_id=tarifario.academia_id, codigo="COMPETIDOR", nombre="Competidor")
    frecuencia = FrecuenciaEntrenamiento(academia_id=tarifario.academia_id, codigo="D5", nombre="Cinco dias", dias_semana=5)
    db.session.add_all([plan, frecuencia])
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    response = client.post(url_tarifa(catalogo), data=datos_tarifa(
        catalogo, plan_id=plan.id, frecuencia_id=frecuencia.id, valor_base="80.50",
        observaciones="Precio editado", activo="", academia_id=base_data["academia_b"].id,
        tarifario_id=catalogo["b"][0].id,
    ))
    assert response.status_code == 302
    db.session.refresh(tarifa)
    assert (tarifa.plan_id, tarifa.frecuencia_id, tarifa.valor_base) == (plan.id, frecuencia.id, Decimal("80.50"))
    assert tarifa.observaciones == "Precio editado" and not tarifa.activo
    assert tarifa.academia_id == tarifario.academia_id and tarifa.tarifario_id == tarifario.id
    assert catalogo["b"][3].valor_base == Decimal("50.00")
    detalle = client.get(response.location)
    assert b"Competidor" in detalle.data and b"80.50" in detalle.data and b"Inactiva" in detalle.data


def test_publicar_borrador_valida_solapamiento_y_permite_otro_tenant(app, db, base_data, catalogo):
    tarifario = catalogo["a"][0]
    tarifario.estado = "BORRADOR"
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    editar = f"/finanzas/tarifarios/{tarifario.id}/editar"
    datos = datos_tarifario(nombre=tarifario.nombre, estado="VIGENTE", fecha_inicio_vigencia=tarifario.fecha_inicio_vigencia.isoformat())
    # El tarifario VIGENTE de B tiene las mismas fechas y no debe bloquear a A.
    assert client.post(editar, data=datos).status_code == 302
    assert tarifario.estado == "VIGENTE"
    assert client.post("/finanzas/tarifarios/nuevo", data=datos_tarifario()).status_code == 302
    borrador = Tarifario.query.filter_by(nombre="Precios nuevos").one()
    publicar = f"/finanzas/tarifarios/{borrador.id}/editar"
    assert b"solapa" in client.post(publicar, data=datos_tarifario(estado="VIGENTE")).data
    db.session.refresh(borrador)
    assert borrador.estado == "BORRADOR"


@pytest.mark.parametrize("estado", ["CERRADO", "VENCIDO"])
def test_web_bloquea_alta_edicion_y_activacion_en_tarifario_no_editable(app, db, base_data, catalogo, estado):
    tarifario, _, _, tarifa = catalogo["a"]
    if estado == "CERRADO":
        tarifario.estado = estado
    else:
        tarifario.fecha_inicio_vigencia = date.today() - timedelta(days=10)
        tarifario.fecha_fin_vigencia = date.today() - timedelta(days=1)
    tarifa.activo = False
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    alta = f"/finanzas/tarifarios/{tarifario.id}/tarifas/nueva"
    for url in (alta, url_tarifa(catalogo)):
        assert b"disabled" in client.get(url).data
        response = client.post(url, data=datos_tarifa(catalogo))
        assert response.status_code == 200 and b"cerrado o vencido" in response.data
    response = client.post(url_tarifa(catalogo, "alternar-activo"), follow_redirects=True)
    assert b"cerrado o vencido" in response.data
    db.session.refresh(tarifa)
    assert not tarifa.activo and tarifa.valor_base == Decimal("50.00")
    assert TarifaPlan.query.count() == 2


def test_edicion_fechas_invalidas_y_publicacion_vencida_no_persisten(app, db, base_data, catalogo):
    tarifario = catalogo["a"][0]
    original = (tarifario.nombre, tarifario.fecha_inicio_vigencia, tarifario.fecha_fin_vigencia, tarifario.estado)
    client = cliente(app, base_data["admin_a"])
    editar = f"/finanzas/tarifarios/{tarifario.id}/editar"
    response = client.post(editar, data=datos_tarifario(
        estado="VIGENTE", fecha_inicio_vigencia=date.today().isoformat(),
        fecha_fin_vigencia=(date.today() - timedelta(days=1)).isoformat(),
    ))
    assert b"anterior al inicio" in response.data
    response = client.post(editar, data=datos_tarifario(
        estado="VIGENTE", fecha_inicio_vigencia=(date.today() - timedelta(days=2)).isoformat(),
        fecha_fin_vigencia=(date.today() - timedelta(days=1)).isoformat(),
    ))
    assert b"vigencia ya termino" in response.data
    db.session.refresh(tarifario)
    assert (tarifario.nombre, tarifario.fecha_inicio_vigencia, tarifario.fecha_fin_vigencia, tarifario.estado) == original
