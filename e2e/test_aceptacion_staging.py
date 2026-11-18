"""Pruebas de aceptación (PRE-PROD) contra STAGING desplegado en AWS.

Recorren los flujos principales con la app real (API Gateway → ALB → ECS → DynamoDB → Gemini):
registro, gasto personal, grupo compartido por correo, gasto dividido, transferencia y asesor.
Cada ejecución usa correos únicos @pruebas.kuadra.app para no mezclar datos.
"""

import re
import uuid

import pytest

from e2e.cliente import TOKEN_PRUEBAS, Navegador

pytestmark = pytest.mark.skipif(not TOKEN_PRUEBAS, reason="Falta TOKEN_PRUEBAS")

ID = uuid.uuid4().hex[:8]
MANU = f"manu-{ID}@pruebas.kuadra.app"
ANA = f"ana-{ID}@pruebas.kuadra.app"
INTRUSO = f"intruso-{ID}@pruebas.kuadra.app"


def nuevo_usuario(correo: str, nombre: str) -> Navegador:
    nav = Navegador()
    nav.entrar_pruebas(correo)
    r = nav.enviar("/registro", nombre=nombre)
    assert f"Hola, {nombre}" in r.text, "Después del registro debe saludar por el nombre"
    return nav


@pytest.fixture(scope="module")
def manu():
    return nuevo_usuario(MANU, "Manu")


@pytest.fixture(scope="module")
def ana():
    return nuevo_usuario(ANA, "Ana")


@pytest.fixture(scope="module")
def grupo_id(manu, ana):
    r = manu.enviar("/compartido/nuevo", nombre=f"Hermanas {ID}", correos=ANA)
    assert "creado" in r.text
    m = re.search(r'/compartido/([0-9a-f]{12})/gasto', r.text)
    assert m, "El grupo nuevo debe aparecer en Compartido"
    return m.group(1)


def test_primer_ingreso_pide_nombre():
    nav = Navegador()
    nav.entrar_pruebas(f"nuevo-{ID}@pruebas.kuadra.app")
    assert "Crear mi cuenta" in nav.get("/").text


def test_gasto_personal_se_guarda(manu):
    r = manu.enviar("/movimientos/nuevo", tipo="gasto", monto="45000", descripcion=f"Almuerzo {ID}",
                    categoria="Comida", medio="Efectivo", fecha="2026-11-18")
    assert "Movimiento guardado" in r.text
    assert f"Almuerzo {ID}" in r.text


def test_grupo_compartido_lo_ve_la_invitada(grupo_id, ana):
    html = ana.get("/compartido").text
    assert f"Hermanas {ID}" in html
    assert "Manu" in html


def test_persona_no_invitada_no_ve_el_grupo(grupo_id):
    intruso = nuevo_usuario(INTRUSO, "Intruso")
    assert f"Hermanas {ID}" not in intruso.get("/compartido").text
    assert intruso.get(f"/compartido/{grupo_id}/gasto").status_code == 404


def test_gasto_compartido_se_divide(manu, ana, grupo_id):
    r = manu.enviar(f"/compartido/{grupo_id}/gasto", monto="100000", descripcion="Mercado",
                    pagado_por=MANU, dividido_entre=[MANU, ANA], fecha="2026-11-18")
    assert "Gasto compartido guardado" in r.text
    assert "Te deben $50.000" in manu.get("/compartido").text
    assert "Debes $50.000" in ana.get("/compartido").text
    assert "Debes $50.000" in ana.get("/").text  # también en el inicio de Ana


def test_transferencia_deja_a_paz_y_salvo(manu, ana, grupo_id):
    test_gasto = ana.get("/compartido").text
    assert "Debes $50.000" in test_gasto
    r = ana.post(f"/compartido/{grupo_id}/pago", data={
        "csrf_token": ana.csrf("/compartido"), "de": ANA, "para": MANU, "monto": "50000",
    })
    assert "Pago registrado" in r.text
    assert "A paz y salvo" in ana.get("/compartido").text
    assert "A paz y salvo" in manu.get("/compartido").text


def test_invitar_despues_por_correo(manu, grupo_id):
    nuevo = f"sara-{ID}@pruebas.kuadra.app"
    r = manu.post(f"/compartido/{grupo_id}/invitar", data={"csrf_token": manu.csrf("/compartido"), "correo": nuevo})
    assert "verá" in r.text
    sara = nuevo_usuario(nuevo, "Sara")
    assert f"Hermanas {ID}" in sara.get("/compartido").text


def test_asesor_responde(manu):
    r = manu.post("/asesor", data={"csrf_token": manu.csrf("/"), "pregunta": "¿Puedo comprar unos zapatos?",
                                   "siguiente": "/"})
    burbujas = re.findall(r'class="burbuja kuadra">(.*?)</div>', r.text, re.S)
    assert burbujas and len(burbujas[0].strip()) > 20, "El asesor debe responder algo con sentido"


def test_login_de_pruebas_rechaza_token_falso():
    r = Navegador().post("/pruebas/login", data={"correo": MANU}, headers={"X-Token-Pruebas": "falso" * 10})
    assert r.status_code == 404
