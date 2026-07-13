"""
earnings.py — El riesgo de empresa única: la fecha de resultados.

Los ETF (SPY, QQQ, GLD...) no tienen este riesgo — por eso Cardona empieza ahí.
Pero las acciones individuales SÍ: el día de resultados (earnings) la acción puede
pegar un salto enorme en cualquier dirección, sin importar la señal técnica.

Regla: si los earnings caen DENTRO de la ventana en que tendrías la opción abierta,
es un riesgo grande. El motor lo avisa para que decidas con los ojos abiertos
(muchos operadores prefieren NO cargar opciones sobre earnings).
"""
from __future__ import annotations

from datetime import date

import yfinance as yf


def proxima_fecha(ticker: str) -> date | None:
    """Devuelve la próxima fecha de resultados (futura) del ticker, o None."""
    try:
        cal = yf.Ticker(ticker).calendar
        fechas = None
        if isinstance(cal, dict):
            fechas = cal.get("Earnings Date")
        if not fechas:
            return None
        if not isinstance(fechas, (list, tuple)):
            fechas = [fechas]
        hoy = date.today()
        futuras = [f for f in fechas if hasattr(f, "year") and f >= hoy]
        return min(futuras) if futuras else None
    except Exception:
        return None


def contexto(ticker: str, dias_ventana: int, es_accion: bool = True) -> dict:
    """
    ¿Hay earnings dentro de la ventana en que tendrías la opción abierta?
    `dias_ventana` = días hasta el vencimiento de la opción sugerida.
    """
    if not es_accion:
        return {"nivel": "na", "texto": ""}  # los ETF no reportan earnings
    f = proxima_fecha(ticker)
    if f is None:
        return {"nivel": "sin_dato", "texto": "Sin fecha de earnings disponible."}
    dias = (f - date.today()).days
    fstr = f.strftime("%d-%b-%Y")
    if 0 <= dias <= dias_ventana:
        return {"nivel": "riesgo", "fecha": f, "dias": dias,
                "texto": f"⚠️ **Earnings el {fstr}** (en {dias} días) — CAE DENTRO de la vida de la opción. "
                         "La acción puede saltar fuerte en cualquier dirección ese día, sin importar la técnica. "
                         "Muchos evitan cargar opciones sobre earnings."}
    return {"nivel": "ok", "fecha": f, "dias": dias,
            "texto": f"Próximos earnings: {fstr} (en {dias} días) — fuera de la ventana de la opción. OK."}
