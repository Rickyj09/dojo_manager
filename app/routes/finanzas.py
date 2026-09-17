from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.alumno import Alumno
from app.models.finanzas import AlumnoPlanFinanciero, FrecuenciaEntrenamiento, PlanFinanciero, TarifaPlan, Tarifario
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.services.finanzas import (
    MEDIOS_PAGO_FINANCIERO,
    anular_pago,
    aplicar_pago_a_obligaciones,
    eliminar_archivo_comprobante,
    guardar_dia_vencimiento_pension,
    guardar_comprobante_pago,
    obtener_detalle_pago,
    listar_comprobantes_pago,
    obtener_cartera_alumnos,
    obtener_comprobante,
    obtener_configuracion_financiera,
    obtener_estado_cuenta_alumno,
    obtener_obligaciones_aplicables_pago,
    obtener_resumen_cartera_academia,
    registrar_pago,
    resolver_ruta_comprobante,
)
from app.services.finanzas.familias import FinanzasError
from app.services.finanzas.asignaciones import asignar_plan_financiero, resolver_tarifa_asignacion
from app.services.finanzas.tarifas import calcular_tarifa
from app.services.finanzas.tarifarios import (
    ESTADOS_TARIFARIO, alternar_tarifa, guardar_tarifa, guardar_tarifario, tarifas_editables,
)


finanzas_bp = Blueprint("finanzas", __name__, url_prefix="/finanzas")

ROLES_LECTURA_FINANZAS = ("SUPERADMIN", "ADMIN", "PROFESOR")
ROLES_ADMINISTRACION_FINANZAS = ("SUPERADMIN", "ADMIN")


def _academia_id_or_403():
    academia_id = getattr(current_user, "academia_id", None)
    if not academia_id:
        abort(403)
    return academia_id


def _puede_ver_finanzas():
    return current_user.is_authenticated and any(
        current_user.has_role(rol) for rol in ROLES_LECTURA_FINANZAS
    )


def _puede_configurar_finanzas():
    return current_user.is_authenticated and any(
        current_user.has_role(rol) for rol in ROLES_ADMINISTRACION_FINANZAS
    )


def _puede_escribir_finanzas():
    return _puede_configurar_finanzas()


def _validar_alumno_visible(academia_id: int, alumno_id: int):
    alumno = Alumno.query.filter_by(id=alumno_id, academia_id=academia_id).first()
    if alumno is None:
        abort(404)
    if current_user.has_role("PROFESOR") and alumno.sucursal_id != current_user.sucursal_id:
        abort(403)
    return alumno


