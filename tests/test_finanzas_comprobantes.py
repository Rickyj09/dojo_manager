from datetime import date
from decimal import Decimal
from io import BytesIO
import hashlib
import os

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db as _db
from app.models.finanzas import PagoComprobante, PagoFinanciero
from app.models.role import Role
from app.models.user import User
from app.services.finanzas.comprobantes import (
    guardar_comprobante_pago,
    listar_comprobantes_pago,
    obtener_comprobante,
    resolver_ruta_comprobante,
)
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.pagos import anular_pago, registrar_pago


PNG_BYTES = b"\x89PNG\r\n\x1a\nsmoke"
JPG_BYTES = b"\xff\xd8\xff\xe0smoke"
PDF_BYTES = b"%PDF-1.4\nsmoke\n%%EOF"


def login(client, user):
    response = client.post("/auth/login", data={"username": user.username, "password": "secret"})
    assert response.status_code == 302


@pytest.fixture()
def comprobantes_storage(app, tmp_path):
    root = tmp_path / "comprobantes"
    app.config["PAGO_COMPROBANTE_STORAGE_ROOT"] = str(root)
    app.config["PAGO_COMPROBANTE_MAX_BYTES"] = 1024
    return root


def file_storage(nombre, contenido, mimetype):
    return FileStorage(stream=BytesIO(contenido), filename=nombre, content_type=mimetype)


def crear_pago(base_data, valor="50.00", academia_key="academia_a", alumno_key="alumno_a1"):
    pago = registrar_pago(
        academia_id=base_data[academia_key].id,
        alumno_id=base_data[alumno_key].id,
        fecha_pago=date(2026, 9, 5),
        valor=Decimal(valor),
        medio_pago="EFECTIVO",
    )
    _db.session.commit()
    return pago


def guardar(base_data, pago, archivo, observacion=None):
    comprobante = guardar_comprobante_pago(
        academia_id=pago.academia_id,
        pago_id=pago.id,
        archivo=archivo,
        uploaded_by_id=base_data["admin_a"].id,
        observacion=observacion,
    )
    _db.session.commit()
    return comprobante


def test_guardar_jpg_valido(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("transferencia.jpg", JPG_BYTES, "image/jpeg"))

    assert comprobante.extension == ".jpg"
    assert comprobante.mime_type == "image/jpeg"
    assert resolver_ruta_comprobante(comprobante).exists()


def test_guardar_jpeg_valido(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("transferencia.jpeg", JPG_BYTES + b"2", "image/jpeg"))

    assert comprobante.extension == ".jpeg"
    assert comprobante.mime_type == "image/jpeg"


def test_guardar_png_valido(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("deposito.png", PNG_BYTES, "image/png"))

    assert comprobante.extension == ".png"
    assert comprobante.mime_type == "image/png"


def test_guardar_pdf_valido(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("comprobante.pdf", PDF_BYTES, "application/pdf"))

    assert comprobante.extension == ".pdf"
    assert comprobante.mime_type == "application/pdf"


