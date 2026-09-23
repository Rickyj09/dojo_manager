from datetime import date

from app.models.sucursal import Sucursal
from app.models.torneo import Torneo
from test_finanzas_tarifarios_ui import cliente


def test_torneos_admin_solo_ve_su_academia(
    app,
    db,
    base_data,
):
    torneo_a = Torneo(
        academia_id=base_data["academia_a"].id,
        nombre="TORNEO_VISIBLE_A",
        ciudad="Quito",
        fecha=date(2026, 11, 1),
        organizador="Academia A",
        activo=True,
    )

    torneo_b = Torneo(
        academia_id=base_data["academia_b"].id,
        nombre="TORNEO_PROHIBIDO_B",
        ciudad="Quito",
        fecha=date(2026, 11, 2),
        organizador="Academia B",
        activo=True,
    )

    db.session.add_all([
        torneo_a,
        torneo_b,
    ])
    db.session.commit()

    client = cliente(
        app,
        base_data["admin_a"],
    )

    response = client.get("/torneos/")

    assert response.status_code == 200
    assert b"TORNEO_VISIBLE_A" in response.data
    assert b"TORNEO_PROHIBIDO_B" not in response.data


def test_nuevo_torneo_se_asigna_a_academia_actual(
    app,
    db,
    base_data,
):
    client = cliente(
        app,
        base_data["admin_a"],
    )

    response = client.post(
        "/torneos/nuevo",
        data={
            "nombre": "TORNEO_NUEVO_TENANT_A",
            "ciudad": "Quito",
            "fecha": "2026-11-10",
            "organizador": "Academia A",
            "precio_poomsae": "30",
            "precio_combate": "30",
            "precio_ambas": "40",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    torneo = Torneo.query.filter_by(
        nombre="TORNEO_NUEVO_TENANT_A"
    ).one()

    assert (
        torneo.academia_id
        == base_data["academia_a"].id
    )


def test_ranking_admin_solo_ve_su_academia(
    app,
    db,
    base_data,
):
    base_data["alumno_a1"].nombres = (
        "RANKING_VISIBLE_A"
    )

    base_data["alumno_b1"].nombres = (
        "RANKING_PROHIBIDO_B"
    )

    db.session.commit()

    client = cliente(
        app,
        base_data["admin_a"],
    )

    response = client.get("/ranking/")

    assert response.status_code == 200
    assert b"RANKING_VISIBLE_A" in response.data
    assert b"RANKING_PROHIBIDO_B" not in response.data


def test_ranking_profesor_solo_ve_su_sucursal(
    app,
    db,
    base_data,
):
    otra_sucursal = Sucursal(
        academia_id=base_data["academia_a"].id,
        nombre="Sucursal Ranking No Visible",
        activo=True,
    )

    db.session.add(otra_sucursal)
    db.session.flush()

    base_data["alumno_a1"].nombres = (
        "RANKING_PROFESOR_VISIBLE"
    )
    base_data["alumno_a1"].sucursal_id = (
        base_data["profesor_a"].sucursal_id
    )

    base_data["alumno_a2"].nombres = (
        "RANKING_PROFESOR_PROHIBIDO"
    )
    base_data["alumno_a2"].sucursal_id = (
        otra_sucursal.id
    )

    db.session.commit()

    client = cliente(
        app,
        base_data["profesor_a"],
    )

    response = client.get("/ranking/")

    assert response.status_code == 200
    assert (
        b"RANKING_PROFESOR_VISIBLE"
        in response.data
    )
    assert (
        b"RANKING_PROFESOR_PROHIBIDO"
        not in response.data
    )


def test_participaciones_admin_no_abre_alumno_otro_tenant(
    app,
    db,
    base_data,
):
    client = cliente(
        app,
        base_data["admin_a"],
    )

    response = client.get(
        "/participaciones/nuevo/"
        f"{base_data['alumno_b1'].id}"
    )

    assert response.status_code == 404


def test_participaciones_profesor_no_abre_otra_sucursal(
    app,
    db,
    base_data,
):
    otra_sucursal = Sucursal(
        academia_id=base_data["academia_a"].id,
        nombre="Sucursal Participacion No Visible",
        activo=True,
    )

    db.session.add(otra_sucursal)
    db.session.flush()

    base_data["alumno_a2"].sucursal_id = (
        otra_sucursal.id
    )

    db.session.commit()

    client = cliente(
        app,
        base_data["profesor_a"],
    )

    response = client.get(
        "/participaciones/nuevo/"
        f"{base_data['alumno_a2'].id}"
    )

    assert response.status_code == 403


def test_participaciones_post_rechaza_torneo_otro_tenant(
    app,
    db,
    base_data,
):
    torneo_b = Torneo(
        academia_id=base_data["academia_b"].id,
        nombre="TORNEO_POST_PROHIBIDO_B",
        ciudad="Quito",
        fecha=date(2026, 11, 15),
        organizador="Academia B",
        activo=True,
    )

    db.session.add(torneo_b)
    db.session.commit()

    client = cliente(
        app,
        base_data["admin_a"],
    )

    response = client.post(
        "/participaciones/nuevo/"
        f"{base_data['alumno_a1'].id}",
        data={
            "torneo_id": str(torneo_b.id),
            "modalidad": "POOMSAE",
            "medalla_id": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 404