import importlib.util
import re
import shutil
from io import BytesIO
from pathlib import Path

import pytest
from flask import g, render_template
from PIL import Image
from sqlalchemy import create_engine, inspect, text
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.models.academia import Academia
from app.models.role import Role
from app.models.user import User
from app.services.branding import LOGO_MAX_BYTES, obtener_logo_academia


URL = "/academias/identidad-visual"


@pytest.fixture
def almacenamiento(app, tmp_path, monkeypatch):
    root = tmp_path / "static"
    (root / "img").mkdir(parents=True)
    shutil.copyfile(Path(app.static_folder) / "img/logoDojoManager.png", root / "img/logoDojoManager.png")
    monkeypatch.setattr(app, "static_folder", str(root))
    return root


def cliente(app, usuario):
    # La fixture global conserva un app_context: cada cliente debe resolver su usuario.
    g.pop("_login_user", None)
    client = app.test_client()
    with client.session_transaction() as sesion:
        sesion["_user_id"] = str(usuario.id)
        sesion["_fresh"] = True
    return client


def imagen(formato="PNG", color="red", size=(64, 64)):
    contenido = BytesIO()
    Image.new("RGB", size, color).save(contenido, format=formato)
    contenido.seek(0)
    return contenido


def subir(client, contenido=None, nombre="logo.png", **extra):
    return client.post(URL, data={"logo": (contenido or imagen(), nombre), **extra}, content_type="multipart/form-data")


def test_admin_sin_logo_pantalla_sidebar_y_dashboard(app, db, base_data, almacenamiento):
    client = cliente(app, base_data["admin_a"])
    assert obtener_logo_academia(base_data["academia_a"]) is None
    response = client.get(URL)
    assert response.status_code == 200
    assert "Identidad visual" in response.text and "Academia A" in response.text
    assert "Logo predeterminado de Dojo_Manager" in response.text
    assert 'enctype="multipart/form-data"' in response.text and 'name="csrf_token"' in response.text
    dashboard = client.get("/admin/")
    assert 'src="/static/img/logoDojoManager.png"' in dashboard.text
    assert "Panel de Academia A" in dashboard.text and URL in dashboard.text


@pytest.mark.parametrize("formato,extension", [("PNG", "png"), ("JPEG", "jpg"), ("JPEG", "jpeg"), ("WEBP", "webp")])
def test_subir_imagen_valida_y_branding_comun(app, db, base_data, almacenamiento, formato, extension):
    academia = base_data["academia_a"]
    client = cliente(app, base_data["admin_a"])
    response = subir(client, imagen(formato), f"Logo academia.{extension}")
    assert response.status_code == 302 and response.location.endswith(URL)
    assert re.fullmatch(rf"uploads/academias/{academia.id}/[0-9a-f]{{32}}\.png", academia.logo_filename)
    assert obtener_logo_academia(academia) == academia.logo_filename
    with Image.open(almacenamiento / academia.logo_filename) as logo:
        assert logo.format == "PNG" and logo.size == (64, 64)
    for destino in (URL, "/admin/", "/finanzas/cartera",
                    f"/finanzas/alumnos/{base_data['alumno_a1'].id}/estado-cuenta"):
        response = client.get(destino)
        assert response.status_code == 200
        assert f'src="/static/{academia.logo_filename}"' in response.text
        assert f'rel="icon" href="/static/{academia.logo_filename}"' in response.text
        assert "Plataforma Dojo_Manager" in response.text
    archivo = client.get(f"/static/{academia.logo_filename}")
    assert archivo.status_code == 200 and archivo.mimetype == "image/png"
    assert archivo.headers["X-Content-Type-Options"] == "nosniff"


def test_tres_academias_aisladas_y_restaurar_no_afecta_otras(app, db, base_data, almacenamiento):
    a, b = base_data["academia_a"], base_data["academia_b"]
    c = Academia(nombre="Academia C")
    db.session.add(c)
    db.session.flush()
    usuario_c = User(username="admin_c", email="c@example.com", academia_id=c.id, password_hash="no-login",
                     roles=list(base_data["admin_a"].roles))
    db.session.add(usuario_c)
    db.session.commit()
    assert subir(cliente(app, base_data["admin_a"])).status_code == 302
    assert subir(cliente(app, base_data["admin_b"]), imagen(color="blue")).status_code == 302
    ruta_a, ruta_b = a.logo_filename, b.logo_filename
    for usuario, propia, ajena in [(base_data["admin_a"], ruta_a, ruta_b), (base_data["admin_b"], ruta_b, ruta_a),
                                   (usuario_c, "img/logoDojoManager.png", ruta_a)]:
        response = cliente(app, usuario).get("/admin/")
        assert response.status_code == 200
        assert f'src="/static/{propia}"' in response.text and ajena not in response.text
    client = cliente(app, base_data["admin_a"])
    assert subir(client, imagen(color="green")).status_code == 302
    ruta_nueva = a.logo_filename
    assert ruta_nueva != ruta_a
    assert not (almacenamiento / ruta_a).exists()
    assert (almacenamiento / ruta_nueva).is_file() and (almacenamiento / ruta_b).is_file()
    response = client.post(URL, data={"accion": "restaurar"}, follow_redirects=True)
    assert response.status_code == 200 and "Logo predeterminado restaurado" in response.text
    assert a.logo_filename is None and not (almacenamiento / ruta_nueva).exists()
    assert b.logo_filename == ruta_b and (almacenamiento / ruta_b).is_file()


