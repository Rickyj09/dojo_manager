"""Logos públicos de academia; edición limitada al tenant desde la ruta.

El login permanece general. Un futuro login por academia requerirá resolver el
tenant antes de autenticar (por ejemplo mediante una URL propia).
"""
import re
import warnings
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import update

from app.extensions import db
from app.models.academia import Academia
from app.services.uploads import nombre_archivo_seguro


LOGO_MAX_BYTES = 2 * 1024 * 1024
FORMATOS_LOGO = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}


class BrandingError(ValueError):
    pass


def _ruta_logo(academia_id, relativa):
    if not isinstance(relativa, str) or not re.fullmatch(
        rf"uploads/academias/{int(academia_id)}/[0-9a-f]{{32}}\.png", relativa
    ):
        raise BrandingError("La ruta del logo no es válida.")
    root = Path(current_app.static_folder).resolve()
    destino = root / relativa
    # Impide también enlaces simbólicos que redirijan a otro tenant/directorio.
    if destino.resolve() != destino:
        raise BrandingError("La ruta del logo no es válida.")
    return destino


def obtener_logo_academia(academia):
    """Ruta para url_for('static') o None para usar el logo general."""
    if academia is None or not academia.logo_filename:
        return None
    try:
        ruta = _ruta_logo(academia.id, academia.logo_filename)
        return academia.logo_filename if ruta.is_file() else None
    except (BrandingError, OSError, ValueError):
        return None


def _imagen_validada(archivo):
    if archivo is None or not archivo.filename:
        raise BrandingError("Seleccione una imagen para el logo.")
    extension = Path(nombre_archivo_seguro(archivo.filename)).suffix.lower()
    if extension not in FORMATOS_LOGO:
        raise BrandingError("Use una imagen PNG, JPG/JPEG o WEBP.")
    contenido = archivo.stream.read(LOGO_MAX_BYTES + 1)
    if len(contenido) > LOGO_MAX_BYTES:
        raise BrandingError("El logo no puede superar los 2 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(contenido)) as original:
                if original.format != FORMATOS_LOGO[extension]:
                    raise BrandingError("El contenido no coincide con el formato de la imagen.")
                if original.width * original.height > 4_000_000:
                    raise BrandingError("La imagen es demasiado grande. Use hasta 4 millones de píxeles.")
                original.verify()
            with Image.open(BytesIO(contenido)) as original:
                original.load()
                imagen = ImageOps.exif_transpose(original).convert("RGBA")
                imagen.thumbnail((1024, 1024))
                # Reconstrucción de píxeles: sin metadatos ni contenido añadido.
                limpia = Image.new("RGBA", imagen.size)
                limpia.paste(imagen)
                salida = BytesIO()
                limpia.save(salida, format="PNG")
                return salida.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        if isinstance(exc, BrandingError):
            raise
        raise BrandingError("El archivo no es una imagen válida. Use PNG, JPG/JPEG o WEBP.") from exc


def _eliminar_logo(academia_id, relativa):
    if not relativa:
        return
    try:
        _ruta_logo(academia_id, relativa).unlink(missing_ok=True)
    except (BrandingError, OSError):
        current_app.logger.warning("No se pudo limpiar un archivo de logo de academia")


def actualizar_logo_academia(*, academia_id, archivo=None, restaurar=False):
    contenido = None if restaurar else _imagen_validada(archivo)
    destino = None
    creado = False
    try:
        # Serializa reemplazos/restauraciones del mismo tenant, también en SQLite.
        resultado = db.session.execute(update(Academia).where(Academia.id == academia_id)
            .values(activo=Academia.activo).execution_options(synchronize_session=False))
        if resultado.rowcount != 1:
            raise BrandingError("No se encontró la academia actual.")
        academia = Academia.query.filter_by(id=academia_id).populate_existing().one()
        anterior = academia.logo_filename
        nueva = None
        if not restaurar:
            nueva = f"uploads/academias/{academia_id}/{uuid4().hex}.png"
            destino = _ruta_logo(academia_id, nueva)
            destino.parent.mkdir(parents=True, exist_ok=True)
            # Nombre exclusivo; la referencia solo se publica al confirmar la BD.
            with destino.open("xb") as fichero:
                creado = True
                fichero.write(contenido)
        academia.logo_filename = nueva
        db.session.commit()
    except Exception:
        db.session.rollback()
        if creado:
            _eliminar_logo(academia_id, nueva)
        raise
    # Nunca eliminar el anterior antes de confirmar el reemplazo en la BD.
    _eliminar_logo(academia_id, anterior)
