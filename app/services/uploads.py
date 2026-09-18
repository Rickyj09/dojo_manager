from werkzeug.utils import secure_filename


def nombre_archivo_seguro(filename, predeterminado="archivo"):
    """Normalización compartida de nombres originales, nunca rutas de destino."""
    filename = (filename or "").replace("\\", "/").split("/")[-1].strip()
    return (secure_filename(filename) or predeterminado)[:255]
