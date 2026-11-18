"""La entrada de pruebas solo existe en staging, con token secreto y correos @pruebas.kuadra.app."""

import pytest

from app import create_app
from app.almacen import AlmacenMemoria

TOKEN = "t" * 40


def app_con(ambiente, token=TOKEN):
    return create_app({"TESTING": True, "SECRET_KEY": "x", "AMBIENTE": ambiente, "TOKEN_PRUEBAS": token,
                       "ALMACEN": AlmacenMemoria(), "MODO_DEMO": False})


def entrar(app, correo="ana@pruebas.kuadra.app", token=TOKEN):
    return app.test_client().post("/pruebas/login", data={"correo": correo}, headers={"X-Token-Pruebas": token})


def test_staging_con_token_entra():
    app = app_con("staging")
    c = app.test_client()
    resp = c.post("/pruebas/login", data={"correo": "Ana@Pruebas.Kuadra.App"}, headers={"X-Token-Pruebas": TOKEN})
    assert resp.status_code == 200 and resp.get_json()["usuario"] == "ana@pruebas.kuadra.app"
    assert c.get("/").headers["Location"].endswith("/registro")  # luego debe registrarse como cualquiera


@pytest.mark.parametrize("ambiente", ["production", "local", "ci"])
def test_no_existe_fuera_de_staging(ambiente):
    assert entrar(app_con(ambiente)).status_code == 404


def test_token_incorrecto():
    assert entrar(app_con("staging"), token="otro" * 10).status_code == 404


def test_sin_token_configurado():
    assert entrar(app_con("staging", token=""), token="").status_code == 404


def test_token_corto_no_sirve():
    assert entrar(app_con("staging", token="corto"), token="corto").status_code == 404


def test_solo_correos_de_prueba():
    assert entrar(app_con("staging"), correo="manuela@gmail.com").status_code == 404
