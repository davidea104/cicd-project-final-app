"""Registro con nombre, login con Google (simulado) y grupos compartidos por correo."""

import pytest

from app import create_app, google_auth
from app.almacen import AlmacenMemoria
from app.asesor import ModeloFalso


@pytest.fixture
def app_vacia():
    return create_app({
        "TESTING": True, "SECRET_KEY": "x", "WTF_CSRF_ENABLED": False, "MODO_DEMO": False,
        "ALMACEN": AlmacenMemoria(), "MODELO_IA": ModeloFalso(),
        "GOOGLE_CLIENT_ID": "cliente", "GOOGLE_CLIENT_SECRET": "secreto", "URL_PUBLICA": "https://kuadra.test",
    })


def entrar_como(app, correo, monkeypatch, nombre_google="Persona"):
    """Simula el ida y vuelta con Google y devuelve un cliente con sesión."""
    c = app.test_client()
    resp = c.get("/login/google")
    assert resp.status_code == 302 and resp.headers["Location"].startswith(google_auth.AUTH_URL)
    with c.session_transaction() as s:
        estado = s["oauth_estado"]
    monkeypatch.setattr(google_auth, "usuario_desde_codigo",
                        lambda *a, **k: {"correo": correo, "nombre": nombre_google})
    resp = c.get(f"/auth/google/callback?state={estado}&code=abc")
    assert resp.status_code == 302
    return c


def registrarse(c, nombre):
    return c.post("/registro", data={"nombre": nombre})


# ---------- Login con Google ----------

def test_url_de_google_lleva_pkce_y_redirect(app_vacia):
    resp = app_vacia.test_client().get("/login/google")
    url = resp.headers["Location"]
    assert "code_challenge_method=S256" in url
    assert "redirect_uri=https%3A%2F%2Fkuadra.test%2Fauth%2Fgoogle%2Fcallback" in url
    assert "scope=openid+email+profile" in url  # sin permisos de Drive


def test_callback_con_estado_falso_no_inicia_sesion(app_vacia):
    c = app_vacia.test_client()
    c.get("/login/google")
    resp = c.get("/auth/google/callback?state=falso&code=abc", follow_redirects=True)
    assert "La sesión expiró" in resp.get_data(as_text=True)
    with c.session_transaction() as s:
        assert "usuario" not in s


def test_callback_cancelado(app_vacia):
    c = app_vacia.test_client()
    c.get("/login/google")
    with c.session_transaction() as s:
        estado = s["oauth_estado"]
    resp = c.get(f"/auth/google/callback?state={estado}&error=access_denied", follow_redirects=True)
    assert "Cancelaste" in resp.get_data(as_text=True)


def test_callback_error_de_google(app_vacia, monkeypatch):
    c = app_vacia.test_client()
    c.get("/login/google")
    with c.session_transaction() as s:
        estado = s["oauth_estado"]

    def falla(*a, **k):
        raise google_auth.ErrorLogin("Tu correo de Google no está verificado.")

    monkeypatch.setattr(google_auth, "usuario_desde_codigo", falla)
    resp = c.get(f"/auth/google/callback?state={estado}&code=x", follow_redirects=True)
    assert "no está verificado" in resp.get_data(as_text=True)


def test_sin_configurar_google():
    app = create_app({"TESTING": True, "SECRET_KEY": "x", "WTF_CSRF_ENABLED": False, "ALMACEN": AlmacenMemoria()})
    resp = app.test_client().get("/login/google", follow_redirects=True)
    assert "no está configurado" in resp.get_data(as_text=True)


# ---------- Registro ----------

def test_primer_ingreso_pide_nombre(app_vacia, monkeypatch):
    c = entrar_como(app_vacia, "manu@gmail.com", monkeypatch, "Manuela Jiménez")
    resp = c.get("/")
    assert resp.headers["Location"].endswith("/registro")
    html = c.get("/registro").get_data(as_text=True)
    assert 'value="Manuela Jiménez"' in html  # sugiere el nombre de Google
    registrarse(c, "Manu")
    assert app_vacia.extensions["almacen"].perfil("manu@gmail.com") == "Manu"
    assert "Manu" in c.get("/").get_data(as_text=True)


def test_registro_nombre_vacio(app_vacia, monkeypatch):
    c = entrar_como(app_vacia, "manu@gmail.com", monkeypatch)
    resp = registrarse(c, "   ")
    assert resp.status_code == 200
    assert app_vacia.extensions["almacen"].perfil("manu@gmail.com") is None


def test_registro_sin_sesion(app_vacia):
    assert "/bienvenida" in app_vacia.test_client().get("/registro").headers["Location"]


def test_registro_ya_hecho_va_al_inicio(app_vacia, monkeypatch):
    c = entrar_como(app_vacia, "manu@gmail.com", monkeypatch)
    registrarse(c, "Manu")
    assert c.get("/registro").headers["Location"].endswith("/")


# ---------- Grupos compartidos por correo ----------