@pytest.mark.parametrize("rol", ["PROFESOR", "COACH", "MONITOR"])
def test_roles_lectores_no_configuran_branding(app, db, base_data, almacenamiento, rol):
    assert subir(cliente(app, base_data["admin_a"])).status_code == 302
    usuario = base_data["profesor_a"]
    if rol != "PROFESOR":
        usuario.roles = [Role(name=rol)]
        db.session.commit()
    client = cliente(app, usuario)
    assert client.get(URL).status_code == 403
    assert subir(client).status_code == 403
    assert client.post(URL, data={"accion": "restaurar"}).status_code == 403
    with app.test_request_context():
        from flask_login import login_user
        login_user(usuario)
        html = render_template("base_admin.html")
        assert base_data["academia_a"].logo_filename in html
        assert URL not in html


def test_superadmin_limitado_a_academia_actual_y_sin_tenant(app, db, base_data, almacenamiento):
    usuario = base_data["admin_a"]
    usuario.roles = [Role(name="SUPERADMIN")]
    db.session.commit()
    client = cliente(app, usuario)
    assert subir(client).status_code == 302
    assert client.get(URL, query_string={"academia_id": base_data["academia_b"].id}).status_code == 403
    usuario.academia_id = None
    db.session.commit()
    assert client.get(URL).status_code == 403
    response = client.get("/admin/")
    assert response.status_code == 200 and 'src="/static/img/logoDojoManager.png"' in response.text


def test_parametros_y_rutas_cross_tenant_bloqueados(app, db, base_data, almacenamiento):
    b = base_data["academia_b"]
    assert subir(cliente(app, base_data["admin_b"])).status_code == 302
    anterior = b.logo_filename
    contenido = (almacenamiento / anterior).read_bytes()
    client = cliente(app, base_data["admin_a"])
    assert client.get(URL, query_string={"academia_id": b.id}).status_code == 403
    assert subir(client, academia_id=b.id).status_code == 403
    assert client.post(URL, data={"accion": "restaurar", "academia_id": b.id}).status_code == 403
    assert client.get(f"/academias/{b.id}/identidad-visual").status_code == 404
    assert client.post(f"/academias/{b.id}/identidad-visual", data={"accion": "restaurar"}).status_code == 404
    assert b.logo_filename == anterior and (almacenamiento / anterior).read_bytes() == contenido
    assert base_data["academia_a"].logo_filename is None


@pytest.mark.parametrize("nombre,contenido", [
    ("archivo.html", b"<html>malicioso</html>"), ("archivo.py", b"print('no')"),
    ("logo.png", b"<html>renombrado</html>"), ("logo.jpg", b"print('renombrado')"),
    ("logo.png", b"\x89PNG\r\n\x1a\n<html>falso</html>"),
    ("logo.webp", b"RIFF0000WEBP<script>falso</script>"), ("logo.png", b""),
])
def test_archivos_invalidos_rechazados(app, db, base_data, almacenamiento, nombre, contenido):
    response = subir(cliente(app, base_data["admin_a"]), BytesIO(contenido), nombre)
    assert response.status_code == 400
    assert base_data["academia_a"].logo_filename is None
    assert not list(almacenamiento.rglob("uploads/**/*.png"))


def test_formato_real_no_coincide_con_extension(app, db, base_data, almacenamiento):
    response = subir(cliente(app, base_data["admin_a"]), imagen("JPEG"), "logo.png")
    assert response.status_code == 400 and "no coincide" in response.text


@pytest.mark.parametrize("tamano", [LOGO_MAX_BYTES + 1, LOGO_MAX_BYTES * 2])
def test_logo_demasiado_grande(app, db, base_data, almacenamiento, tamano):
    client = cliente(app, base_data["admin_a"])
    response = subir(client, BytesIO(b"x" * tamano))
    if response.status_code == 302:
        response = client.get(response.location)
    assert "no puede superar los 2 MB" in response.text
    assert base_data["academia_a"].logo_filename is None


def test_dimensiones_excesivas_rechazadas(app, db, base_data, almacenamiento):
    response = subir(cliente(app, base_data["admin_a"]), imagen(size=(2001, 2000)))
    assert response.status_code == 400 and "4 millones" in response.text


def test_nombre_malicioso_no_controla_destino_y_elimina_contenido_extra(app, db, base_data, almacenamiento):
    contenido = imagen().getvalue() + b"<script>malicioso</script>"
    response = subir(cliente(app, base_data["admin_a"]), BytesIO(contenido), "../../otra_academia/logo.png")
    assert response.status_code == 302
    ruta = base_data["academia_a"].logo_filename
    assert ".." not in ruta and "otra_academia" not in ruta
    assert b"<script>" not in (almacenamiento / ruta).read_bytes()


