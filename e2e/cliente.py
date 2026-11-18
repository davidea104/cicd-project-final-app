"""Cliente HTTP para probar Kuadra desplegada (staging o producción), como lo haría un navegador."""

from __future__ import annotations

import os
import re

import requests

BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000").rstrip("/")
TOKEN_PRUEBAS = os.environ.get("TOKEN_PRUEBAS", "")
TIMEOUT = 20


class Navegador:
    """Una sesión con cookies, como la de un usuario real."""

    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "kuadra-e2e"

    def get(self, ruta: str, **kw) -> requests.Response:
        return self.s.get(BASE_URL + ruta, timeout=TIMEOUT, **kw)

    def post(self, ruta: str, **kw) -> requests.Response:
        return self.s.post(BASE_URL + ruta, timeout=TIMEOUT, **kw)

    def csrf(self, ruta: str) -> str:
        html = self.get(ruta).text
        m = re.search(r'name="(?:[a-z]-)?csrf_token"[^>]*value="([^"]+)"', html) or re.search(
            r'value="([^"]+)"[^>]*name="(?:[a-z]-)?csrf_token"', html
        )
        assert m, f"No se encontró el token CSRF en {ruta}"
        return m.group(1)

    def enviar(self, ruta_form: str, ruta_post: str | None = None, **datos) -> requests.Response:
        """Abre el formulario, toma su token CSRF y lo envía (siguiendo la redirección)."""
        datos["csrf_token"] = self.csrf(ruta_form)
        return self.post(ruta_post or ruta_form, data=datos)

    def entrar_pruebas(self, correo: str) -> None:
        r = self.post("/pruebas/login", data={"correo": correo}, headers={"X-Token-Pruebas": TOKEN_PRUEBAS})
        assert r.status_code == 200, f"Login de pruebas falló ({r.status_code})"