def test_compartir_por_correo_y_la_otra_persona_lo_ve(app_vacia, monkeypatch):
    manu = entrar_como(app_vacia, "manu@gmail.com", monkeypatch)
    registrarse(manu, "Manu")
    resp = manu.post("/compartido/nuevo", data={"nombre": "Hermanas", "correos": "Ana@Gmail.com, sofia@gmail.com"})
    assert resp.status_code == 302

    # Ana entra por primera vez: tras registrarse ve el grupo
    ana = entrar_como(app_vacia, "ana@gmail.com", monkeypatch)
    resp = registrarse(ana, "Ana")
    html = ana.get("/compartido").get_data(as_text=True)
    assert "Hermanas" in html and "Manu" in html

    # Una persona que no fue invitada no lo ve
    otra = entrar_como(app_vacia, "otra@gmail.com", monkeypatch)
    registrarse(otra, "Otra")
    assert "Hermanas" not in otra.get("/compartido").get_data(as_text=True)


def test_gasto_compartido_entre_dos_cuentas(app_vacia, monkeypatch):
    alm = app_vacia.extensions["almacen"]
    manu = entrar_como(app_vacia, "manu@gmail.com", monkeypatch)
    registrarse(manu, "Manu")
    manu.post("/compartido/nuevo", data={"nombre": "Casa", "correos": "ana@gmail.com"})
    casa = alm.grupos("manu@gmail.com")[0].id
    manu.post(f"/compartido/{casa}/gasto", data={
        "monto": "100000", "descripcion": "Mercado", "pagado_por": "manu@gmail.com",
        "dividido_entre": ["manu@gmail.com", "ana@gmail.com"], "fecha": "2026-11-17",
    })
    ana = entrar_como(app_vacia, "ana@gmail.com", monkeypatch)
    registrarse(ana, "Ana")
    html = ana.get("/compartido").get_data(as_text=True)
    assert "Debes $50.000" in html
    assert "Debes $50.000" in ana.get("/").get_data(as_text=True)
    assert "Te deben $50.000" in manu.get("/compartido").get_data(as_text=True)


def test_invitar_despues(app_vacia, monkeypatch):
    alm = app_vacia.extensions["almacen"]
    manu = entrar_como(app_vacia, "manu@gmail.com", monkeypatch)
    registrarse(manu, "Manu")
    manu.post("/compartido/nuevo", data={"nombre": "Pareja", "correos": ""})
    gid = alm.grupos("manu@gmail.com")[0].id
    resp = manu.post(f"/compartido/{gid}/invitar", data={"correo": "Novio@Gmail.com "}, follow_redirects=True)
    assert "novio@gmail.com verá «Pareja»" in resp.get_data(as_text=True)
    assert "novio@gmail.com" in alm.miembros(gid)
    resp = manu.post(f"/compartido/{gid}/invitar", data={"correo": "novio@gmail.com"}, follow_redirects=True)
    assert "ya está en Pareja" in resp.get_data(as_text=True)
    resp = manu.post(f"/compartido/{gid}/invitar", data={"correo": "no-es-correo"}, follow_redirects=True)
    assert "Correo no válido" in resp.get_data(as_text=True)
    resp = manu.post(f"/compartido/{gid}/invitar", data={"correo": ""}, follow_redirects=True)
    assert "Escribe un correo" in resp.get_data(as_text=True)


def test_no_se_puede_invitar_a_grupo_ajeno(app_vacia, monkeypatch):
    alm = app_vacia.extensions["almacen"]
    gid = alm.crear_grupo("Privado", "duena@gmail.com", [])
    intruso = entrar_como(app_vacia, "intruso@gmail.com", monkeypatch)
    registrarse(intruso, "Intruso")
    assert intruso.post(f"/compartido/{gid}/invitar", data={"correo": "intruso@gmail.com"}).status_code == 404
    assert intruso.get(f"/compartido/{gid}/gasto").status_code == 404
    assert alm.miembros(gid) == ["duena@gmail.com"]


def test_crear_grupo_con_correo_invalido(app_vacia, monkeypatch):
    manu = entrar_como(app_vacia, "manu@gmail.com", monkeypatch)
    registrarse(manu, "Manu")
    resp = manu.post("/compartido/nuevo", data={"nombre": "Casa", "correos": "ana@gmail.com, malo"})
    assert resp.status_code == 200
    assert "Correo no válido: malo" in resp.get_data(as_text=True)
    assert app_vacia.extensions["almacen"].grupos("manu@gmail.com") == []


def test_crear_grupo_maximo_20(app_vacia, monkeypatch):
    manu = entrar_como(app_vacia, "manu@gmail.com", monkeypatch)
    registrarse(manu, "Manu")
    correos = ", ".join(f"p{i}@x.co" for i in range(21))
    resp = manu.post("/compartido/nuevo", data={"nombre": "Grande", "correos": correos})
    assert "Máximo 20" in resp.get_data(as_text=True)


def test_pagina_nuevo_grupo(app_vacia, monkeypatch):
    manu = entrar_como(app_vacia, "manu@gmail.com", monkeypatch)
    registrarse(manu, "Manu")
    assert "Crear grupo" in manu.get("/compartido/nuevo").get_data(as_text=True)
    assert "Aún no tienes grupos" in manu.get("/compartido").get_data(as_text=True)
