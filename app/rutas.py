from __future__ import annotations

import secrets
from datetime import date
from functools import wraps

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import dominio as d
from app import google_auth
from app.almacen import USUARIO_DEMO, Almacen
from app.asesor import AsesorNoDisponible, ModeloFalso, ModeloIA
from app.formularios import (
    FotoForm,
    GastoGrupoForm,
    GrupoForm,
    InvitarForm,
    MovimientoForm,
    PagoForm,
    PreguntaForm,
    RegistroForm,
)

bp = Blueprint("kuadra", __name__)

MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
         "Noviembre", "Diciembre")
COLORES = ("#1E1B4B", "#4F46C8", "#8B8FF0", "#B7B9F6", "#D9DBFB", "#6B66D9", "#3A348F", "#A3A6F3", "#C9CBF9", "#E8E9FD")


def almacen() -> Almacen:
    return current_app.extensions["almacen"]


def modelo_ia() -> ModeloIA:
    return current_app.extensions["modelo_ia"]


def login_requerido(vista):
    """Exige sesión y, la primera vez, que la persona registre su nombre."""
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("kuadra.bienvenida"))
        if not almacen().perfil(session["usuario"]):
            return redirect(url_for("kuadra.registro"))
        return vista(*args, **kwargs)

    return envoltura


def nombre(correo: str) -> str:
    """Nombre para mostrar: 'Tú', el nombre registrado o la parte inicial del correo (invitados sin cuenta)."""
    if correo == session.get("usuario"):
        return "Tú"
    cache = g.setdefault("nombres", {})
    if correo not in cache:
        cache[correo] = almacen().perfil(correo) or correo.split("@")[0].capitalize()
    return cache[correo]


def grupo_del_usuario(grupo_id: str) -> d.Grupo:
    """El grupo, solo si el usuario es miembro; si no, 404 (no se revela si existe)."""
    grupo = almacen().grupo(grupo_id)
    if not grupo or session["usuario"] not in almacen().miembros(grupo_id):
        abort(404)
    return grupo


def saldo_compartido_total(usuario: str) -> int:
    total = 0
    for grupo in almacen().grupos(usuario):
        total += d.saldos(almacen().gastos_grupo(grupo.id), almacen().pagos_grupo(grupo.id)).get(usuario, 0)
    return total


@bp.app_context_processor
def usuario_actual():
    """Nombre y foto del usuario para el saludo y la barra lateral."""
    correo = session.get("usuario")
    nombre_completo = almacen().perfil(correo) if correo else None
    if not nombre_completo:
        return {}
    tiene_foto = almacen().foto(correo) is not None
    return {"yo": {
        "nombre": nombre_completo,
        "primer_nombre": d.primer_nombre(nombre_completo),
        "inicial": nombre_completo[:1].upper(),
        "foto": url_for("kuadra.mi_foto") if tiene_foto else session.get("foto_google", ""),
    }}


def google_configurado() -> bool:
    return bool(current_app.config["GOOGLE_CLIENT_ID"] and current_app.config["GOOGLE_CLIENT_SECRET"])


def redirect_uri_google() -> str:
    base = current_app.config["URL_PUBLICA"]
    ruta = url_for("kuadra.google_callback")
    return base.rstrip("/") + ruta if base else url_for("kuadra.google_callback", _external=True)


def dias_restantes(hoy: date) -> int:
    siguiente = date(hoy.year + (hoy.month == 12), hoy.month % 12 + 1, 1)
    return (siguiente - hoy).days


def segmentos_dona(por_categoria: dict[str, int]) -> list[dict]:
    """Segmentos para una dona SVG (circunferencia normalizada a 100)."""
    total = sum(por_categoria.values()) or 1
    segmentos, acumulado = [], 0.0
    for i, (categoria, valor) in enumerate(por_categoria.items()):
        pct = valor * 100 / total
        segmentos.append({
            "categoria": categoria,
            "valor": valor,
            "pct": round(pct),
            "color": COLORES[i % len(COLORES)],
            "dash": f"{pct:.2f} {100 - pct:.2f}",
            "offset": f"{25 - acumulado:.2f}",
        })
        acumulado += pct
    return segmentos


