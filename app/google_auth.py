"""Inicio de sesión con Google (OAuth 2.0 + OpenID Connect, flujo de código con PKCE).

Solo se piden los permisos `openid email profile`: Kuadra conoce el correo y el nombre,
nunca la contraseña ni el contenido del Drive del usuario.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (es una URL, no una contraseña)
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
ALCANCES = "openid email profile"


class ErrorLogin(Exception):
    """El inicio de sesión con Google falló."""


def nuevo_pkce() -> tuple[str, str]:
    """Devuelve (verificador, desafío) para PKCE S256."""
    verificador = secrets.token_urlsafe(64)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    return verificador, desafio


def url_autorizacion(client_id: str, redirect_uri: str, estado: str, desafio: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ALCANCES,
        "state": estado,
        "code_challenge": desafio,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    })


def _post_json(url: str, datos: dict, timeout: float) -> dict:
    req = urllib.request.Request(  # noqa: S310 (URL fija https)
        url, data=urllib.parse.urlencode(datos).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read())


def usuario_desde_codigo(
    client_id: str, client_secret: str, codigo: str, redirect_uri: str, verificador: str, timeout: float = 10.0
) -> dict:
    """Cambia el código por un token y devuelve {'correo', 'nombre'} del usuario verificado."""
    try:
        token = _post_json(TOKEN_URL, {
            "code": codigo,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verificador,
        }, timeout)
        req = urllib.request.Request(  # noqa: S310 (URL fija https)
            USERINFO_URL, headers={"Authorization": f"Bearer {token['access_token']}"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            info = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        raise ErrorLogin("No se pudo completar el inicio de sesión con Google.") from exc
    if not info.get("email") or not info.get("email_verified"):
        raise ErrorLogin("Tu correo de Google no está verificado.")
    foto = info.get("picture") or ""
    return {
        "correo": info["email"].lower(),
        "nombre": info.get("name") or info.get("given_name") or "",
        "foto": foto if foto.startswith("https://") else "",
    }
