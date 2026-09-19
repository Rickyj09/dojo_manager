from datetime import date

import pytest

from app.models.finanzas import AlumnoGrupoFamiliar, GrupoFamiliar
from app.services.finanzas.familias import (
    asignar_alumno_a_familia,
    crear_grupo_familiar,
)


def cliente(app, usuario):
    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={
            "username": usuario.username,
            "password": "secret",
        },
    )
    assert response.status_code == 302
    return client


def crear_familia(
    db,
    academia_id,
    codigo,
    nombre,
    *,
    observaciones=None,
    activo=True,
):
    familia = crear_grupo_familiar(
        academia_id=academia_id,
        codigo=codigo,
        nombre=nombre,
        observaciones=observaciones,
    )
    familia.activo = activo
    db.session.commit()
    return familia


def datos_familia(**cambios):
    datos = {
        "codigo": "FAM-000001",
        "nombre": "Familia Perez",
        "observaciones": "Familia de prueba",
    }
    datos.update(cambios)
    return datos


def test_admin_lista_solo_familias_de_su_academia(app, db, base_data):
    familia_a = crear_familia(
        db,
        base_data["academia_a"].id,
        "FAM-A",
        "Familia Alpha",
    )
    familia_b = crear_familia(
        db,
        base_data["academia_b"].id,
        "FAM-B",
        "Familia Beta",
    )

    client = cliente(app, base_data["admin_a"])
    response = client.get("/finanzas/familias")

    assert response.status_code == 200
    assert familia_a.nombre.encode() in response.data
    assert familia_b.nombre.encode() not in response.data
    assert b"Nueva familia" in response.data


def test_admin_puede_crear_familia_y_no_inyectar_academia(
    app,
    db,
    base_data,
):
    client = cliente(app, base_data["admin_a"])

    response = client.post(
        "/finanzas/familias/nueva",
        data=datos_familia(
            academia_id=str(base_data["academia_b"].id),
        ),
    )

    assert response.status_code == 302

    familia = GrupoFamiliar.query.filter_by(
        nombre="Familia Perez",
    ).one()

    assert familia.academia_id == base_data["academia_a"].id
    assert familia.codigo == "FAM_000001"
    assert familia.activo is True
    assert response.location.endswith(
        f"/finanzas/familias/{familia.id}"
    )


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("codigo", ""),
        ("nombre", ""),
        ("codigo", "   "),
        ("nombre", "   "),
    ],
)
def test_creacion_requiere_codigo_y_nombre(
    app,
    db,
    base_data,
    campo,
    valor,
):
    client = cliente(app, base_data["admin_a"])
    datos = datos_familia(**{campo: valor})

    response = client.post(
        "/finanzas/familias/nueva",
        data=datos,
    )

    assert response.status_code == 200
    assert GrupoFamiliar.query.filter_by(
        academia_id=base_data["academia_a"].id,
    ).count() == 0


