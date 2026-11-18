from app.asesor import PROMPT_SISTEMA, ModeloFalso

CON_DEUDA_CARA = {
    "gastos_mes": 1_588_000,
    "balance_mes": 2_612_000,
    "dias_restantes_mes": 14,
    "gastos_por_categoria": {"Mercado": 830_000, "Deudas": 350_000},
    "categorias_excedidas": ["Mercado"],
    "disponible_por_categoria": {"Mercado": -130_000, "Ocio": 90_000},
    "deudas_en_orden_de_pago": [
        {"deuda": "Deuda 1", "saldo": 1_800_000, "tasa_ea": 28.6, "cuota": 350_000},
        {"deuda": "Deuda 2", "saldo": 12_000_000, "tasa_ea": 16.5, "cuota": 450_000},
        {"deuda": "Deuda 3", "saldo": 600_000, "tasa_ea": 0.0, "cuota": 100_000},
    ],
}
SANO = {
    "gastos_mes": 1_000_000,
    "balance_mes": 2_000_000,
    "dias_restantes_mes": 10,
    "gastos_por_categoria": {"Comida": 600_000},
    "categorias_excedidas": [],
    "disponible_por_categoria": {"Comida": 100_000},
    "deudas_en_orden_de_pago": [],
}
asesor = ModeloFalso()


def test_compra_con_deuda_cara_dice_no():
    r = asesor.responder(CON_DEUDA_CARA, "si en este momento me quisiera comprar unos zapatos lo podría hacer?")
    assert r.startswith("No.")
    assert "construir futuro" in r
    assert "28.6% E.A." in r and "$1.800.000" in r and "Mercado" in r


def test_compra_con_finanzas_sanas_dice_si_con_limite():
    r = asesor.responder(SANO, "¿Puedo comprarme unos tenis?")
    assert r.startswith("Sí")
    assert "$400.000" in r


def test_compra_con_balance_negativo_dice_no():
    r = asesor.responder({**SANO, "balance_mes": -50_000}, "¿puedo salir a comer?")
    assert r.startswith("No.")


def test_en_que_gasto_mas():
    r = asesor.responder(CON_DEUDA_CARA, "¿En qué gasto más?")
    assert "Mercado" in r and "$830.000" in r


def test_orden_de_deudas():
    r = asesor.responder(CON_DEUDA_CARA, "¿Qué deuda pago primero?")
    assert "28.6%" in r and "16.5%" in r and "no la adelantes" in r


def test_sin_deudas():
    assert "fondo de emergencia" in asesor.responder(SANO, "¿qué deuda pago primero?")


def test_topes():
    assert "Mercado" in asesor.responder(CON_DEUDA_CARA, "¿Cómo voy con mis topes?")
    assert "Comida $100.000" in asesor.responder(SANO, "¿cómo voy con el presupuesto?")


def test_sin_gastos():
    assert "no tienes gastos" in asesor.responder({**SANO, "gastos_por_categoria": {}}, "en qué gasto más")


def test_pregunta_general():
    assert "Pregúntame" in asesor.responder(SANO, "hola")


def test_prompt_pide_firmeza():
    assert "NO sin rodeos" in PROMPT_SISTEMA
    assert "construir futuro" in PROMPT_SISTEMA