# ---------- Sesión ----------

@bp.get("/health")
def health():
    return {"estado": "ok", "ambiente": current_app.config["AMBIENTE"], "version": current_app.config["VERSION"]}


@bp.get("/bienvenida")
def bienvenida():
    return render_template(
        "bienvenida.html", modo_demo=current_app.config["MODO_DEMO"], google=google_configurado()
    )


@bp.get("/login/google")
def login_google():
    if not google_configurado():
        flash("El inicio de sesión con Google no está configurado.", "error")
        return redirect(url_for("kuadra.bienvenida"))
    verificador, desafio = google_auth.nuevo_pkce()
    estado = secrets.token_urlsafe(32)
    session.clear()
    session["oauth_estado"], session["oauth_verificador"] = estado, verificador
    return redirect(google_auth.url_autorizacion(
        current_app.config["GOOGLE_CLIENT_ID"], redirect_uri_google(), estado, desafio
    ))


@bp.get("/auth/google/callback")
def google_callback():
    estado = session.pop("oauth_estado", None)
    verificador = session.pop("oauth_verificador", None)
    if not estado or not secrets.compare_digest(estado, request.args.get("state", "")) or not verificador:
        flash("La sesión expiró. Intenta de nuevo.", "error")
        return redirect(url_for("kuadra.bienvenida"))
    if "code" not in request.args:
        flash("Cancelaste el inicio de sesión.", "error")
        return redirect(url_for("kuadra.bienvenida"))
    try:
        usuario = google_auth.usuario_desde_codigo(
            current_app.config["GOOGLE_CLIENT_ID"], current_app.config["GOOGLE_CLIENT_SECRET"],
            request.args["code"], redirect_uri_google(), verificador,
        )
    except google_auth.ErrorLogin as err:
        current_app.logger.warning("Login con Google falló: %s", err.__cause__ or err)
        flash(str(err), "error")
        return redirect(url_for("kuadra.bienvenida"))
    session.clear()
    session["usuario"] = usuario["correo"]
    session["nombre_google"] = usuario["nombre"][:40]
    session["foto_google"] = usuario.get("foto", "")
    return redirect(url_for("kuadra.inicio"))


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    if "usuario" not in session:
        return redirect(url_for("kuadra.bienvenida"))
    if almacen().perfil(session["usuario"]):
        return redirect(url_for("kuadra.inicio"))
    form = RegistroForm()
    if not form.is_submitted():
        form.nombre.data = session.get("nombre_google", "")
    if form.validate_on_submit():
        try:
            nombre_valido = d.validar_nombre(form.nombre.data)
        except d.DatoInvalido as err:
            flash(str(err), "error")
        else:
            almacen().guardar_perfil(session["usuario"], nombre_valido)
            grupos = almacen().grupos(session["usuario"])
            if grupos:
                flash(f"¡Bienvenida/o, {nombre_valido}! Ya estás en: {', '.join(x.nombre for x in grupos)} 🎉", "ok")
            return redirect(url_for("kuadra.inicio"))
    return render_template("registro.html", form=form, correo=session["usuario"])


@bp.post("/demo")
def entrar_demo():
    if not current_app.config["MODO_DEMO"]:
        abort(404)
    session.clear()
    session["usuario"] = USUARIO_DEMO
    return redirect(url_for("kuadra.inicio"))


@bp.post("/salir")
def salir():
    session.clear()
    return redirect(url_for("kuadra.bienvenida"))


# ---------- Personal ----------

