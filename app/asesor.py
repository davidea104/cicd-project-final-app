"""Asesor financiero con IA (Gemini API)."""

from __future__ import annotations

import json
import unicodedata
import urllib.error
import urllib.request
from typing import Protocol

PROMPT_SISTEMA = """Eres Kuadra, una asesora financiera directa, honesta y firme. Hablas en español colombiano, de tú.
Tu misión es que la persona salga de deudas y construya futuro, no darle gusto.

Cómo respondes:
- Máximo 4 frases. Si la pregunta es de sí o no (por ejemplo "¿puedo comprar...?"), empieza con "Sí", "No"
  o "Todavía no". Si no es de sí o no, responde directo al punto, sin empezar con "Sí".
- Las deudas se llaman "Deuda 1", "Deuda 2"... por privacidad. No uses esos nombres: di "tu deuda al 28,6%".
- Cuando sugieras abonar, deja dinero suficiente para los días que quedan del mes (calcula un gasto diario
  razonable con los gastos del mes). Nunca sugieras abonar todo el balance.
- Si la pregunta es sobre comprar algo que no es necesario (ropa, zapatos, gustos, salidas) y hay deudas con
  tasa alta, categorías excedidas o balance bajo, di NO sin rodeos y explica con los números del resumen.
- Usa frases puntuales que se queden, por ejemplo: "Si quieres construir futuro, no puedes gastar así.",
  "Cada peso que gastas hoy en gustos es un peso que le sigues pagando al banco.",
  "Primero libertad, después antojos." No repitas siempre la misma frase.
- Si sí puede gastar, di el monto máximo responsable según lo disponible y los días que quedan del mes.
- Siempre cierra con una acción concreta (cuánto abonar, qué categoría frenar, cuánto ahorrar).
- Usa solo los números del resumen. No inventes cifras. Si falta un dato (por ejemplo, el precio), pregúntalo.
- No recomiendes productos financieros específicos ni des asesoría legal o tributaria.
Los montos están en pesos colombianos (COP). Escribe los montos con puntos de miles, por ejemplo $1.800.000."""

MAX_PREGUNTA = 500


class AsesorNoDisponible(Exception):
    """El modelo no respondió (sin cuota, sin red o error del servicio)."""


class ModeloIA(Protocol):
    def responder(self, resumen: dict, pregunta: str) -> str: ...


def _pesos(valor: int) -> str:
    return f"${valor:,}".replace(",", ".")


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")


