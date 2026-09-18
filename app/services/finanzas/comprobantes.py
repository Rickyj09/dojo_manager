import hashlib
import os
from pathlib import Path
from uuid import uuid4

from flask import current_app
from werkzeug.datastructures import FileStorage
from app.services.uploads import nombre_archivo_seguro

from app.extensions import db
from app.models.finanzas import PagoComprobante, PagoFinanciero
from app.models.user import User
from app.services.finanzas.familias import FinanzasError


FORMATOS_COMPROBANTE = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
}
PAGO_COMPROBANTE_MAX_BYTES_DEFAULT = 5 * 1024 * 1024


def _storage_root() -> Path:
    root = current_app.config.get("PAGO_COMPROBANTE_STORAGE_ROOT")
    if not root:
        root = Path(current_app.instance_path) / "pagos_comprobantes"
    return Path(root).resolve()


def _max_bytes() -> int:
    return int(current_app.config.get("PAGO_COMPROBANTE_MAX_BYTES", PAGO_COMPROBANTE_MAX_BYTES_DEFAULT))


def _nombre_original_seguro(filename: str | None) -> str:
    return nombre_archivo_seguro(filename, predeterminado="comprobante")


def _extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def _validar_archivo(archivo: FileStorage) -> tuple[str, str, bytes, str]:
    if archivo is None or not archivo.filename:
        raise FinanzasError("Debe seleccionar un archivo de comprobante")

    nombre_original = _nombre_original_seguro(archivo.filename)
    extension = _extension(nombre_original)
    if extension not in FORMATOS_COMPROBANTE:
        raise FinanzasError("Formato de comprobante no permitido")

    mime_esperado, magic = FORMATOS_COMPROBANTE[extension]
    mime_declarado = (archivo.mimetype or "").strip().lower()
    if mime_declarado != mime_esperado:
        raise FinanzasError("Tipo MIME de comprobante no permitido")

    contenido = archivo.stream.read()
    try:
        archivo.stream.seek(0)
    except (AttributeError, OSError):
        pass

    if not contenido:
        raise FinanzasError("El comprobante no puede estar vacio")
    if len(contenido) > _max_bytes():
        raise FinanzasError("El comprobante excede el tamano maximo permitido")
    if not contenido.startswith(magic):
        raise FinanzasError("El contenido del comprobante no coincide con su tipo")

    sha256 = hashlib.sha256(contenido).hexdigest()
    return nombre_original, extension, contenido, sha256


def _ruta_relativa(academia_id: int, pago_id: int, nombre_interno: str) -> str:
    return os.path.join(str(academia_id), str(pago_id), nombre_interno).replace("\\", "/")


def resolver_ruta_comprobante(comprobante: PagoComprobante) -> Path:
    root = _storage_root()
    ruta = (root / comprobante.ruta_relativa).resolve()
    if root != ruta and root not in ruta.parents:
        raise FinanzasError("Ruta de comprobante invalida")
    return ruta


def obtener_comprobante(*, academia_id: int, comprobante_id: int) -> PagoComprobante:
    comprobante = PagoComprobante.query.filter_by(id=comprobante_id, academia_id=academia_id).first()
    if comprobante is None:
        raise FinanzasError("Comprobante no pertenece a la academia indicada")
    return comprobante


def listar_comprobantes_pago(*, academia_id: int, pago_id: int) -> list[PagoComprobante]:
    pago = PagoFinanciero.query.filter_by(id=pago_id, academia_id=academia_id).first()
    if pago is None:
        raise FinanzasError("Pago no pertenece a la academia indicada")
    return (
        PagoComprobante.query
        .filter_by(academia_id=academia_id, pago_financiero_id=pago.id)
        .order_by(PagoComprobante.created_at.desc(), PagoComprobante.id.desc())
        .all()
    )


def eliminar_archivo_comprobante(comprobante: PagoComprobante) -> None:
    try:
        resolver_ruta_comprobante(comprobante).unlink(missing_ok=True)
    except OSError:
        pass


def guardar_comprobante_pago(
    *,
    academia_id: int,
    pago_id: int,
    archivo: FileStorage,
    uploaded_by_id: int,
    observacion: str | None = None,
) -> PagoComprobante:
    pago = PagoFinanciero.query.filter_by(id=pago_id, academia_id=academia_id).first()
    if pago is None:
        raise FinanzasError("Pago no pertenece a la academia indicada")
    if pago.estado == "ANULADO":
        raise FinanzasError("No se puede cargar comprobantes en un pago anulado")

    usuario = User.query.filter_by(id=uploaded_by_id).first()
    if usuario is None:
        raise FinanzasError("Usuario de carga invalido")
    if usuario.academia_id != academia_id and not usuario.has_role("SUPERADMIN"):
        raise FinanzasError("Usuario de carga no pertenece a la academia indicada")

    nombre_original, extension, contenido, sha256 = _validar_archivo(archivo)
    existente = PagoComprobante.query.filter_by(
        academia_id=academia_id,
        pago_financiero_id=pago.id,
        sha256=sha256,
    ).first()
    if existente is not None:
        raise FinanzasError("El comprobante ya fue cargado para este pago")

    nombre_interno = f"{uuid4().hex}{extension}"
    ruta_relativa = _ruta_relativa(academia_id, pago.id, nombre_interno)
    mime_type = FORMATOS_COMPROBANTE[extension][0]
    root = _storage_root()
    destino = (root / ruta_relativa).resolve()
    if root != destino and root not in destino.parents:
        raise FinanzasError("Ruta de comprobante invalida")
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(f".{destino.name}.tmp")

    try:
        with open(temporal, "wb") as fh:
            fh.write(contenido)

        comprobante = PagoComprobante(
            academia_id=academia_id,
            pago_financiero_id=pago.id,
            nombre_original=nombre_original,
            nombre_interno=nombre_interno,
            ruta_relativa=ruta_relativa,
            mime_type=mime_type,
            extension=extension,
            tamano_bytes=len(contenido),
            sha256=sha256,
            uploaded_by_id=uploaded_by_id,
            observacion=(observacion or "").strip() or None,
        )
        db.session.add(comprobante)
        db.session.flush()
        os.replace(temporal, destino)
        return comprobante
    except Exception:
        try:
            temporal.unlink(missing_ok=True)
            destino.unlink(missing_ok=True)
        except OSError:
            pass
        raise
