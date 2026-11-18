import pytest

from app import create_app
from app.almacen import almacen_demo
from app.asesor import ModeloFalso


@pytest.fixture
def app():
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "pruebas",
        "WTF_CSRF_ENABLED": False,
        "MODO_DEMO": True,
        "ALMACEN": almacen_demo(),
        "MODELO_IA": ModeloFalso(),
    })


@pytest.fixture
def cliente(app):
    return app.test_client()


@pytest.fixture
def sesion_demo(cliente):
    cliente.post("/demo")
    return cliente
