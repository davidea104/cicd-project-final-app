"""AlmacenDynamo contra una DynamoDB simulada (moto): mismo comportamiento que en AWS."""

from datetime import date

import boto3
import pytest
from moto import mock_aws

from app.almacen import AlmacenDynamo
from app.dominio import Deuda, GastoCompartido, Movimiento


@pytest.fixture
def alm(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="kuadra-test",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield AlmacenDynamo.desde_nombre("kuadra-test")


def test_perfil(alm):
    assert alm.perfil("a@x.co") is None
    alm.guardar_perfil("a@x.co", "Ana")
    assert alm.perfil("a@x.co") == "Ana"


def test_movimientos_ordenados(alm):
    alm.agregar_movimiento("a@x.co", Movimiento(date(2026, 11, 1), 100, "uno", "Comida", "Efectivo", "gasto"))
    alm.agregar_movimiento("a@x.co", Movimiento(date(2026, 11, 5), 200, "dos", "Mercado", "Débito", "gasto"))
    alm.agregar_movimiento("b@x.co", Movimiento(date(2026, 11, 5), 999, "otro", "Mercado", "Débito", "gasto"))
    movs = alm.movimientos("a@x.co")
    assert [m.descripcion for m in movs] == ["dos", "uno"]
    assert movs[0].monto == 200 and isinstance(movs[0].monto, int)


def test_topes_y_deudas_vacios(alm):
    assert alm.topes("a@x.co") == {}
    assert alm.deudas("a@x.co") == []


def test_topes_y_deudas(alm):
    alm._t.put_item(Item={"PK": "USER#a@x.co", "SK": "TOPES", "topes": {"Mercado": 700000}})
    alm._t.put_item(Item={"PK": "USER#a@x.co", "SK": "DEUDA#1", "nombre": "Tarjeta", "saldo": 1000,
                          "tasa_ea": "28.6", "cuota": 100})
    assert alm.topes("a@x.co") == {"Mercado": 700000}
    assert alm.deudas("a@x.co") == [Deuda("Tarjeta", 1000, 28.6, 100)]


def test_grupos_compartidos(alm):
    gid = alm.crear_grupo("Hermanas", "manu@x.co", ["ana@x.co"])
    assert [g.nombre for g in alm.grupos("ana@x.co")] == ["Hermanas"]
    assert alm.grupos("otra@x.co") == []
    alm.invitar(gid, "sofia@x.co")
    assert set(alm.miembros(gid)) == {"manu@x.co", "ana@x.co", "sofia@x.co"}
    assert alm.grupo(gid).creador == "manu@x.co"
    assert alm.grupo("noexiste") is None


def test_invitar_a_grupo_inexistente(alm):
    with pytest.raises(KeyError):
        alm.invitar("noexiste", "a@x.co")


def test_gastos_grupo(alm):
    gid = alm.crear_grupo("Casa", "manu@x.co", ["ana@x.co"])
    alm.agregar_gasto_grupo(gid, GastoCompartido(date(2026, 11, 2), 300, "Mercado", "manu@x.co",
                                                 ("manu@x.co", "ana@x.co")))
    gastos = alm.gastos_grupo(gid)
    assert gastos[0].dividido_entre == ("manu@x.co", "ana@x.co")
    assert alm.pagos_grupo(gid) == []


def test_pagos_grupo(alm):
    gid = alm.crear_grupo("Casa", "manu@x.co", [])
    alm._t.put_item(Item={"PK": f"GRUPO#{gid}", "SK": "PAGO#2026-11-03#1", "fecha": "2026-11-03",
                          "de": "ana@x.co", "para": "manu@x.co", "monto": 50})
    assert alm.pagos_grupo(gid)[0].monto == 50


def test_pagos_y_foto(alm):
    from app.dominio import Pago

    gid = alm.crear_grupo("Casa", "manu@x.co", ["sara@x.co"])
    alm.agregar_pago(gid, Pago(date(2026, 11, 4), "sara@x.co", "manu@x.co", 40000))
    assert alm.pagos_grupo(gid)[0].monto == 40000
    assert alm.foto("manu@x.co") is None
    alm.guardar_foto("manu@x.co", b"\xff\xd8\xffdatos", "image/jpeg")
    assert alm.foto("manu@x.co") == (b"\xff\xd8\xffdatos", "image/jpeg")