@bp.get("/")
@login_requerido
def inicio():
    u = session["usuario"]
    hoy = date.today()
    movs = almacen().movimientos(u)
    mes = d.del_mes(movs, hoy.year, hoy.month)
    ingresos, gastos = d.total(mes, "ingreso"), d.total(mes, "gasto")
    semana = d.gastos_por_dia(movs, hoy)
    maximo = max((v for _, v in semana), default=0) or 1
    alertas = d.alertas_topes(d.gastos_por_categoria(mes), almacen().topes(u))
    return render_template(
        "inicio.html",
        mes=MESES[hoy.month - 1],
        dias_restantes=dias_restantes(hoy),
        semana=[{"dia": dia, "valor": v, "alto": max(8, round(v * 100 / maximo))} for dia, v in semana],
        total_semana=sum(v for _, v in semana),
        ingresos=ingresos,
        gastos=gastos,
        balance=ingresos - gastos,
        recientes=movs[:6],
        saldo_compartido=saldo_compartido_total(u),
        alertas=alertas,
    )


@bp.route("/movimientos/nuevo", methods=["GET", "POST"])
@login_requerido
def nuevo_movimiento():
    form = MovimientoForm()
    if not form.is_submitted():
        form.fecha.data = date.today()
    if form.validate_on_submit():
        try:
            mov = d.validar_movimiento(d.Movimiento(
                fecha=form.fecha.data,
                monto=form.monto.data,
                descripcion=form.descripcion.data.strip(),
                categoria=form.categoria.data if form.tipo.data == "gasto" else "Otros",
                medio=form.medio.data,
                tipo=form.tipo.data,
            ))
        except d.DatoInvalido as err:
            flash(str(err), "error")
        else:
            almacen().agregar_movimiento(session["usuario"], mov)
            flash("Movimiento guardado ✅", "ok")
            return redirect(url_for("kuadra.inicio"))
    return render_template("movimiento_nuevo.html", form=form)


@bp.get("/analisis")
@login_requerido
def analisis():
    u = session["usuario"]
    hoy = date.today()
    movs = almacen().movimientos(u)
    mes = d.del_mes(movs, hoy.year, hoy.month)
    por_categoria = d.gastos_por_categoria(mes)
    tendencia = d.tendencia_mensual(movs, hoy)
    maximo = max((v for _, v in tendencia), default=0) or 1
    topes = almacen().topes(u)
    gastado_con_tope = sum(por_categoria.get(c, 0) for c in topes)
    tope_total = sum(topes.values())
    return render_template(
        "analisis.html",
        total_gastos=sum(por_categoria.values()),
        segmentos=segmentos_dona(por_categoria),
        barras=[{"mes": m, "valor": v, "alto": round(v * 100 / maximo)} for m, v in tendencia],
        alertas=d.alertas_topes(por_categoria, topes),
        diferencia_pct=round((tope_total - gastado_con_tope) * 100 / tope_total) if tope_total else None,
        deudas=d.orden_pago_deudas(almacen().deudas(u)),
    )


# ---------- Compartido ----------

@bp.get("/compartido")
@login_requerido
def compartido():
    u = session["usuario"]
    grupos = []
    for grupo in almacen().grupos(u):
        netos = d.saldos(almacen().gastos_grupo(grupo.id), almacen().pagos_grupo(grupo.id))
        grupos.append({
            "id": grupo.id,
            "nombre": grupo.nombre,
            "miembros": [nombre(m) for m in almacen().miembros(grupo.id)],
            "mi_saldo": netos.get(u, 0),
            "transferencias": [
                {"de": a, "para": b, "monto": m, "texto": f"{nombre(a)} → {nombre(b)}"}
                for a, b, m in d.simplificar(netos)
            ],
            "opciones": [(m, nombre(m)) for m in almacen().miembros(grupo.id)],
            "gastos": almacen().gastos_grupo(grupo.id)[:5],
            "pagos": sorted(almacen().pagos_grupo(grupo.id), key=lambda p: p.fecha, reverse=True)[:5],
        })
    return render_template("compartido.html", grupos=grupos, nombre=nombre, usuario=u)


@bp.route("/compartido/nuevo", methods=["GET", "POST"])
@login_requerido
def nuevo_grupo():
    u = session["usuario"]
    form = GrupoForm()
    if form.validate_on_submit():
        try:
            nombre_grupo = d.validar_nombre(form.nombre.data)
            invitados = [c for c in d.leer_correos(form.correos.data) if c != u]
            if len(invitados) > 20:
                raise d.DatoInvalido("Máximo 20 personas por grupo.")
        except d.DatoInvalido as err:
            flash(str(err), "error")
        else:
            almacen().crear_grupo(nombre_grupo, u, invitados)
            flash(f"Grupo «{nombre_grupo}» creado. Las personas invitadas lo verán al entrar con su correo ✅", "ok")
            return redirect(url_for("kuadra.compartido"))
    return render_template("grupo_nuevo.html", form=form)


