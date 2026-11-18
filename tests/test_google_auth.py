import io
import json
import urllib.error

import pytest

from app import google_auth


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def falso_google(info):
    llamadas = []

    def urlopen(req, timeout):
        llamadas.append(req)
        if req.full_url == google_auth.TOKEN_URL:
            return Resp(json.dumps({"access_token": "tok"}).encode())
        return Resp(json.dumps(info).encode())

    return urlopen, llamadas


def test_pkce_s256():
    verificador, desafio = google_auth.nuevo_pkce()
    assert len(verificador) >= 43 and "=" not in desafio


def test_usuario_verificado(monkeypatch):
    urlopen, llamadas = falso_google({"email": "Manu@Gmail.com", "email_verified": True, "name": "Manu J"})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    u = google_auth.usuario_desde_codigo("id", "secreto", "code", "https://k/cb", "verif")
    assert u == {"correo": "manu@gmail.com", "nombre": "Manu J", "foto": ""}
    assert b"code_verifier=verif" in llamadas[0].data
    assert llamadas[1].headers["Authorization"] == "Bearer tok"


def test_correo_no_verificado(monkeypatch):
    urlopen, _ = falso_google({"email": "x@y.co", "email_verified": False})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(google_auth.ErrorLogin):
        google_auth.usuario_desde_codigo("id", "s", "c", "r", "v")


def test_error_de_red(monkeypatch):
    def falla(req, timeout):
        raise urllib.error.URLError("sin red")

    monkeypatch.setattr("urllib.request.urlopen", falla)
    with pytest.raises(google_auth.ErrorLogin):
        google_auth.usuario_desde_codigo("id", "s", "c", "r", "v")
