from decimal import Decimal

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.extensions import db
from app.models.alumno import Alumno
from app.models.torneo import Torneo
from app.models.medalla import Medalla
from app.models.participacion import Participacion
from app.utils.categorias import obtener_categoria_competencia


participaciones_bp = Blueprint(
    "participaciones",
    __name__,
    url_prefix="/participaciones"
)


@participaciones_bp.route("/nuevo/<int:alumno_id>", methods=["GET", "POST"])
@login_required
def nuevo(alumno_id):
    academia_id = getattr(
        current_user,
        "academia_id",
        None,
    )

    # Un usuario normal siempre debe pertenecer
    # a una academia.
    if (
        academia_id is None
        and not current_user.has_role("SUPERADMIN")
    ):
        abort(403)

    query_alumno = Alumno.query.filter_by(
        id=alumno_id
    )

    if academia_id is not None:
        query_alumno = query_alumno.filter_by(
            academia_id=academia_id
        )

    alumno = query_alumno.first_or_404()

    if current_user.has_role("PROFESOR"):
        if (
            alumno.sucursal_id
            != current_user.sucursal_id
        ):
            abort(403)

    torneos = (
        Torneo.query
        .filter_by(
            academia_id=alumno.academia_id
        )
        .order_by(
            Torneo.fecha.desc()
        )
        .all()
    )

    # Solo mostrar medallas pertenecientes
    # a la academia del alumno.
    medallas = (
        Medalla.query
        .filter_by(
            academia_id=alumno.academia_id
        )
        .order_by(
            Medalla.orden
        )
        .all()
    )

    if request.method == "POST":
        torneo_id = request.form.get(
            "torneo_id"
        )

        modalidad = (
            request.form.get("modalidad")
            or ""
        ).strip().upper()

        medalla_id = request.form.get(
            "medalla_id"
        )

        observacion = (
            request.form.get("observacion")
            or ""
        ).strip() or None

        # ====================================================
        # Validaciones básicas
        # ====================================================

        if not torneo_id or not modalidad:
            flash(
                "Debe seleccionar torneo y modalidad.",
                "danger",
            )
            return redirect(request.url)

        if modalidad not in (
            "POOMSAE",
            "COMBATE",
            "AMBAS",
        ):
            flash(
                "Modalidad inválida.",
                "danger",
            )
            return redirect(request.url)

        try:
            torneo_id_int = int(
                torneo_id
            )
        except (TypeError, ValueError):
            flash(
                "Torneo inválido.",
                "danger",
            )
            return redirect(request.url)

        torneo = Torneo.query.filter_by(
            id=torneo_id_int,
            academia_id=alumno.academia_id,
        ).first_or_404()

        # ============================================================
        # Medalla

        # ============================================================
        # Medalla
        #
        # medalla_id vacío = Participación / sin medalla
        # ============================================================

        medalla_fk = None

        if medalla_id:
            try:
                medalla_fk = int(medalla_id)
            except (TypeError, ValueError):
                flash(
                    "Medalla inválida.",
                    "danger"
                )
                return redirect(request.url)

            medalla = Medalla.query.filter_by(
                id=medalla_fk,
                academia_id=alumno.academia_id
            ).first()

            if not medalla:
                flash(
                    "La medalla seleccionada no pertenece a esta academia.",
                    "danger"
                )
                return redirect(request.url)

        # ============================================================
        # Modalidades que se deben registrar
        # ============================================================

        modalidades_a_registrar = (
            ["POOMSAE", "COMBATE"]
            if modalidad == "AMBAS"
            else [modalidad]
        )

        # ============================================================
        # Calcular valor_evento
        # ============================================================

        if modalidad == "AMBAS":
            total = Decimal(
                str(torneo.precio_ambas or 0)
            )

            valor_por_modalidad = (
                total / Decimal("2")
            ).quantize(Decimal("0.01"))

            valores = {
                "POOMSAE": valor_por_modalidad,
                "COMBATE": valor_por_modalidad,
            }

        elif modalidad == "POOMSAE":
            valores = {
                "POOMSAE": Decimal(
                    str(torneo.precio_poomsae or 0)
                )
            }

        else:
            valores = {
                "COMBATE": Decimal(
                    str(torneo.precio_combate or 0)
                )
            }

        creadas = 0
        actualizadas = 0

        # ============================================================
        # Crear / actualizar participaciones
        # ============================================================

        for mod in modalidades_a_registrar:
            categoria, error_categoria = obtener_categoria_competencia(
                alumno=alumno,
                torneo=torneo,
                modalidad=mod
            )

            if not categoria:
                flash(
                    error_categoria
                    or f"No se encontró categoría válida para {mod}.",
                    "danger"
                )
                return redirect(request.url)

            # Una participación por:
            # alumno + torneo + modalidad
            p = Participacion.query.filter_by(
                academia_id=alumno.academia_id,
                alumno_id=alumno.id,
                torneo_id=torneo.id,
                modalidad=mod
            ).first()

            if p:
                p.categoria_id = categoria.id
                p.medalla_id = medalla_fk
                p.observacion = observacion
                p.valor_evento = valores.get(
                    mod,
                    Decimal("0.00")
                )

                actualizadas += 1

            else:
                p = Participacion(
                    alumno_id=alumno.id,
                    torneo_id=torneo.id,
                    modalidad=mod,
                    categoria_id=categoria.id,
                    medalla_id=medalla_fk,
                    observacion=observacion,
                    valor_evento=valores.get(
                        mod,
                        Decimal("0.00")
                    ),
                    pagado_evento=False,
                    academia_id=alumno.academia_id
                )

                db.session.add(p)
                creadas += 1

        db.session.commit()

        flash(
            (
                "Participación guardada correctamente. "
                f"Nuevas: {creadas} | "
                f"Actualizadas: {actualizadas}"
            ),
            "success"
        )

        return redirect(
            url_for(
                "alumnos.perfil",
                id=alumno.id
            )
        )

    return render_template(
        "participaciones/nuevo.html",
        alumno=alumno,
        torneos=torneos,
        medallas=medallas
    )