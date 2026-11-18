"""Aceptación de interfaz con Selenium (Chrome sin pantalla) contra STAGING.

Recorre la app como una persona: entra a la demo, se registra si hace falta y agrega un gasto.
"""

import os
import uuid

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from e2e.cliente import BASE_URL

pytestmark = pytest.mark.skipif(os.environ.get("EXPECTED_ENV") == "production", reason="Solo staging")


@pytest.fixture
def navegador():
    opciones = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,900"):
        opciones.add_argument(arg)
    driver = webdriver.Chrome(options=opciones)
    yield driver
    driver.quit()


def esperar(driver, by, valor):
    return WebDriverWait(driver, 20).until(EC.presence_of_element_located((by, valor)))


def test_demo_agregar_gasto(navegador):
    navegador.get(BASE_URL + "/bienvenida")
    esperar(navegador, By.ID, "entrar-demo").click()
    WebDriverWait(navegador, 20).until(lambda d: "/bienvenida" not in d.current_url)
    if "/registro" in navegador.current_url:
        campo = esperar(navegador, By.NAME, "nombre")
        campo.clear()
        campo.send_keys("Demo")
        navegador.find_element(By.ID, "crear-cuenta").click()
    esperar(navegador, By.CLASS_NAME, "saludo")
    assert "Hola" in navegador.page_source

    descripcion = f"Helado {uuid.uuid4().hex[:6]}"
    navegador.get(BASE_URL + "/movimientos/nuevo")
    Select(esperar(navegador, By.NAME, "tipo")).select_by_value("gasto")
    navegador.find_element(By.NAME, "monto").send_keys("12000")
    navegador.find_element(By.NAME, "descripcion").send_keys(descripcion)
    Select(navegador.find_element(By.NAME, "categoria")).select_by_value("Comida")
    navegador.find_element(By.CSS_SELECTOR, "form.tarjeta button[type='submit']").click()

    esperar(navegador, By.CLASS_NAME, "aviso")
    assert "Movimiento guardado" in navegador.page_source
    assert descripcion in navegador.page_source