def test_codigo_duplicado_mismo_tenant_es_rechazado(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id

    crear_familia(
        db,
        academia_id,
        "FAM-000001",
        "Familia Original",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        "/finanzas/familias/nueva",
        data=datos_familia(nombre="Familia Duplicada"),
    )

    assert response.status_code == 200
    assert GrupoFamiliar.query.filter_by(
        academia_id=academia_id,
        codigo="FAM_000001",
    ).count() == 1


def test_mismo_codigo_es_permitido_en_otro_tenant(
    app,
    db,
    base_data,
):
    crear_familia(
        db,
        base_data["academia_b"].id,
        "FAM-000001",
        "Familia Tenant B",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        "/finanzas/familias/nueva",
        data=datos_familia(nombre="Familia Tenant A"),
    )

    assert response.status_code == 302

    assert GrupoFamiliar.query.filter_by(
        codigo="FAM_000001",
    ).count() == 2


def test_busqueda_por_codigo_y_nombre(app, db, base_data):
    academia_id = base_data["academia_a"].id

    crear_familia(
        db,
        academia_id,
        "FAM-ALFA",
        "Familia Perez",
    )
    crear_familia(
        db,
        academia_id,
        "FAM-BETA",
        "Familia Andrade",
    )

    client = cliente(app, base_data["admin_a"])

    por_codigo = client.get(
        "/finanzas/familias?q=ALFA"
    )
    assert b"Familia Perez" in por_codigo.data
    assert b"Familia Andrade" not in por_codigo.data

    por_nombre = client.get(
        "/finanzas/familias?q=Andrade"
    )
    assert b"Familia Andrade" in por_nombre.data
    assert b"Familia Perez" not in por_nombre.data


def test_filtros_activas_e_inactivas(app, db, base_data):
    academia_id = base_data["academia_a"].id

    crear_familia(
        db,
        academia_id,
        "FAM-ACTIVA",
        "Familia Activa",
        activo=True,
    )
    crear_familia(
        db,
        academia_id,
        "FAM-INACTIVA",
        "Familia Inactiva",
        activo=False,
    )

    client = cliente(app, base_data["admin_a"])

    activas = client.get(
        "/finanzas/familias?estado=activas"
    )
    assert b"Familia Activa" in activas.data
    assert b"Familia Inactiva" not in activas.data

    inactivas = client.get(
        "/finanzas/familias?estado=inactivas"
    )
    assert b"Familia Inactiva" in inactivas.data
    assert b"Familia Activa" not in inactivas.data


def test_admin_puede_editar_nombre_y_observaciones_pero_no_codigo(
    app,
    db,
    base_data,
):
    familia = crear_familia(
        db,
        base_data["academia_a"].id,
        "FAM-ORIGINAL",
        "Familia Original",
        observaciones="Anterior",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        f"/finanzas/familias/{familia.id}/editar",
        data={
            "codigo": "CODIGO-MANIPULADO",
            "nombre": "Familia Actualizada",
            "observaciones": "Nueva observacion",
        },
    )

    assert response.status_code == 302

    db.session.refresh(familia)

    assert familia.codigo == "FAM_ORIGINAL"
    assert familia.nombre == "Familia Actualizada"
    assert familia.observaciones == "Nueva observacion"


def test_academia_no_puede_ver_editar_o_alternar_familia_ajena(
    app,
    db,
    base_data,
):
    familia_b = crear_familia(
        db,
        base_data["academia_b"].id,
        "FAM-B",
        "Familia B",
    )

    client = cliente(app, base_data["admin_a"])

    assert client.get(
        f"/finanzas/familias/{familia_b.id}"
    ).status_code == 404

    assert client.get(
        f"/finanzas/familias/{familia_b.id}/editar"
    ).status_code == 404

    assert client.post(
        f"/finanzas/familias/{familia_b.id}/editar",
        data={
            "nombre": "Manipulada",
            "observaciones": "",
        },
    ).status_code == 404

    assert client.post(
        f"/finanzas/familias/{familia_b.id}/alternar-activo"
    ).status_code == 404

    db.session.refresh(familia_b)
    assert familia_b.activo is True
    assert familia_b.nombre == "Familia B"


def test_no_permite_desactivar_familia_con_integrantes_activos(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id

    familia = crear_familia(
        db,
        academia_id,
        "FAM-ACTIVA",
        "Familia Activa",
    )

    asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        grupo_familiar_id=familia.id,
        fecha_inicio=date.today(),
    )
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        f"/finanzas/familias/{familia.id}/alternar-activo",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"No se puede desactivar" in response.data

    db.session.refresh(familia)
    assert familia.activo is True


def test_desactivar_y_reactivar_familia_sin_integrantes_activos(
    app,
    db,
    base_data,
):
    familia = crear_familia(
        db,
        base_data["academia_a"].id,
        "FAM-ESTADO",
        "Familia Estado",
    )

    client = cliente(app, base_data["admin_a"])
    url = (
        f"/finanzas/familias/"
        f"{familia.id}/alternar-activo"
    )

    response = client.post(url)
    assert response.status_code == 302

    db.session.refresh(familia)
    assert familia.activo is False

    response = client.post(url)
    assert response.status_code == 302

    db.session.refresh(familia)
    assert familia.activo is True


def test_profesor_puede_consultar_familia_visible_pero_no_modificar(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id
    profesor = base_data["profesor_a"]
    alumno = base_data["alumno_a1"]

    assert profesor.sucursal_id is not None
    alumno.sucursal_id = profesor.sucursal_id

    familia = crear_grupo_familiar(
        academia_id=academia_id,
        codigo="FAM-PROFESOR",
        nombre="Familia Visible Profesor",
    )
    db.session.flush()

    asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=alumno.id,
        grupo_familiar_id=familia.id,
        fecha_inicio=date.today(),
    )
    db.session.commit()

    client = cliente(app, profesor)

    listado = client.get("/finanzas/familias")
    assert listado.status_code == 200
    assert b"Familia Visible Profesor" in listado.data
    assert b"Nueva familia" not in listado.data

    detalle = client.get(
        f"/finanzas/familias/{familia.id}"
    )
    assert detalle.status_code == 200
    assert b"Familia Visible Profesor" in detalle.data

    assert client.get(
        "/finanzas/familias/nueva"
    ).status_code == 403

    assert client.post(
        "/finanzas/familias/nueva",
        data=datos_familia(),
    ).status_code == 403

    assert client.get(
        f"/finanzas/familias/{familia.id}/editar"
    ).status_code == 403

    assert client.post(
        f"/finanzas/familias/{familia.id}/alternar-activo"
    ).status_code == 403


def test_profesor_no_ve_familia_sin_alumnos_visibles(
    app,
    db,
    base_data,
):
    familia = crear_familia(
        db,
        base_data["academia_a"].id,
        "FAM-OCULTA",
        "Familia Oculta Profesor",
    )

    client = cliente(app, base_data["profesor_a"])

    listado = client.get("/finanzas/familias")
    assert listado.status_code == 200
    assert b"Familia Oculta Profesor" not in listado.data

    assert client.get(
        f"/finanzas/familias/{familia.id}"
    ).status_code == 403


def test_usuario_sin_rol_financiero_recibe_403(
    app,
    db,
    base_data,
):
    usuario = base_data["admin_a"]
    usuario.roles = []
    db.session.commit()

    client = cliente(app, usuario)

    assert client.get(
        "/finanzas/familias"
    ).status_code == 403

    assert client.get(
        "/finanzas/familias/nueva"
    ).status_code == 403


def test_csrf_protege_mutaciones_de_familias(
    app,
    db,
    base_data,
    monkeypatch,
):
    familia = crear_familia(
        db,
        base_data["academia_a"].id,
        "FAM-CSRF",
        "Familia CSRF",
    )

    client = cliente(app, base_data["admin_a"])

    monkeypatch.setitem(
        app.config,
        "WTF_CSRF_ENABLED",
        True,
    )

    urls = [
        "/finanzas/familias/nueva",
        f"/finanzas/familias/{familia.id}/editar",
        (
            f"/finanzas/familias/"
            f"{familia.id}/alternar-activo"
        ),
    ]

    assert client.post(
        urls[0],
        data=datos_familia(),
    ).status_code == 400

    assert client.post(
        urls[1],
        data={
            "nombre": "Cambio",
            "observaciones": "",
        },
    ).status_code == 400

    assert client.post(
        urls[2],
    ).status_code == 400

    assert b'name="csrf_token"' in client.get(
        "/finanzas/familias/nueva"
    ).data

    assert b'name="csrf_token"' in client.get(
        f"/finanzas/familias/{familia.id}/editar"
    ).data

    assert b'name="csrf_token"' in client.get(
        f"/finanzas/familias/{familia.id}"
    ).data

def test_admin_puede_agregar_integrante_a_familia(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id

    familia = crear_familia(
        db,
        academia_id,
        "FAM-INTEGRANTES",
        "Familia Integrantes",
    )

    alumno = base_data["alumno_a1"]

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        f"/finanzas/familias/{familia.id}/integrantes",
        data={
            "alumno_id": str(alumno.id),
            "fecha_inicio": "2026-09-01",
        },
    )

    assert response.status_code == 302

    membresia = AlumnoGrupoFamiliar.query.filter_by(
        academia_id=academia_id,
        grupo_familiar_id=familia.id,
        alumno_id=alumno.id,
    ).one()

    assert membresia.activo is True
    assert membresia.fecha_inicio == date(2026, 9, 1)
    assert membresia.fecha_fin is None


def test_detalle_muestra_integrante_activo(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id

    familia = crear_familia(
        db,
        academia_id,
        "FAM-DETALLE",
        "Familia Detalle",
    )

    alumno = base_data["alumno_a1"]

    asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=alumno.id,
        grupo_familiar_id=familia.id,
        fecha_inicio=date(2026, 9, 1),
    )
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    response = client.get(
        f"/finanzas/familias/{familia.id}"
    )

    assert response.status_code == 200
    assert alumno.nombres.encode() in response.data
    assert alumno.apellidos.encode() in response.data
    assert b"ACTIVO" in response.data
    assert b"Retirar" in response.data


def test_no_permite_agregar_alumno_de_otro_tenant(
    app,
    db,
    base_data,
):
    familia = crear_familia(
        db,
        base_data["academia_a"].id,
        "FAM-A",
        "Familia A",
    )

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        f"/finanzas/familias/{familia.id}/integrantes",
        data={
            "alumno_id": str(base_data["alumno_b1"].id),
            "fecha_inicio": "2026-09-01",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Alumno no pertenece" in response.data

    assert AlumnoGrupoFamiliar.query.filter_by(
        academia_id=base_data["academia_a"].id,
        grupo_familiar_id=familia.id,
    ).count() == 0


def test_no_permite_alumno_en_dos_familias_activas(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id
    alumno = base_data["alumno_a1"]

    familia_1 = crear_familia(
        db,
        academia_id,
        "FAM-1",
        "Familia 1",
    )

    familia_2 = crear_familia(
        db,
        academia_id,
        "FAM-2",
        "Familia 2",
    )

    asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=alumno.id,
        grupo_familiar_id=familia_1.id,
        fecha_inicio=date(2026, 9, 1),
    )
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        f"/finanzas/familias/{familia_2.id}/integrantes",
        data={
            "alumno_id": str(alumno.id),
            "fecha_inicio": "2026-09-15",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"familia activa" in response.data

    assert AlumnoGrupoFamiliar.query.filter_by(
        alumno_id=alumno.id,
        activo=True,
    ).count() == 1


def test_admin_puede_retirar_integrante_y_conserva_historial(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id
    alumno = base_data["alumno_a1"]

    familia = crear_familia(
        db,
        academia_id,
        "FAM-RETIRO",
        "Familia Retiro",
    )

    membresia = asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=alumno.id,
        grupo_familiar_id=familia.id,
        fecha_inicio=date(2026, 9, 1),
    )
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        (
            f"/finanzas/familias/{familia.id}/integrantes/"
            f"{membresia.id}/retirar"
        ),
        data={
            "fecha_fin": "2026-10-15",
        },
    )

    assert response.status_code == 302

    db.session.refresh(membresia)

    assert membresia.activo is False
    assert membresia.fecha_fin == date(2026, 10, 15)

    detalle = client.get(
        f"/finanzas/familias/{familia.id}"
    )

    assert b"HIST" in detalle.data
    assert alumno.nombres.encode() in detalle.data


def test_retiro_rechaza_fecha_anterior_al_ingreso(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id
    alumno = base_data["alumno_a1"]

    familia = crear_familia(
        db,
        academia_id,
        "FAM-FECHA",
        "Familia Fecha",
    )

    membresia = asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=alumno.id,
        grupo_familiar_id=familia.id,
        fecha_inicio=date(2026, 9, 10),
    )
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        (
            f"/finanzas/familias/{familia.id}/integrantes/"
            f"{membresia.id}/retirar"
        ),
        data={
            "fecha_fin": "2026-09-01",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"anterior" in response.data

    db.session.refresh(membresia)
    assert membresia.activo is True
    assert membresia.fecha_fin is None


def test_membresia_de_otra_familia_no_puede_retirarse(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id

    familia_1 = crear_familia(
        db,
        academia_id,
        "FAM-1",
        "Familia 1",
    )

    familia_2 = crear_familia(
        db,
        academia_id,
        "FAM-2",
        "Familia 2",
    )

    membresia = asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=base_data["alumno_a1"].id,
        grupo_familiar_id=familia_1.id,
        fecha_inicio=date(2026, 9, 1),
    )
    db.session.commit()

    client = cliente(app, base_data["admin_a"])

    response = client.post(
        (
            f"/finanzas/familias/{familia_2.id}/integrantes/"
            f"{membresia.id}/retirar"
        ),
        data={
            "fecha_fin": "2026-10-01",
        },
    )

    assert response.status_code == 404

    db.session.refresh(membresia)
    assert membresia.activo is True


def test_profesor_no_puede_agregar_ni_retirar_integrantes(
    app,
    db,
    base_data,
):
    academia_id = base_data["academia_a"].id
    alumno = base_data["alumno_a1"]

    profesor = base_data["profesor_a"]
    alumno.sucursal_id = profesor.sucursal_id

    familia = crear_familia(
        db,
        academia_id,
        "FAM-PROF",
        "Familia Profesor",
    )

    membresia = asignar_alumno_a_familia(
        academia_id=academia_id,
        alumno_id=alumno.id,
        grupo_familiar_id=familia.id,
        fecha_inicio=date(2026, 9, 1),
    )
    db.session.commit()

    client = cliente(app, profesor)

    assert client.post(
        f"/finanzas/familias/{familia.id}/integrantes",
        data={
            "alumno_id": str(base_data["alumno_a2"].id),
            "fecha_inicio": "2026-09-01",
        },
    ).status_code == 403

    assert client.post(
        (
            f"/finanzas/familias/{familia.id}/integrantes/"
            f"{membresia.id}/retirar"
        ),
        data={
            "fecha_fin": "2026-10-01",
        },
    ).status_code == 403