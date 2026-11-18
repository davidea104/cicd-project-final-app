"""Kuadra — tus cuentas, en orden."""

from __future__ import annotations

import os
import secrets

from flask import Flask
from flask_wtf.csrf import CSRFProtect

from app.almacen import AlmacenDynamo, almacen_demo
from app.asesor import GeminiModelo, ModeloFalso

csrf = CSRFProtect()


def _bool(valor: str | None) -> bool:
    return (valor or "").lower() in ("1", "true", "si", "sí", "yes")


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    clave = os.environ.get("SECRET_KEY")
    if not clave and os.environ.get("AMBIENTE", "local") != "local" and not (config or {}).get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY es obligatoria fuera del ambiente local.")
    app.config.update(
        SECRET_KEY=clave or secrets.token_hex(32),
        MODO_DEMO=_bool(os.environ.get("MODO_DEMO", "true")),
        AMBIENTE=os.environ.get("AMBIENTE", "local"),
        VERSION=os.environ.get("APP_VERSION", "dev"),
        GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY", ""),
        GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID", ""),
        GOOGLE_CLIENT_SECRET=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        URL_PUBLICA=os.environ.get("URL_PUBLICA", ""),
        DYNAMODB_TABLA=os.environ.get("DYNAMODB_TABLA", ""),
        GEMINI_MODELO=os.environ.get("GEMINI_MODELO", "gemini-flash-lite-latest"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_bool(os.environ.get("COOKIE_SEGURA", "false")),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )
    if config:
        app.config.update(config)

    csrf.init_app(app)

    if app.config.get("ALMACEN"):
        app.extensions["almacen"] = app.config["ALMACEN"]
    elif app.config["DYNAMODB_TABLA"]:
        app.extensions["almacen"] = AlmacenDynamo.desde_nombre(app.config["DYNAMODB_TABLA"])
    else:
        app.extensions["almacen"] = almacen_demo()
    if app.config.get("MODELO_IA"):
        app.extensions["modelo_ia"] = app.config["MODELO_IA"]
    elif app.config["GEMINI_API_KEY"]:
        app.extensions["modelo_ia"] = GeminiModelo(app.config["GEMINI_API_KEY"], app.config["GEMINI_MODELO"])
    else:
        app.extensions["modelo_ia"] = ModeloFalso()

    from app.rutas import bp

    app.register_blueprint(bp)

    @app.template_filter("pesos")
    def pesos(valor: int) -> str:
        signo = "-" if valor < 0 else ""
        return f"{signo}${abs(int(valor)):,}".replace(",", ".")

    @app.after_request
    def cabeceras_seguridad(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: https://lh3.googleusercontent.com; "
            "style-src 'self'; script-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if app.config["SESSION_COOKIE_SECURE"]:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resp

    return app