@pytest.mark.parametrize("ruta", ["../../fuera.png", "img/logoDojoManager.png", "https://example.com/logo.png",
                                 "C:\\logo.png", "uploads/academias/999/" + "a" * 32 + ".png"])
def test_referencia_invalida_usa_fallback(app, db, base_data, almacenamiento, ruta):
    base_data["academia_a"].logo_filename = ruta
    db.session.commit()
    response = cliente(app, base_data["admin_a"]).get("/admin/")
    assert response.status_code == 200 and 'src="/static/img/logoDojoManager.png"' in response.text
    assert obtener_logo_academia(base_data["academia_a"]) is None


def test_logo_faltante_y_referencia_a_otro_tenant_usan_fallback(app, db, base_data, almacenamiento):
    assert subir(cliente(app, base_data["admin_b"])).status_code == 302
    a, b = base_data["academia_a"], base_data["academia_b"]
    a.logo_filename = b.logo_filename
    db.session.commit()
    client = cliente(app, base_data["admin_a"])
    assert obtener_logo_academia(a) is None
    assert client.post(URL, data={"accion": "restaurar"}).status_code == 302
    assert (almacenamiento / b.logo_filename).is_file()
    assert subir(client).status_code == 302
    (almacenamiento / a.logo_filename).unlink()
    response = client.get("/admin/")
    assert response.status_code == 200 and 'src="/static/img/logoDojoManager.png"' in response.text


def test_error_commit_conserva_logo_anterior_y_no_deja_nuevo(app, db, base_data, almacenamiento, monkeypatch):
    client = cliente(app, base_data["admin_a"])
    subir(client)
    anterior = base_data["academia_a"].logo_filename
    def fallar():
        raise RuntimeError("SQL privado")
    monkeypatch.setattr(db.session, "commit", fallar)
    response = subir(client, imagen(color="blue"))
    assert response.status_code == 500 and "SQL privado" not in response.text
    assert base_data["academia_a"].logo_filename == anterior
    assert [p.relative_to(almacenamiento).as_posix() for p in almacenamiento.glob("uploads/academias/*/*.png")] == [anterior]


def test_csrf_obligatorio_y_login_general(app, db, base_data, almacenamiento, monkeypatch):
    client = cliente(app, base_data["admin_a"])
    monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", True)
    assert subir(client).status_code == 400
    assert client.post(URL, data={"accion": "restaurar"}).status_code == 400
    token = re.search(r'name="csrf_token" value="([^"]+)"', client.get(URL).text)[1]
    assert subir(client, csrf_token=token).status_code == 302
    client.get("/auth/logout")
    g.pop("_login_user", None)
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert 'src="/static/img/logoDojoManager.png"' in response.text
    assert "uploads/academias/" not in response.text


def test_imagen_rectangular_conserva_proporcion(app, db, base_data, almacenamiento):
    response = subir(cliente(app, base_data["admin_a"]), imagen(size=(1600, 800)))
    assert response.status_code == 302
    with Image.open(almacenamiento / base_data["academia_a"].logo_filename) as logo:
        assert logo.size == (1024, 512)


def test_colision_nombre_no_elimina_logo_existente(app, db, base_data, almacenamiento, monkeypatch):
    from types import SimpleNamespace
    from app.services import branding
    client = cliente(app, base_data["admin_a"])
    assert subir(client).status_code == 302
    anterior = base_data["academia_a"].logo_filename
    contenido = (almacenamiento / anterior).read_bytes()
    monkeypatch.setattr(branding, "uuid4", lambda: SimpleNamespace(hex=Path(anterior).stem))
    assert subir(client).status_code == 500
    assert base_data["academia_a"].logo_filename == anterior
    assert (almacenamiento / anterior).read_bytes() == contenido


def test_migracion_logo_upgrade_y_downgrade_preservan_academia(tmp_path):
    archivo = Path(__file__).parents[1] / "migrations/versions/e5f9a2b3c4d6_agregar_logo_academia.py"
    spec = importlib.util.spec_from_file_location("migracion_logo", archivo)
    migracion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migracion)
    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE academias (id INTEGER PRIMARY KEY, nombre VARCHAR(150) NOT NULL)"))
            conn.execute(text("INSERT INTO academias VALUES (1, 'Academia test')"))
            with Operations.context(MigrationContext.configure(conn)):
                migracion.upgrade()
                assert conn.execute(text("SELECT logo_filename FROM academias")).scalar() is None
                assert next(c for c in inspect(conn).get_columns("academias") if c["name"] == "logo_filename")["nullable"]
                migracion.downgrade()
            assert "logo_filename" not in [c["name"] for c in inspect(conn).get_columns("academias")]
            assert conn.execute(text("SELECT nombre FROM academias")).scalar() == "Academia test"
    finally:
        engine.dispose()
