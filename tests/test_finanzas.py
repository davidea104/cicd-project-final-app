"""Registrar deudas y topes desde la app."""

import pytest

from app import dominio as d
from app.almacen import USUARIO_DEMO


def test_pagina_finanzas(sesion_demo):
    html = sesion_demo.get("/finanzas").get_data(as_text=True)
    assert "Mis deudas" in html and "Topes mensuales" in html and "Tarjeta de crédito" in html


def test_agregar_deuda(app, sesion_demo):
    resp = sesion_demo.post("/finanzas", data={"accion": "deuda", "d-nombre": "Moto", "d-saldo": "5000000",
                                               "d-tasa_ea": "22.5", "d-cuota": "300000"}, follow_redirects=True)
    assert "Deuda «Moto» registrada" in resp.get_data(as_text=True)
    moto = [x for x in app.extensions["almacen"].deudas(USUARIO_DEMO) if x.nombre == "Moto"][0]
    assert moto.tasa_ea == 22.5 and moto.id


def test_deuda_invalida(app, sesion_demo):
    antes = len(app.extensions["almacen"].deudas(USUARIO_DEMO))
    resp = sesion_demo.post("/finanzas", data={"accion": "deuda", "d-nombre": "X", "d-saldo": "0",
                                               "d-tasa_ea": "10", "d-cuota": "0"}, follow_redirects=True)
    assert "Revisa los datos" in resp.get_data(as_text=True)
    assert len(app.extensions["almacen"].deudas(USUARIO_DEMO)) == antes


def test_eliminar_deuda(app, sesion_demo):
    alm = app.extensions["almacen"]
    deuda = alm.deudas(USUARIO_DEMO)[0]
    sesion_demo.post("/finanzas", data={"accion": "eliminar", "deuda_id": deuda.id})
    assert deuda.id not in [x.id for x in alm.deudas(USUARIO_DEMO)]


def test_guardar_topes(app, sesion_demo):
    sesion_demo.post("/finanzas", data={"accion": "topes", "tope-Mercado": "800000", "tope-Ocio": ""})
    assert app.extensions["almacen"].topes(USUARIO_DEMO) == {"Mercado": 800000}


def test_topes_no_numericos(sesion_demo):
    resp = sesion_demo.post("/finanzas", data={"accion": "topes", "tope-Mercado": "mucho"}, follow_redirects=True)
    assert "deben ser números" in resp.get_data(as_text=True)


def test_analisis_sin_deudas_invita_a_registrarlas(app, sesion_demo):
    alm = app.extensions["almacen"]
    for x in alm.deudas(USUARIO_DEMO):
        alm.eliminar_deuda(USUARIO_DEMO, x.id)
    html = sesion_demo.get("/analisis").get_data(as_text=True)
    assert "¿Qué deuda pagar primero?" not in html
    assert "Registrar deudas y topes" in html


def test_validaciones_dominio():
    with pytest.raises(d.DatoInvalido):
        d.validar_deuda(d.Deuda("X", 100, 250.0, 0))
    with pytest.raises(d.DatoInvalido):
        d.validar_deuda(d.Deuda("X", 100, 10.0, -1))
    with pytest.raises(d.DatoInvalido):
        d.validar_topes({"Casino": 100})
    with pytest.raises(d.DatoInvalido):
        d.validar_topes({"Mercado": -1})


def test_post_sin_csrf_rechazado():
    from app import create_app
    from app.almacen import almacen_demo

    app = create_app({"TESTING": True, "SECRET_KEY": "x", "ALMACEN": almacen_demo(), "MODO_DEMO": True})
    c = app.test_client()
    with c.session_transaction() as s:
        s["usuario"] = USUARIO_DEMO
    assert c.post("/finanzas", data={"accion": "topes"}).status_code == 400
