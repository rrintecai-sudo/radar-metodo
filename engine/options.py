"""
options.py — Qué opción comprar (strike y vencimiento).

Traduce la señal técnica a una recomendación concreta de contrato, siguiendo las
reglas del método:
  - CALL -> strike un poco POR ENCIMA del precio (OTM).
  - PUT  -> strike un poco POR DEBAJO del precio (OTM).
  - Vencimiento corto: entre 1 y 3 semanas.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from config import (STRIKE_OTM_PCT, VENCIMIENTO_DIAS_MAX, VENCIMIENTO_DIAS_MIN)


def sugerir_opcion(precio: float, direccion: str, estrategia: str,
                   hoy: pd.Timestamp | None = None) -> dict:
    """
    Devuelve strike OTM y ventana de vencimiento recomendada.

    `hoy` se pasa explícito (no usamos el reloj interno) para que el resultado
    sea reproducible en backtests.
    """
    if direccion == "call":
        strike = round(precio * (1 + STRIKE_OTM_PCT / 100), 2)
        tipo = "CALL"
    else:
        strike = round(precio * (1 - STRIKE_OTM_PCT / 100), 2)
        tipo = "PUT"

    # Las estrategias rápidas usan el extremo corto del rango; las pausadas el largo.
    dias = {
        "ma40": VENCIMIENTO_DIAS_MIN,
        "canal": VENCIMIENTO_DIAS_MIN + 5,
        "piso_fuerte": VENCIMIENTO_DIAS_MIN + 7,
        "tres_semanas": VENCIMIENTO_DIAS_MAX,
    }.get(estrategia, VENCIMIENTO_DIAS_MAX)

    venc = None
    if hoy is not None:
        venc = (hoy + timedelta(days=dias)).date().isoformat()

    return {
        "tipo": tipo,
        "strike": strike,
        "otm_pct": STRIKE_OTM_PCT,
        "dias_vencimiento": dias,
        "vencimiento_aprox": venc,
        "nota": f"{tipo} strike {strike} (~{STRIKE_OTM_PCT}% OTM), vence en ~{dias} días",
    }