class ModeloFalso:
    """Asesor por reglas: se usa en pruebas, en la demo y cuando no hay clave de Gemini."""

    PALABRAS_COMPRA = ("comprar", "compro", "gastar", "gasto en", "darme", "puedo", "antojo", "pedir")
    PALABRAS_DEUDA = ("deuda", "pagar primero", "pago primero", "abonar", "tarjeta", "credito")
    PALABRAS_CATEGORIA = ("en que gasto", "gasto mas", "donde se me va", "en que se me va")
    PALABRAS_TOPES = ("tope", "presupuesto", "como voy")

    def responder(self, resumen: dict, pregunta: str) -> str:
        p = _normalizar(pregunta)
        if any(k in p for k in self.PALABRAS_CATEGORIA):
            return self._categorias(resumen)
        if any(k in p for k in self.PALABRAS_TOPES):
            return self._topes(resumen)
        if any(k in p for k in self.PALABRAS_DEUDA):
            return self._deudas(resumen)
        if any(k in p for k in self.PALABRAS_COMPRA):
            return self._compra(resumen)
        return self._general(resumen)

    def _deuda_cara(self, resumen: dict) -> dict | None:
        deudas = resumen.get("deudas_en_orden_de_pago", [])
        return deudas[0] if deudas and deudas[0]["tasa_ea"] >= 20 else None

    def _compra(self, resumen: dict) -> str:
        cara = self._deuda_cara(resumen)
        excedidas = resumen.get("categorias_excedidas", [])
        balance = resumen.get("balance_mes", 0)
        if cara or excedidas or balance <= 0:
            razones = []
            if cara:
                razones.append(f"tienes una deuda al {cara['tasa_ea']}% E.A. con saldo de {_pesos(cara['saldo'])}")
            if excedidas:
                razones.append(f"ya te pasaste del tope en {', '.join(excedidas)}")
            if balance <= 0:
                razones.append("este mes ya gastaste más de lo que entró")
            accion = (
                f"Ese dinero abónalo a la deuda del {cara['tasa_ea']}%."
                if cara else "Guarda ese dinero y revisa tus topes."
            )
            motivo = " y ".join(razones)
            return (
                f"No. {motivo[0].upper()}{motivo[1:]}. "
                "Si quieres construir futuro, no puedes gastar así. "
                f"{accion}"
            )
        dias = max(resumen.get("dias_restantes_mes", 0), 1)
        maximo = balance // 5
        return (
            f"Sí, pero con cabeza: máximo {_pesos(maximo)}, porque te quedan {_pesos(balance)} "
            f"para {dias} días. Primero libertad, después antojos: si lo puedes esperar, espéralo."
        )

    def _deudas(self, resumen: dict) -> str:
        deudas = resumen.get("deudas_en_orden_de_pago", [])
        if not deudas:
            return "No tienes deudas registradas. Ahora toca blindarte: construye tu fondo de emergencia."
        primera = deudas[0]
        texto = (
            f"Primero la deuda al {primera['tasa_ea']}% E.A. (saldo {_pesos(primera['saldo'])}): "
            "es la que más intereses te cobra."
        )
        if len(deudas) > 1:
            texto += f" Después la del {deudas[1]['tasa_ea']}%."
        sin_interes = [x for x in deudas if x["tasa_ea"] == 0]
        if sin_interes:
            texto += " La que no cobra intereses va de última: no la adelantes."
        return texto + " Cada peso que gastas en gustos es un peso que le sigues pagando al banco."

    def _categorias(self, resumen: dict) -> str:
        por_categoria = resumen.get("gastos_por_categoria", {})
        if not por_categoria:
            return (
                "Este mes no tienes gastos registrados. "
                "Anota todo, hasta el tinto: lo que no se mide no se controla."
            )
        categoria, valor = next(iter(por_categoria.items()))
        total = resumen.get("gastos_mes") or 1
        return (
            f"Donde más gastas es en {categoria}: {_pesos(valor)}, el {round(valor * 100 / total)}% del mes. "
            f"Ahí está tu primera oportunidad de ahorro."
        )

    def _topes(self, resumen: dict) -> str:
        excedidas = resumen.get("categorias_excedidas", [])
        disponible = resumen.get("disponible_por_categoria", {})
        if excedidas:
            return (
                f"Te pasaste en {', '.join(excedidas)}. Lo que queda del mes, cero gastos en esas categorías. "
                "Un tope que no se respeta no es un tope, es un deseo."
            )
        holgura = ", ".join(f"{c} {_pesos(v)}" for c, v in disponible.items() if v > 0)
        return f"Vas dentro de tus topes. Te queda: {holgura}. Que te sobre no significa que te lo tengas que gastar."

    def _general(self, resumen: dict) -> str:
        return (
            f"Este mes llevas {_pesos(resumen.get('gastos_mes', 0))} en gastos y un balance de "
            f"{_pesos(resumen.get('balance_mes', 0))}. Pregúntame si puedes comprar algo, qué deuda pagar "
            "primero o cómo vas con tus topes."
        )


class GeminiModelo:
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"

    def __init__(self, api_key: str, modelo: str, timeout: float = 20.0) -> None:
        if not api_key:
            raise ValueError("Falta la API key de Gemini.")
        self._api_key = api_key
        self._modelo = modelo
        self._timeout = timeout

    def responder(self, resumen: dict, pregunta: str) -> str:
        cuerpo = {
            "system_instruction": {"parts": [{"text": PROMPT_SISTEMA}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"Resumen financiero:\n{json.dumps(resumen, ensure_ascii=False)}\n\n"
                                       f"Pregunta: {pregunta[:MAX_PREGUNTA]}"}],
                }
            ],
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": 400},
        }
        req = urllib.request.Request(  # noqa: S310 (URL fija https)
            self.URL.format(modelo=self._modelo),
            data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 (URL fija https)
                datos = json.loads(resp.read())
            return datos["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise AsesorNoDisponible(str(exc)) from exc
