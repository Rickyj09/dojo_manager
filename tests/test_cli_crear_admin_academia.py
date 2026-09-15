from app.models.academia import Academia
from app.models.role import Role
from app.models.user import User


def test_crear_admin_academia_es_idempotente_y_respeta_tenant(app, db, monkeypatch):
    academia = Academia(nombre="Borjas Lions", activo=True)
    rol_admin = Role(name="ADMIN")
    db.session.add_all([academia, rol_admin])
    db.session.commit()

    monkeypatch.setenv("DOJOMANAGER_NEW_USER_PASSWORD", "clave-inicial-segura")
    runner = app.test_cli_runner()
    args = [
        "crear-admin-academia",
        "--academia",
        "Borjas Lions",
        "--username",
        "borjaslions.admin",
        "--email",
        "borjaslions.admin@example.test",
    ]

    resultado = runner.invoke(args=args)

    assert resultado.exit_code == 0, resultado.output
    usuario = User.query.filter_by(username="borjaslions.admin").one()
    assert usuario.academia_id == academia.id
    assert usuario.is_active is True
    assert [rol.name for rol in usuario.roles] == ["ADMIN"]
    assert usuario.check_password("clave-inicial-segura")
    assert "resultado: creado" in resultado.output
    assert f"academia_id: {academia.id}" in resultado.output

    monkeypatch.delenv("DOJOMANAGER_NEW_USER_PASSWORD")
    resultado_repetido = runner.invoke(args=args)

    assert resultado_repetido.exit_code == 0, resultado_repetido.output
    assert User.query.filter_by(username="borjaslions.admin").count() == 1
    assert "resultado: ya existía" in resultado_repetido.output


def test_crear_admin_academia_falla_si_borjas_lions_no_existe(app, db, monkeypatch):
    monkeypatch.setenv("DOJOMANAGER_NEW_USER_PASSWORD", "clave-inicial-segura")
    resultado = app.test_cli_runner().invoke(
        args=[
            "crear-admin-academia",
            "--academia",
            "Borjas Lions",
            "--username",
            "borjaslions.admin",
            "--email",
            "borjaslions.admin@example.test",
        ]
    )

    assert resultado.exit_code != 0
    assert "No existe la academia" in resultado.output
    assert User.query.filter_by(username="borjaslions.admin").count() == 0


def test_crear_admin_academia_no_permite_otro_tenant(app, db, monkeypatch):
    academia = Academia(nombre="Otra academia", activo=True)
    rol_admin = Role(name="ADMIN")
    db.session.add_all([academia, rol_admin])
    db.session.commit()
    monkeypatch.setenv("DOJOMANAGER_NEW_USER_PASSWORD", "clave-inicial-segura")

    resultado = app.test_cli_runner().invoke(
        args=[
            "crear-admin-academia",
            "--academia",
            "Otra academia",
            "--username",
            "borjaslions.admin",
            "--email",
            "borjaslions.admin@example.test",
        ]
    )

    assert resultado.exit_code != 0
    assert "solo permite la academia 'Borjas Lions'" in resultado.output
    assert User.query.count() == 0


def test_crear_admin_academia_valida_email_y_password(app, db, monkeypatch):
    academia = Academia(nombre="Borjas Lions", activo=True)
    rol_admin = Role(name="ADMIN")
    db.session.add_all([academia, rol_admin])
    db.session.flush()
    usuario_existente = User(
        username="otro.usuario",
        email="borjaslions.admin@example.test",
        academia_id=academia.id,
    )
    usuario_existente.set_password("clave-existente")
    db.session.add(usuario_existente)
    db.session.commit()
    monkeypatch.setenv("DOJOMANAGER_NEW_USER_PASSWORD", "clave-inicial-segura")
    args = [
        "crear-admin-academia",
        "--academia",
        "Borjas Lions",
        "--username",
        "borjaslions.admin",
        "--email",
        "borjaslions.admin@example.test",
    ]

    resultado_email = app.test_cli_runner().invoke(args=args)

    assert resultado_email.exit_code != 0
    assert "ya pertenece al usuario 'otro.usuario'" in resultado_email.output
    assert User.query.filter_by(username="otro.usuario").one().academia_id == academia.id
    assert User.query.filter_by(username="borjaslions.admin").count() == 0

    usuario_existente.email = "otro.usuario@example.test"
    db.session.commit()
    monkeypatch.delenv("DOJOMANAGER_NEW_USER_PASSWORD")
    resultado_password = app.test_cli_runner().invoke(args=args)

    assert resultado_password.exit_code != 0
    assert "DOJOMANAGER_NEW_USER_PASSWORD" in resultado_password.output
    assert User.query.filter_by(username="borjaslions.admin").count() == 0