@bp.post("/compartido/<grupo_id>/invitar")
@login_requerido
def invitar(grupo_id: str):
    grupo = grupo_del_usuario(grupo_id)
    form = InvitarForm()
    if form.validate_on_submit():
        try:
            correo = d.normalizar_correo(form.correo.data)
        except d.DatoInvalido as err:
            flash(str(err), "error")
        else:
            if correo in almacen().miembros(grupo.id):
                flash(f"{correo} ya está en {grupo.nombre}.", "info")
            elif len(almacen().miembros(grupo.id)) >= 21:
                flash("Máximo 20 personas por grupo.", "error")
            else:
                almacen().invitar(grupo.id, correo)
                flash(f"Listo: {correo} verá «{grupo.nombre}» cuando entre a Kuadra ✅", "ok")
    else:
        flash("Escribe un correo.", "error")
    return redirect(url_for("kuadra.compartido"))


@bp.post("/compartido/<grupo_id>/pago")
@login_requerido
def registrar_pago(grupo_id: str):
    """Registra una transferencia entre miembros (ej. 'Sara le pagó a Manuela') y se descuenta del saldo."""
    grupo = grupo_del_usuario(grupo_id)
    miembros = almacen().miembros(grupo.id)
    form = PagoForm()
    form.de.choices = form.para.choices = [(m, m) for m in miembros]
    if not form.validate_on_submit():
        flash("Revisa el pago: elige las personas y un monto válido.", "error")
        return redirect(url_for("kuadra.compartido"))
    try:
        pago = d.validar_pago(d.Pago(date.today(), form.de.data, form.para.data, form.monto.data), miembros)
    except d.DatoInvalido as err:
        flash(str(err), "error")
    else:
        almacen().agregar_pago(grupo.id, pago)
        flash(f"Pago registrado: {nombre(pago.de)} → {nombre(pago.para)} {pago.monto:,} ✅".replace(",", "."), "ok")
    return redirect(url_for("kuadra.compartido"))


@bp.route("/compartido/<grupo_id>/gasto", methods=["GET", "POST"])
@login_requerido
def nuevo_gasto_grupo(grupo_id: str):
    u = session["usuario"]
    grupo = grupo_del_usuario(grupo_id)
    miembros = almacen().miembros(grupo.id)
    form = GastoGrupoForm()
    opciones = [(m, nombre(m)) for m in miembros]
    form.pagado_por.choices = opciones
    form.dividido_entre.choices = opciones
    if not form.is_submitted():
        form.fecha.data = date.today()
        form.pagado_por.data = u
        form.dividido_entre.data = miembros
    if form.validate_on_submit():
        try:
            gasto = d.validar_gasto_compartido(d.GastoCompartido(
                fecha=form.fecha.data,
                monto=form.monto.data,
                descripcion=form.descripcion.data.strip(),
                pagado_por=form.pagado_por.data,
                dividido_entre=tuple(form.dividido_entre.data),
            ))
        except d.DatoInvalido as err:
            flash(str(err), "error")
        else:
            almacen().agregar_gasto_grupo(grupo.id, gasto)
            flash("Gasto compartido guardado ✅", "ok")
            return redirect(url_for("kuadra.compartido"))
    return render_template("gasto_grupo_nuevo.html", form=form, grupo=grupo.nombre)


# ---------- Perfil ----------

