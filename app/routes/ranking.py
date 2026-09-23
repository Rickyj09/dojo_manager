from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from sqlalchemy import func, case, and_

from app.extensions import db
from app.models.alumno import Alumno
from app.models.participacion import Participacion
from app.models.medalla import Medalla

ranking_bp = Blueprint("ranking", __name__, url_prefix="/ranking")

def _academia_id_actual():
    academia_id = getattr(
        current_user,
        "academia_id",
        None,
    )

    if academia_id:
        return academia_id

    if current_user.has_role("SUPERADMIN"):
        return None

    abort(403)

@ranking_bp.route("/")
@login_required
def index():
    academia_id = _academia_id_actual()

    query = (
        db.session.query(
            Alumno,
            func.sum(
                case(
                    (Medalla.nombre == "Oro", 1),
                    else_=0,
                )
            ).label("oros"),
            func.sum(
                case(
                    (Medalla.nombre == "Plata", 1),
                    else_=0,
                )
            ).label("platas"),
            func.sum(
                case(
                    (Medalla.nombre == "Bronce", 1),
                    else_=0,
                )
            ).label("bronces"),
            func.count(Medalla.id).label("total"),
        )
        .outerjoin(
            Participacion,
            and_(
                Participacion.alumno_id == Alumno.id,
                Participacion.academia_id
                == Alumno.academia_id,
            ),
        )
        .outerjoin(
            Medalla,
            and_(
                Medalla.id
                == Participacion.medalla_id,
                Medalla.academia_id
                == Alumno.academia_id,
            ),
        )
    )

    if academia_id is not None:
        query = query.filter(
            Alumno.academia_id == academia_id
        )

    if current_user.has_role("PROFESOR"):
        query = query.filter(
            Alumno.sucursal_id
            == current_user.sucursal_id
        )

    ranking = (
        query
        .group_by(Alumno.id)
        .order_by(
            func.sum(
                case(
                    (Medalla.nombre == "Oro", 1),
                    else_=0,
                )
            ).desc(),
            func.sum(
                case(
                    (Medalla.nombre == "Plata", 1),
                    else_=0,
                )
            ).desc(),
            func.sum(
                case(
                    (Medalla.nombre == "Bronce", 1),
                    else_=0,
                )
            ).desc(),
            func.count(Medalla.id).desc(),
        )
        .all()
    )

    return render_template(
        "alumnos/ranking.html",
        ranking=ranking,
    )