def test_rechaza_extension_no_permitida(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    with pytest.raises(FinanzasError, match="Formato"):
        guardar_comprobante_pago(
            academia_id=pago.academia_id,
            pago_id=pago.id,
            archivo=file_storage("comprobante.exe", b"MZ", "application/octet-stream"),
            uploaded_by_id=base_data["admin_a"].id,
        )


def test_rechaza_mime_no_permitido(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    with pytest.raises(FinanzasError, match="MIME"):
        guardar_comprobante_pago(
            academia_id=pago.academia_id,
            pago_id=pago.id,
            archivo=file_storage("comprobante.png", PNG_BYTES, "application/pdf"),
            uploaded_by_id=base_data["admin_a"].id,
        )


def test_rechaza_magic_bytes_incompatibles(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    with pytest.raises(FinanzasError, match="contenido"):
        guardar_comprobante_pago(
            academia_id=pago.academia_id,
            pago_id=pago.id,
            archivo=file_storage("comprobante.png", b"not-png", "image/png"),
            uploaded_by_id=base_data["admin_a"].id,
        )


def test_rechaza_archivo_vacio(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    with pytest.raises(FinanzasError, match="vacio"):
        guardar_comprobante_pago(
            academia_id=pago.academia_id,
            pago_id=pago.id,
            archivo=file_storage("comprobante.pdf", b"", "application/pdf"),
            uploaded_by_id=base_data["admin_a"].id,
        )


def test_rechaza_archivo_demasiado_grande(app, db, base_data, comprobantes_storage):
    app.config["PAGO_COMPROBANTE_MAX_BYTES"] = 8
    pago = crear_pago(base_data)

    with pytest.raises(FinanzasError, match="tamano maximo"):
        guardar_comprobante_pago(
            academia_id=pago.academia_id,
            pago_id=pago.id,
            archivo=file_storage("comprobante.png", PNG_BYTES, "image/png"),
            uploaded_by_id=base_data["admin_a"].id,
        )


def test_sha256_correcto(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("comprobante.png", PNG_BYTES, "image/png"))

    assert comprobante.sha256 == hashlib.sha256(PNG_BYTES).hexdigest()


def test_nombre_interno_no_depende_del_original(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("comprobante_banco_julio.pdf", PDF_BYTES, "application/pdf"))

    assert comprobante.nombre_interno != comprobante.nombre_original
    assert comprobante.nombre_interno.endswith(".pdf")
    assert "comprobante_banco_julio" not in comprobante.nombre_interno


def test_path_traversal_en_nombre_original_no_altera_ruta(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("../evil.png", PNG_BYTES, "image/png"))
    ruta = resolver_ruta_comprobante(comprobante)

    assert comprobante.nombre_original == "evil.png"
    assert comprobantes_storage.resolve() in ruta.parents
    assert comprobante.ruta_relativa == f"{pago.academia_id}/{pago.id}/{comprobante.nombre_interno}"


def test_duplicado_mismo_pago_rechazado(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    guardar(base_data, pago, file_storage("uno.png", PNG_BYTES, "image/png"))

    with pytest.raises(FinanzasError, match="ya fue cargado"):
        guardar_comprobante_pago(
            academia_id=pago.academia_id,
            pago_id=pago.id,
            archivo=file_storage("dos.png", PNG_BYTES, "image/png"),
            uploaded_by_id=base_data["admin_a"].id,
        )


def test_mismo_archivo_en_pagos_distintos_permitido(app, db, base_data, comprobantes_storage):
    pago_1 = crear_pago(base_data)
    pago_2 = crear_pago(base_data, valor="60.00")

    comprobante_1 = guardar(base_data, pago_1, file_storage("uno.png", PNG_BYTES, "image/png"))
    comprobante_2 = guardar(base_data, pago_2, file_storage("dos.png", PNG_BYTES, "image/png"))

    assert comprobante_1.sha256 == comprobante_2.sha256
    assert comprobante_1.pago_financiero_id != comprobante_2.pago_financiero_id


def test_archivo_bajo_academia_y_pago_correctos(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("comprobante.png", PNG_BYTES, "image/png"))

    assert comprobante.academia_id == pago.academia_id
    assert comprobante.pago_financiero_id == pago.id
    assert comprobante.ruta_relativa.startswith(f"{pago.academia_id}/{pago.id}/")


def test_pago_anulado_no_acepta_comprobante(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    anular_pago(academia_id=pago.academia_id, pago_id=pago.id)
    _db.session.commit()

    with pytest.raises(FinanzasError, match="pago anulado"):
        guardar_comprobante_pago(
            academia_id=pago.academia_id,
            pago_id=pago.id,
            archivo=file_storage("comprobante.png", PNG_BYTES, "image/png"),
            uploaded_by_id=base_data["admin_a"].id,
        )


def test_tenant_distinto_rechazado(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data, academia_key="academia_b", alumno_key="alumno_b1")

    with pytest.raises(FinanzasError, match="Pago no pertenece"):
        guardar_comprobante_pago(
            academia_id=base_data["academia_a"].id,
            pago_id=pago.id,
            archivo=file_storage("comprobante.png", PNG_BYTES, "image/png"),
            uploaded_by_id=base_data["admin_a"].id,
        )


def test_uploaded_by_correcto(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("comprobante.png", PNG_BYTES, "image/png"))

    assert comprobante.uploaded_by_id == base_data["admin_a"].id
    assert comprobante.uploaded_by.username == "admin_a"


def test_error_al_escribir_archivo_no_crea_metadata(app, db, base_data, comprobantes_storage, monkeypatch):
    pago = crear_pago(base_data)

    def fallar_mkdir(*args, **kwargs):
        raise OSError("sin disco")

    monkeypatch.setattr("pathlib.Path.mkdir", fallar_mkdir)

    with pytest.raises(OSError):
        guardar_comprobante_pago(
            academia_id=pago.academia_id,
            pago_id=pago.id,
            archivo=file_storage("comprobante.png", PNG_BYTES, "image/png"),
            uploaded_by_id=base_data["admin_a"].id,
        )

    assert PagoComprobante.query.filter_by(academia_id=pago.academia_id, pago_financiero_id=pago.id).count() == 0


def test_error_db_limpia_archivo_temporal(app, db, base_data, comprobantes_storage, monkeypatch):
    pago = crear_pago(base_data)
    flush_original = _db.session.flush

    def fallar_flush(*args, **kwargs):
        raise RuntimeError("db rota")

    monkeypatch.setattr(_db.session, "flush", fallar_flush)

    with pytest.raises(RuntimeError):
        guardar_comprobante_pago(
            academia_id=pago.academia_id,
            pago_id=pago.id,
            archivo=file_storage("comprobante.png", PNG_BYTES, "image/png"),
            uploaded_by_id=base_data["admin_a"].id,
        )

    monkeypatch.setattr(_db.session, "flush", flush_original)
    _db.session.rollback()
    assert not list(comprobantes_storage.rglob("*.*"))


def test_archivo_valido_db_valida_existen_ambos(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("comprobante.png", PNG_BYTES, "image/png"))

    assert PagoComprobante.query.filter_by(id=comprobante.id).one()
    assert resolver_ruta_comprobante(comprobante).exists()


def test_ruta_guardada_es_relativa(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)

    comprobante = guardar(base_data, pago, file_storage("comprobante.png", PNG_BYTES, "image/png"))

    assert not os.path.isabs(comprobante.ruta_relativa)


def test_admin_puede_cargar_comprobante(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(
        f"/finanzas/pagos/{pago.id}/comprobantes",
        data={"comprobante": (BytesIO(PNG_BYTES), "comprobante.png"), "observacion_comprobante": "Transferencia"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert PagoComprobante.query.filter_by(academia_id=pago.academia_id, pago_financiero_id=pago.id).count() == 1


def test_superadmin_con_academia_puede_cargar_comprobante(app, db, base_data, comprobantes_storage):
    role = Role(name="SUPERADMIN", description="Super admin")
    user = User(username="super_a", email="super_a@example.com", academia_id=base_data["academia_a"].id, sucursal_id=base_data["admin_a"].sucursal_id)
    user.set_password("secret")
    user.roles.append(role)
    _db.session.add_all([role, user])
    pago = crear_pago(base_data)
    client = app.test_client()
    login(client, user)

    response = client.post(
        f"/finanzas/pagos/{pago.id}/comprobantes",
        data={"comprobante": (BytesIO(PNG_BYTES), "comprobante.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    assert PagoComprobante.query.filter_by(pago_financiero_id=pago.id).count() == 1


def test_profesor_no_puede_cargar_comprobante(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    client = app.test_client()
    login(client, base_data["profesor_a"])

    response = client.post(
        f"/finanzas/pagos/{pago.id}/comprobantes",
        data={"comprobante": (BytesIO(PNG_BYTES), "comprobante.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 403
    assert PagoComprobante.query.filter_by(pago_financiero_id=pago.id).count() == 0


def test_otro_tenant_no_puede_cargar_comprobante(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data, academia_key="academia_b", alumno_key="alumno_b1")
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(
        f"/finanzas/pagos/{pago.id}/comprobantes",
        data={"comprobante": (BytesIO(PNG_BYTES), "comprobante.png")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 404


def test_post_sin_archivo_rechazado(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(f"/finanzas/pagos/{pago.id}/comprobantes", data={}, follow_redirects=True)

    assert response.status_code == 200
    assert b"Debe seleccionar" in response.data
    assert PagoComprobante.query.filter_by(pago_financiero_id=pago.id).count() == 0


def test_archivo_invalido_muestra_error_controlado(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.post(
        f"/finanzas/pagos/{pago.id}/comprobantes",
        data={"comprobante": (BytesIO(b"bad"), "comprobante.png")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"contenido" in response.data


def test_detalle_pago_muestra_comprobante(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    guardar(base_data, pago, file_storage("transferencia.png", PNG_BYTES, "image/png"))
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/pagos/{pago.id}")

    assert response.status_code == 200
    assert b"Comprobantes" in response.data
    assert b"transferencia.png" in response.data


def test_usuario_autorizado_puede_visualizar(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    comprobante = guardar(base_data, pago, file_storage("transferencia.png", PNG_BYTES, "image/png"))
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/comprobantes/{comprobante.id}")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data == PNG_BYTES


def test_otro_tenant_no_puede_visualizar(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data, academia_key="academia_b", alumno_key="alumno_b1")
    comprobante = guardar(
        {"admin_a": base_data["admin_b"]},
        pago,
        file_storage("transferencia.png", PNG_BYTES, "image/png"),
    )
    client = app.test_client()
    login(client, base_data["admin_a"])

    response = client.get(f"/finanzas/comprobantes/{comprobante.id}")

    assert response.status_code == 404


def test_profesor_puede_visualizar_si_tiene_lectura_del_alumno(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    comprobante = guardar(base_data, pago, file_storage("transferencia.png", PNG_BYTES, "image/png"))
    client = app.test_client()
    login(client, base_data["profesor_a"])

    response = client.get(f"/finanzas/comprobantes/{comprobante.id}")

    assert response.status_code == 200
    assert response.data == PNG_BYTES


def test_no_existe_get_para_cargar_o_borrar_comprobante(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    client = app.test_client()
    login(client, base_data["admin_a"])

    cargar = client.get(f"/finanzas/pagos/{pago.id}/comprobantes")
    posible_borrar = client.get("/finanzas/comprobantes/1/eliminar")

    assert cargar.status_code == 405
    assert posible_borrar.status_code == 404


def test_pago_anulado_conserva_comprobantes_y_no_muestra_carga(app, db, base_data, comprobantes_storage):
    pago = crear_pago(base_data)
    comprobante = guardar(base_data, pago, file_storage("transferencia.png", PNG_BYTES, "image/png"))
    anular_pago(academia_id=pago.academia_id, pago_id=pago.id)
    _db.session.commit()
    client = app.test_client()
    login(client, base_data["admin_a"])

    detalle = client.get(f"/finanzas/pagos/{pago.id}")
    ver = client.get(f"/finanzas/comprobantes/{comprobante.id}")

    assert detalle.status_code == 200
    assert b"transferencia.png" in detalle.data
    assert b'name="comprobante"' not in detalle.data
    assert ver.status_code == 200