@bp.route("/perfil", methods=["GET", "POST"])
@login_requerido
def perfil():
    u = session["usuario"]
    form_nombre = RegistroForm(prefix="n")
    form_foto = FotoForm(prefix="f")
    if not form_nombre.is_submitted():
        form_nombre.nombre.data = almacen().perfil(u)
    if request.method == "POST" and "n-nombre" in request.form and form_nombre.validate_on_submit():
        try:
            almacen().guardar_perfil(u, d.validar_nombre(form_nombre.nombre.data))
        except d.DatoInvalido as err:
            flash(str(err), "error")
        else:
            flash("Nombre actualizado ✅", "ok")
            return redirect(url_for("kuadra.perfil"))
    if request.method == "POST" and "n-nombre" not in request.form:
        if form_foto.validate_on_submit():
            datos = form_foto.foto.data.read(d.FOTO_MAX_BYTES + 1)
            try:
                tipo = d.tipo_de_imagen(datos)
            except d.DatoInvalido as err:
                flash(str(err), "error")
            else:
                almacen().guardar_foto(u, datos, tipo)
                flash("Foto actualizada ✅", "ok")
                return redirect(url_for("kuadra.perfil"))
        else:
            flash("Selecciona una imagen.", "error")
    return render_template("perfil.html", form_nombre=form_nombre, form_foto=form_foto, correo=u)


@bp.get("/perfil/foto")
@login_requerido
def mi_foto():
    foto = almacen().foto(session["usuario"])
    if not foto:
        abort(404)
    datos, tipo = foto
    resp = Response(datos, mimetype=tipo)
    resp.headers["Cache-Control"] = "private, max-age=300"
    resp.headers["Content-Disposition"] = "inline"
    return resp


# ---------- Asesor ----------

MAX_MENSAJES_CHAT = 4
SUGERENCIAS = ("¿Qué deuda pago primero?", "¿En qué gasto más?", "¿Cómo voy con mis topes?")


def destino_seguro(ruta: str | None) -> str:
    """Solo rutas internas: evita redirecciones abiertas a otros sitios."""
    if ruta and ruta.startswith("/") and not ruta.startswith("//") and "\\" not in ruta:
        return ruta
    return url_for("kuadra.inicio")


@bp.app_context_processor
def panel_asesor():
    """El panel del asesor está en todas las pantallas con sesión."""
    if "usuario" not in session:
        return {}
    form = PreguntaForm(formdata=None)
    form.siguiente.data = request.path
    return {"asesor_form": form, "asesor_chat": session.get("chat", []), "asesor_sugerencias": SUGERENCIAS}


@bp.get("/asesor")
@login_requerido
def asesor():
    # En celular el panel se abre como pantalla completa; en escritorio siempre está visible.
    return redirect(url_for("kuadra.inicio") + "#asesor")


@bp.post("/asesor")
@login_requerido
def preguntar_asesor():
    u = session["usuario"]
    form = PreguntaForm()
    destino = destino_seguro(form.siguiente.data) + "#asesor"
    if not form.validate_on_submit():
        flash("Escribe una pregunta de máximo 500 caracteres.", "error")
        return redirect(destino)
    hoy = date.today()
    resumen = d.resumen_para_ia(
        d.del_mes(almacen().movimientos(u), hoy.year, hoy.month),
        almacen().topes(u),
        almacen().deudas(u),
        saldo_compartido_total(u),
        dias_restantes(hoy),
    )
    pregunta = form.pregunta.data.strip()
    try:
        respuesta = modelo_ia().responder(resumen, pregunta)
    except AsesorNoDisponible:
        # Si Gemini no responde (sin cuota o sin red), contesta el asesor por reglas.
        current_app.logger.warning("Gemini no disponible; se usa el asesor por reglas")
        respuesta = ModeloFalso().responder(resumen, pregunta)
    # La sesión vive en una cookie (máx. ~4 KB): se guardan solo los últimos mensajes, recortados.
    chat = session.get("chat", [])
    nuevos = [{"de": "tu", "texto": pregunta[:300]}, {"de": "kuadra", "texto": respuesta[:900]}]
    session["chat"] = (chat + nuevos)[-MAX_MENSAJES_CHAT:]
    return redirect(destino)


@bp.post("/asesor/limpiar")
@login_requerido
def limpiar_asesor():
    session.pop("chat", None)
    return redirect(destino_seguro(request.form.get("siguiente")) + "#asesor")
