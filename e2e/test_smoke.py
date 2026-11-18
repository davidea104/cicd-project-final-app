"""Smoke tests (POST-PROD): rápidos y sin modificar datos. Si fallan, el pipeline hace rollback.

Se ejecutan contra producción (y también contra staging). Validan que la versión correcta esté
arriba, que la entrada sea HTTPS segura y que en producción no queden puertas de prueba abiertas.
"""

import os

from e2e.cliente import BASE_URL, Navegador

VERSION = os.environ.get("EXPECTED_VERSION", "")
AMBIENTE = os.environ.get("EXPECTED_ENV", "")


def test_url_es_https():
    assert BASE_URL.startswith("https://"), "La app debe publicarse por HTTPS"


def test_health_y_version():
    datos = Navegador().get("/health").json()
    assert datos["estado"] == "ok"
    if VERSION:
        assert datos["version"] == VERSION, "La versión desplegada no es la esperada"
    if AMBIENTE:
        assert datos["ambiente"] == AMBIENTE


def test_bienvenida_carga():
    r = Navegador().get("/bienvenida")
    assert r.status_code == 200
    assert "Kuadra" in r.text and "Continuar con Google" in r.text


def test_cabeceras_de_seguridad():
    h = Navegador().get("/bienvenida").headers
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert "max-age" in h["Strict-Transport-Security"]
    assert h["X-Content-Type-Options"] == "nosniff"


def test_cookie_de_sesion_segura():
    cookie = Navegador().get("/bienvenida").headers.get("Set-Cookie", "")
    assert "Secure" in cookie and "HttpOnly" in cookie


def test_rutas_protegidas_piden_sesion():
    r = Navegador().get("/", allow_redirects=False)
    assert r.status_code == 302 and "/bienvenida" in r.headers["Location"]


def test_estaticos():
    assert Navegador().get("/static/kuadra.css").status_code == 200


def test_sin_puertas_de_prueba_en_produccion():
    if AMBIENTE != "production":
        return
    nav = Navegador()
    assert nav.post("/pruebas/login", data={"correo": "x@pruebas.kuadra.app"},
                    headers={"X-Token-Pruebas": "x" * 40}).status_code == 404
    assert "Probar la demo" not in nav.get("/bienvenida").text