def _parse_fecha_pago(value: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise FinanzasError("La fecha de pago no es valida")


def _aplicaciones_desde_formulario():
    aplicaciones = []
    for key, value in request.form.items():
        if not key.startswith("aplicar_"):
            continue
        value = (value or "").strip()
        if not value:
            continue
        try:
            obligacion_id = int(key.removeprefix("aplicar_"))
        except ValueError:
            raise FinanzasError("Obligacion invalida")
        aplicaciones.append(
            {
                "obligacion_financiera_id": obligacion_id,
                "valor_aplicado": value,
            }
        )
    return aplicaciones


def _texto_obligatorio(nombre: str) -> str:
    valor = (request.form.get(nombre) or "").strip()
    if not valor:
        raise FinanzasError(f"El campo {nombre.replace('_', ' ')} es obligatorio")
    return valor


def _entero_desde_formulario(nombre: str, *, minimo: int | None = None, default: int | None = None) -> int:
    valor = (request.form.get(nombre) or "").strip()
    if not valor and default is not None:
        return default
    try:
        resultado = int(valor)
    except ValueError as exc:
        raise FinanzasError(f"El campo {nombre.replace('_', ' ')} debe ser un numero entero") from exc
    if minimo is not None and resultado < minimo:
        raise FinanzasError(f"El campo {nombre.replace('_', ' ')} debe ser mayor o igual a {minimo}")
    return resultado


def _plan_financiero_de_academia(academia_id: int, plan_id: int) -> PlanFinanciero:
    plan = PlanFinanciero.query.filter_by(id=plan_id, academia_id=academia_id).first()
    if plan is None:
        abort(404)
    return plan


def _frecuencia_de_academia(academia_id: int, frecuencia_id: int) -> FrecuenciaEntrenamiento:
    frecuencia = FrecuenciaEntrenamiento.query.filter_by(id=frecuencia_id, academia_id=academia_id).first()
    if frecuencia is None:
        abort(404)
    return frecuencia


def _guardar_catalogo_financiero(catalogo, campos: dict):
    for nombre, valor in campos.items():
        setattr(catalogo, nombre, valor)
    db.session.add(catalogo)
    try:
        db.session.commit()
    except (IntegrityError, ValueError) as exc:
        db.session.rollback()
        if isinstance(exc, IntegrityError):
            raise FinanzasError("Ya existe un registro con ese codigo en la academia") from exc
        raise FinanzasError(str(exc)) from exc


def _academia_administracion_financiera():
    if not _puede_configurar_finanzas():
        abort(403)
    return _academia_id_or_403()


def _tarifario_de_academia(academia_id, tarifario_id):
    return Tarifario.query.filter_by(id=tarifario_id, academia_id=academia_id).first_or_404()


def _tarifa_de_tarifario(academia_id, tarifario_id, tarifa_id):
    return TarifaPlan.query.filter_by(
        id=tarifa_id, academia_id=academia_id, tarifario_id=tarifario_id,
    ).first_or_404()


@finanzas_bp.route("/asignaciones")
@login_required
def asignaciones():
    if not _puede_ver_finanzas():
        abort(403)
    academia_id = _academia_id_or_403()
    filtro = request.args.get("estado", "todos")
    query = db.session.query(Alumno, AlumnoPlanFinanciero).outerjoin(
        AlumnoPlanFinanciero, and_(
            AlumnoPlanFinanciero.alumno_id == Alumno.id,
            AlumnoPlanFinanciero.academia_id == academia_id,
            AlumnoPlanFinanciero.estado == "ACTIVO",
        ),
    ).filter(Alumno.academia_id == academia_id).options(
        joinedload(AlumnoPlanFinanciero.plan), joinedload(AlumnoPlanFinanciero.frecuencia),
    )
    if current_user.has_role("PROFESOR"):
        query = query.filter(Alumno.sucursal_id == current_user.sucursal_id)
    if filtro == "con":
        query = query.filter(AlumnoPlanFinanciero.id.isnot(None))
    elif filtro == "sin":
        query = query.filter(AlumnoPlanFinanciero.id.is_(None))
    return render_template(
        "finanzas/asignaciones.html", filas=query.order_by(Alumno.apellidos, Alumno.nombres, Alumno.id).all(),
        filtro=filtro, puede_escribir=_puede_escribir_finanzas(),
    )


@finanzas_bp.route("/alumnos/<int:alumno_id>/configuracion", methods=["GET", "POST"])
@login_required
def configuracion_alumno(alumno_id):
    if not _puede_ver_finanzas() or (request.method == "POST" and not _puede_escribir_finanzas()):
        abort(403)
    academia_id = _academia_id_or_403()
    alumno = _validar_alumno_visible(academia_id, alumno_id)
    historial = AlumnoPlanFinanciero.query.filter_by(
        academia_id=academia_id, alumno_id=alumno.id,
    ).order_by(AlumnoPlanFinanciero.fecha_inicio.desc(), AlumnoPlanFinanciero.id.desc()).all()
    actual = next((item for item in historial if item.estado == "ACTIVO"), None)
    datos = request.form if request.method == "POST" else request.args
    form = {
        "plan_id": datos.get("plan_id", str(actual.plan_id) if actual else ""),
        "frecuencia_id": datos.get("frecuencia_id", str(actual.frecuencia_id) if actual else ""),
        "fecha_inicio": datos.get("fecha_inicio", date.today().isoformat()),
        "asignacion_actual_id": datos.get("asignacion_actual_id", str(actual.id) if actual else "0"),
    }
    tarifa = resultado = None
    error = None
    if datos or (form["plan_id"] and form["frecuencia_id"]):
        try:
            try:
                plan_id = int(form["plan_id"])
                frecuencia_id = int(form["frecuencia_id"])
                fecha = date.fromisoformat(form["fecha_inicio"])
            except (ValueError, TypeError):
                raise FinanzasError("Seleccione un plan, una frecuencia y una fecha de inicio válidos.")
            # No se aceptan referencias de precio ni importes enviados por el cliente.
            if any(datos.get(campo) for campo in ("tarifario_id", "tarifa_plan_id")):
                raise FinanzasError("El tarifario y la tarifa se resuelven automáticamente para la fecha indicada.")
            tarifa = resolver_tarifa_asignacion(
                academia_id=academia_id, plan_id=plan_id, frecuencia_id=frecuencia_id, fecha_inicio=fecha,
            )
            resultado = calcular_tarifa(
                academia_id=academia_id, plan_id=plan_id, frecuencia_id=frecuencia_id,
                tarifario_id=tarifa.tarifario_id, contexto_descuentos={"fecha": fecha}, aplicar_descuentos=False,
            )
            if request.method == "POST" and datos.get("accion") != "consultar":
                try:
                    esperada = int(request.form["asignacion_actual_id"])
                except (KeyError, ValueError):
                    raise FinanzasError("Vuelva a abrir el formulario antes de guardar la configuración.")
                asignar_plan_financiero(
                    academia_id=academia_id, alumno_id=alumno.id, plan_id=plan_id,
                    frecuencia_id=frecuencia_id, fecha_inicio=fecha, usuario_id=current_user.id,
                    aplicar_descuentos=False, asignacion_actual_id=esperada,
                )
                db.session.commit()
                flash("Configuración financiera guardada correctamente.", "success")
                return redirect(url_for("finanzas.configuracion_alumno", alumno_id=alumno.id))
        except (FinanzasError, IntegrityError) as exc:
            db.session.rollback()
            error = str(exc).removeprefix("Tarifa/configuracion no disponible. ") if isinstance(exc, FinanzasError) else "No se pudo guardar la configuración. Vuelva a abrir el formulario."
    planes = PlanFinanciero.query.filter_by(academia_id=academia_id, activo=True).order_by(PlanFinanciero.orden, PlanFinanciero.nombre).all()
    frecuencias = FrecuenciaEntrenamiento.query.filter_by(academia_id=academia_id, activo=True).order_by(FrecuenciaEntrenamiento.nombre).all()
    return render_template(
        "finanzas/asignacion_form.html", alumno=alumno, asignacion_financiera=actual, historial=historial,
        form=form, planes=planes, frecuencias=frecuencias, tarifa=tarifa, resultado=resultado, error=error,
        puede_escribir_finanzas=_puede_escribir_finanzas(), ver_finanzas=True,
    )


@finanzas_bp.route("/tarifarios")
@login_required
def tarifarios():
    academia_id = _academia_administracion_financiera()
    items = Tarifario.query.filter_by(academia_id=academia_id).order_by(
        Tarifario.fecha_inicio_vigencia.desc(), Tarifario.id.desc(),
    ).all()
    return render_template("finanzas/tarifarios.html", tarifarios=items)


def _formulario_tarifario(academia_id, tarifario=None):
    campos = ("nombre", "descripcion", "moneda", "fecha_inicio_vigencia", "fecha_fin_vigencia", "estado")
    if request.method == "POST":
        form = {campo: request.form.get(campo, "") for campo in campos}
        try:
            guardado = guardar_tarifario(
                academia_id=academia_id, usuario_id=current_user.id, datos=form, tarifario=tarifario,
            )
            db.session.commit()
        except (FinanzasError, IntegrityError) as exc:
            db.session.rollback()
            flash(str(exc) if isinstance(exc, FinanzasError) else "No se pudo guardar el tarifario. Revise los datos.", "danger")
        else:
            flash("Tarifario guardado correctamente.", "success")
            return redirect(url_for("finanzas.tarifario_tarifas", tarifario_id=guardado.id))
    else:
        form = {campo: getattr(tarifario, campo, None) or "" for campo in campos}
        if tarifario is None:
            form.update(moneda="USD", estado="BORRADOR", fecha_inicio_vigencia=date.today().isoformat())
    return render_template("finanzas/tarifario_form.html", tarifario=tarifario, form=form, estados=ESTADOS_TARIFARIO)


@finanzas_bp.route("/tarifarios/nuevo", methods=["GET", "POST"])
@login_required
def tarifario_nuevo():
    return _formulario_tarifario(_academia_administracion_financiera())


@finanzas_bp.route("/tarifarios/<int:tarifario_id>/editar", methods=["GET", "POST"])
@login_required
def tarifario_editar(tarifario_id):
    academia_id = _academia_administracion_financiera()
    return _formulario_tarifario(academia_id, _tarifario_de_academia(academia_id, tarifario_id))


@finanzas_bp.route("/tarifarios/<int:tarifario_id>/tarifas")
@login_required
def tarifario_tarifas(tarifario_id):
    academia_id = _academia_administracion_financiera()
    tarifario = _tarifario_de_academia(academia_id, tarifario_id)
    tarifas = TarifaPlan.query.filter_by(academia_id=academia_id, tarifario_id=tarifario.id).order_by(TarifaPlan.id).all()
    return render_template(
        "finanzas/tarifas.html", tarifario=tarifario, tarifas=tarifas, editable=tarifas_editables(tarifario),
    )


def _formulario_tarifa(academia_id, tarifario, tarifa=None):
    campos = ("plan_id", "frecuencia_id", "valor_base", "observaciones", "activo")
    if request.method == "POST":
        form = {campo: request.form.get(campo, "") for campo in campos}
        try:
            guardar_tarifa(academia_id=academia_id, tarifario=tarifario, tarifa=tarifa, datos=form)
            db.session.commit()
        except (FinanzasError, IntegrityError) as exc:
            db.session.rollback()
            flash(str(exc) if isinstance(exc, FinanzasError) else "Ya existe una tarifa para ese plan y frecuencia.", "danger")
        else:
            flash("Tarifa guardada correctamente.", "success")
            return redirect(url_for("finanzas.tarifario_tarifas", tarifario_id=tarifario.id))
    else:
        form = {campo: getattr(tarifa, campo, None) if tarifa else "" for campo in campos}
        form["activo"] = "1" if tarifa is None or tarifa.activo else ""
    planes = PlanFinanciero.query.filter_by(academia_id=academia_id, activo=True).order_by(PlanFinanciero.orden, PlanFinanciero.nombre).all()
    frecuencias = FrecuenciaEntrenamiento.query.filter_by(academia_id=academia_id, activo=True).order_by(FrecuenciaEntrenamiento.nombre).all()
    return render_template(
        "finanzas/tarifa_form.html", tarifario=tarifario, tarifa=tarifa, form=form,
        planes=planes, frecuencias=frecuencias, editable=tarifas_editables(tarifario),
    )


@finanzas_bp.route("/tarifarios/<int:tarifario_id>/tarifas/nueva", methods=["GET", "POST"])
@login_required
def tarifario_tarifa_nueva(tarifario_id):
    academia_id = _academia_administracion_financiera()
    return _formulario_tarifa(academia_id, _tarifario_de_academia(academia_id, tarifario_id))


@finanzas_bp.route("/tarifarios/<int:tarifario_id>/tarifas/<int:tarifa_id>/editar", methods=["GET", "POST"])
@login_required
def tarifario_tarifa_editar(tarifario_id, tarifa_id):
    academia_id = _academia_administracion_financiera()
    tarifario = _tarifario_de_academia(academia_id, tarifario_id)
    tarifa = _tarifa_de_tarifario(academia_id, tarifario.id, tarifa_id)
    return _formulario_tarifa(academia_id, tarifario, tarifa)


@finanzas_bp.route("/tarifarios/<int:tarifario_id>/tarifas/<int:tarifa_id>/alternar-activo", methods=["POST"])
@login_required
def tarifario_tarifa_alternar(tarifario_id, tarifa_id):
    academia_id = _academia_administracion_financiera()
    tarifario = _tarifario_de_academia(academia_id, tarifario_id)
    tarifa = _tarifa_de_tarifario(academia_id, tarifario.id, tarifa_id)
    try:
        alternar_tarifa(academia_id=academia_id, tarifario=tarifario, tarifa=tarifa)
        db.session.commit()
    except FinanzasError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    else:
        flash("Tarifa activada." if tarifa.activo else "Tarifa desactivada.", "success")
    return redirect(url_for("finanzas.tarifario_tarifas", tarifario_id=tarifario.id))


@finanzas_bp.route("/planes")
@login_required
def planes():
    if not _puede_configurar_finanzas():
        abort(403)
    academia_id = _academia_id_or_403()
    planes_actuales = PlanFinanciero.query.filter_by(academia_id=academia_id).order_by(
        PlanFinanciero.orden, PlanFinanciero.nombre, PlanFinanciero.id
    ).all()
    return render_template("finanzas/planes.html", planes=planes_actuales)


@finanzas_bp.route("/planes/nuevo", methods=["GET", "POST"])
@login_required
def nuevo_plan():
    if not _puede_configurar_finanzas():
        abort(403)
    academia_id = _academia_id_or_403()
    form = {
        "codigo": request.form.get("codigo") or "",
        "nombre": request.form.get("nombre") or "",
        "descripcion": request.form.get("descripcion") or "",
        "objetivo": request.form.get("objetivo") or "",
        "orden": request.form.get("orden") or "0",
    }
    if request.method == "POST":
        try:
            plan = PlanFinanciero(academia_id=academia_id, activo=True)
            _guardar_catalogo_financiero(plan, {
                "codigo": _texto_obligatorio("codigo"),
                "nombre": _texto_obligatorio("nombre"),
                "descripcion": form["descripcion"].strip() or None,
                "objetivo": form["objetivo"].strip() or None,
                "orden": _entero_desde_formulario("orden", default=0),
            })
        except FinanzasError as exc:
            flash(str(exc), "danger")
        else:
            flash("Plan financiero creado correctamente.", "success")
            return redirect(url_for("finanzas.planes"))
    return render_template("finanzas/plan_form.html", plan=None, form=form)


@finanzas_bp.route("/planes/<int:plan_id>/editar", methods=["GET", "POST"])
@login_required
def editar_plan(plan_id):
    if not _puede_configurar_finanzas():
        abort(403)
    academia_id = _academia_id_or_403()
    plan = _plan_financiero_de_academia(academia_id, plan_id)
    form = {
        "codigo": request.form.get("codigo", plan.codigo),
        "nombre": request.form.get("nombre", plan.nombre),
        "descripcion": request.form.get("descripcion", plan.descripcion or ""),
        "objetivo": request.form.get("objetivo", plan.objetivo or ""),
        "orden": request.form.get("orden", str(plan.orden)),
    }
    if request.method == "POST":
        try:
            _guardar_catalogo_financiero(plan, {
                "codigo": _texto_obligatorio("codigo"),
                "nombre": _texto_obligatorio("nombre"),
                "descripcion": form["descripcion"].strip() or None,
                "objetivo": form["objetivo"].strip() or None,
                "orden": _entero_desde_formulario("orden", default=0),
            })
        except FinanzasError as exc:
            flash(str(exc), "danger")
        else:
            flash("Plan financiero actualizado correctamente.", "success")
            return redirect(url_for("finanzas.planes"))
    return render_template("finanzas/plan_form.html", plan=plan, form=form)


@finanzas_bp.route("/planes/<int:plan_id>/alternar-activo", methods=["POST"])
@login_required
def alternar_plan_activo(plan_id):
    if not _puede_configurar_finanzas():
        abort(403)
    plan = _plan_financiero_de_academia(_academia_id_or_403(), plan_id)
    plan.activo = not plan.activo
    db.session.commit()
    flash("Plan financiero activado." if plan.activo else "Plan financiero desactivado.", "success")
    return redirect(url_for("finanzas.planes"))


@finanzas_bp.route("/frecuencias")
@login_required
def frecuencias():
    if not _puede_configurar_finanzas():
        abort(403)
    academia_id = _academia_id_or_403()
    frecuencias_actuales = FrecuenciaEntrenamiento.query.filter_by(academia_id=academia_id).order_by(
        FrecuenciaEntrenamiento.nombre, FrecuenciaEntrenamiento.id
    ).all()
    return render_template("finanzas/frecuencias.html", frecuencias=frecuencias_actuales)


@finanzas_bp.route("/frecuencias/nueva", methods=["GET", "POST"])
@login_required
def nueva_frecuencia():
    if not _puede_configurar_finanzas():
        abort(403)
    academia_id = _academia_id_or_403()
    form = {
        "codigo": request.form.get("codigo") or "",
        "nombre": request.form.get("nombre") or "",
        "dias_semana": request.form.get("dias_semana") or "",
        "descripcion": request.form.get("descripcion") or "",
    }
    if request.method == "POST":
        try:
            frecuencia = FrecuenciaEntrenamiento(academia_id=academia_id, activo=True)
            _guardar_catalogo_financiero(frecuencia, {
                "codigo": _texto_obligatorio("codigo"),
                "nombre": _texto_obligatorio("nombre"),
                "dias_semana": _entero_desde_formulario("dias_semana", minimo=0),
                "descripcion": form["descripcion"].strip() or None,
            })
        except FinanzasError as exc:
            flash(str(exc), "danger")
        else:
            flash("Frecuencia creada correctamente.", "success")
            return redirect(url_for("finanzas.frecuencias"))
    return render_template("finanzas/frecuencia_form.html", frecuencia=None, form=form)


@finanzas_bp.route("/frecuencias/<int:frecuencia_id>/editar", methods=["GET", "POST"])
@login_required
def editar_frecuencia(frecuencia_id):
    if not _puede_configurar_finanzas():
        abort(403)
    academia_id = _academia_id_or_403()
    frecuencia = _frecuencia_de_academia(academia_id, frecuencia_id)
    form = {
        "codigo": request.form.get("codigo", frecuencia.codigo),
        "nombre": request.form.get("nombre", frecuencia.nombre),
        "dias_semana": request.form.get("dias_semana", str(frecuencia.dias_semana)),
        "descripcion": request.form.get("descripcion", frecuencia.descripcion or ""),
    }
    if request.method == "POST":
        try:
            _guardar_catalogo_financiero(frecuencia, {
                "codigo": _texto_obligatorio("codigo"),
                "nombre": _texto_obligatorio("nombre"),
                "dias_semana": _entero_desde_formulario("dias_semana", minimo=0),
                "descripcion": form["descripcion"].strip() or None,
            })
        except FinanzasError as exc:
            flash(str(exc), "danger")
        else:
            flash("Frecuencia actualizada correctamente.", "success")
            return redirect(url_for("finanzas.frecuencias"))
    return render_template("finanzas/frecuencia_form.html", frecuencia=frecuencia, form=form)


@finanzas_bp.route("/frecuencias/<int:frecuencia_id>/alternar-activo", methods=["POST"])
@login_required
def alternar_frecuencia_activa(frecuencia_id):
    if not _puede_configurar_finanzas():
        abort(403)
    frecuencia = _frecuencia_de_academia(_academia_id_or_403(), frecuencia_id)
    frecuencia.activo = not frecuencia.activo
    db.session.commit()
    flash("Frecuencia activada." if frecuencia.activo else "Frecuencia desactivada.", "success")
    return redirect(url_for("finanzas.frecuencias"))


@finanzas_bp.route("/cartera")
@login_required
def cartera():
    if not _puede_ver_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    q = (request.args.get("q") or "").strip()
    filtro = (request.args.get("saldo") or "todos").strip()
    periodo = (request.args.get("periodo") or "").strip() or None
    con_saldo = filtro == "con_saldo"
    vencidos = filtro == "vencidos"
    alumno_ids = None

    if current_user.has_role("PROFESOR"):
        alumnos_visibles = Alumno.query.filter_by(
            academia_id=academia_id,
            sucursal_id=current_user.sucursal_id,
        ).with_entities(Alumno.id).all()
        alumno_ids = {row[0] for row in alumnos_visibles}

    resumen = obtener_resumen_cartera_academia(
        academia_id=academia_id,
        periodo=periodo,
        alumno_ids=alumno_ids,
    )
    alumnos = obtener_cartera_alumnos(
        academia_id=academia_id,
        q=q,
        con_saldo=con_saldo,
        vencidos=vencidos,
        periodo=periodo,
        alumno_ids=alumno_ids,
    )

    return render_template(
        "finanzas/cartera.html",
        resumen=resumen,
        alumnos=alumnos,
        q=q,
        filtro=filtro,
        periodo=periodo or "",
        puede_escribir=_puede_escribir_finanzas(),
    )


@finanzas_bp.route("/alumnos/<int:alumno_id>/estado-cuenta")
@login_required
def estado_cuenta_alumno(alumno_id):
    if not _puede_ver_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    _validar_alumno_visible(academia_id, alumno_id)

    try:
        estado_cuenta = obtener_estado_cuenta_alumno(academia_id=academia_id, alumno_id=alumno_id)
    except FinanzasError:
        abort(404)

    return render_template(
        "finanzas/estado_cuenta_alumno.html",
        estado_cuenta=estado_cuenta,
        puede_escribir=_puede_escribir_finanzas(),
    )


@finanzas_bp.route("/alumnos/<int:alumno_id>/pagos/nuevo", methods=["GET", "POST"])
@login_required
def nuevo_pago_alumno(alumno_id):
    if not _puede_escribir_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    alumno = _validar_alumno_visible(academia_id, alumno_id)
    form = {
        "fecha_pago": request.form.get("fecha_pago") or date.today().isoformat(),
        "valor": request.form.get("valor") or "",
        "moneda": request.form.get("moneda") or "USD",
        "medio_pago": request.form.get("medio_pago") or "EFECTIVO",
        "referencia": request.form.get("referencia") or "",
        "observacion": request.form.get("observacion") or "",
    }

    if request.method == "POST":
        try:
            pago = registrar_pago(
                academia_id=academia_id,
                alumno_id=alumno.id,
                fecha_pago=_parse_fecha_pago(form["fecha_pago"]),
                valor=form["valor"],
                moneda=form["moneda"],
                medio_pago=form["medio_pago"],
                referencia=form["referencia"].strip() or None,
                observacion=form["observacion"].strip() or None,
            )
            db.session.commit()
        except FinanzasError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        else:
            flash("Pago registrado correctamente.", "success")
            return redirect(url_for("finanzas.detalle_pago", pago_id=pago.id))

    return render_template(
        "finanzas/pago_form.html",
        alumno=alumno,
        medios_pago=MEDIOS_PAGO_FINANCIERO,
        form=form,
    )


@finanzas_bp.route("/pagos/<int:pago_id>")
@login_required
def detalle_pago(pago_id):
    if not _puede_ver_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    try:
        detalle = obtener_detalle_pago(academia_id=academia_id, pago_id=pago_id)
    except FinanzasError:
        abort(404)
    _validar_alumno_visible(academia_id, detalle.pago.alumno_id)
    obligaciones_aplicables = obtener_obligaciones_aplicables_pago(academia_id=academia_id, pago_id=pago_id)
    comprobantes = listar_comprobantes_pago(academia_id=academia_id, pago_id=pago_id)

    return render_template(
        "finanzas/pago_detalle.html",
        detalle=detalle,
        obligaciones_aplicables=obligaciones_aplicables,
        comprobantes=comprobantes,
        puede_escribir=_puede_escribir_finanzas(),
    )


@finanzas_bp.route("/pagos/<int:pago_id>/aplicar", methods=["POST"])
@login_required
def aplicar_pago_financiero(pago_id):
    if not _puede_escribir_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    try:
        detalle = obtener_detalle_pago(academia_id=academia_id, pago_id=pago_id)
        _validar_alumno_visible(academia_id, detalle.pago.alumno_id)
        aplicaciones = _aplicaciones_desde_formulario()
        creadas = aplicar_pago_a_obligaciones(
            academia_id=academia_id,
            pago_id=pago_id,
            aplicaciones=aplicaciones,
        )
        db.session.commit()
    except FinanzasError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    else:
        flash(f"Se aplicaron {len(creadas)} valores del pago.", "success")
    return redirect(url_for("finanzas.detalle_pago", pago_id=pago_id))


@finanzas_bp.route("/pagos/<int:pago_id>/comprobantes", methods=["POST"])
@login_required
def cargar_comprobante_pago(pago_id):
    if not _puede_escribir_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    comprobante = None
    try:
        detalle = obtener_detalle_pago(academia_id=academia_id, pago_id=pago_id)
        _validar_alumno_visible(academia_id, detalle.pago.alumno_id)
        comprobante = guardar_comprobante_pago(
            academia_id=academia_id,
            pago_id=pago_id,
            archivo=request.files.get("comprobante"),
            uploaded_by_id=current_user.id,
            observacion=request.form.get("observacion_comprobante"),
        )
        db.session.commit()
    except FinanzasError as exc:
        db.session.rollback()
        if comprobante is not None:
            eliminar_archivo_comprobante(comprobante)
        flash(str(exc), "danger")
    except HTTPException:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        if comprobante is not None:
            eliminar_archivo_comprobante(comprobante)
        flash("No se pudo guardar el comprobante.", "danger")
    else:
        flash("Comprobante cargado correctamente.", "success")
    return redirect(url_for("finanzas.detalle_pago", pago_id=pago_id))


@finanzas_bp.route("/comprobantes/<int:comprobante_id>")
@login_required
def ver_comprobante(comprobante_id):
    if not _puede_ver_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    try:
        comprobante = obtener_comprobante(academia_id=academia_id, comprobante_id=comprobante_id)
        detalle = obtener_detalle_pago(academia_id=academia_id, pago_id=comprobante.pago_financiero_id)
        _validar_alumno_visible(academia_id, detalle.pago.alumno_id)
        ruta = resolver_ruta_comprobante(comprobante)
    except FinanzasError:
        abort(404)
    if not ruta.exists():
        abort(404)
    return send_file(
        ruta,
        mimetype=comprobante.mime_type,
        as_attachment=False,
        download_name=comprobante.nombre_original,
    )


@finanzas_bp.route("/pagos/<int:pago_id>/anular", methods=["POST"])
@login_required
def anular_pago_financiero(pago_id):
    if not _puede_escribir_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    try:
        detalle = obtener_detalle_pago(academia_id=academia_id, pago_id=pago_id)
        _validar_alumno_visible(academia_id, detalle.pago.alumno_id)
        anular_pago(academia_id=academia_id, pago_id=pago_id)
        db.session.commit()
    except FinanzasError as exc:
        db.session.rollback()
        if "pago con aplicaciones" in str(exc):
            flash("No se puede anular este pago porque tiene valores aplicados. Primero debe existir un procedimiento de reverso.", "danger")
        else:
            flash(str(exc), "danger")
    else:
        flash("Pago anulado correctamente.", "success")
    return redirect(url_for("finanzas.detalle_pago", pago_id=pago_id))


@finanzas_bp.route("/configuracion", methods=["GET", "POST"])
@login_required
def configuracion():
    if not _puede_configurar_finanzas():
        abort(403)

    academia_id = _academia_id_or_403()
    configuracion_actual = obtener_configuracion_financiera(academia_id=academia_id)

    if request.method == "POST":
        valor = (request.form.get("dia_vencimiento_pension") or "").strip()
        dia = None
        if valor:
            try:
                dia = int(valor)
            except ValueError:
                flash("El dia de vencimiento debe ser un numero entre 1 y 31.", "danger")
                return render_template("finanzas/configuracion.html", configuracion=configuracion_actual)

        try:
            configuracion_actual = guardar_dia_vencimiento_pension(
                academia_id=academia_id,
                dia_vencimiento_pension=dia,
            )
            db.session.commit()
        except FinanzasError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        else:
            flash("Configuracion financiera actualizada.", "success")
            return redirect(url_for("finanzas.configuracion"))

    return render_template("finanzas/configuracion.html", configuracion=configuracion_actual)
