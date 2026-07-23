"""
ranking.py — El RANKING DE EDGE: proactivo, no reactivo.

En vez de esperar a que una clase nombre un activo, aquí le preguntamos a TODA la
data de una vez: de cada estrategia sobre cada activo, ¿cuál tiene edge de verdad,
medido sobre años de historia? Esto es lo que Alejandro no puede hacer a ojo.

'Edge' = cuánto se mueve A FAVOR típicamente vs. EN CONTRA, ponderado por el % de
acierto histórico. Es un proxy del movimiento del ACTIVO (la opción lo multiplica),
no una promesa de retorno. Muestra chica (< 12) = poco de fiar; se marca aparte.
"""
from __future__ import annotations

from config import ESTRATEGIAS, UNIVERSO_TICKERS

# Universo enfocado: líquido y lo que más se opera. Si alguno no está, se ignora.
TICKERS_RANKING = [
    "SPY", "QQQ", "GLD", "SLV", "AAPL", "META", "NVDA", "TSLA", "AMZN", "GOOGL",
    "MSFT", "TSM", "AVGO", "MU", "AMD", "XOM", "CVX", "USO", "NFLX", "PLTR",
    "NOW", "CRM",
]

MUESTRA_CONFIABLE = 12   # a partir de aquí el % es de fiar


def escanear_edge(tickers: list[str] | None = None, min_n: int = 6) -> list[dict]:
    """
    Recorre cada (activo × estrategia), mide el edge histórico y devuelve la lista
    ordenada de mayor a menor edge. Cada fila trae lo necesario para mostrar y para
    saber qué tan confiable es (tamaño de muestra).
    """
    from engine import backtest

    tks = tickers or [t for t in TICKERS_RANKING if t in UNIVERSO_TICKERS] or UNIVERSO_TICKERS[:22]
    filas: list[dict] = []
    for tk in tks:
        for est in ESTRATEGIAS:
            try:
                h = backtest.historial_senal(tk, est)
                if not h or h.get("sin_datos"):
                    continue
                n = h.get("n", 0)
                if n < min_n:
                    continue
                wr = h["principal"]["win_rate"]
                mfe = h.get("mfe_mediana", 0)        # a favor típico
                mfe_p90 = h.get("mfe_p90", mfe)      # buen caso
                mae = abs(h.get("mae_mediana", 0))   # en contra típico
                edge = round((wr / 100) * mfe - (1 - wr / 100) * mae, 2)
                filas.append({
                    "ticker": tk, "estrategia": est,
                    "nombre": ESTRATEGIAS[est].get("nombre", est),
                    "direccion": "PUT" if est in (
                        "primera_vela_roja", "ruptura_piso_gap", "modelo_4_pasos",
                        "hanger_diario", "techo_fuerte") else "CALL",
                    "n": n, "acierto": round(wr), "favor": round(mfe, 1),
                    "p90": round(mfe_p90, 1), "contra": round(mae, 1),
                    "edge": edge, "confiable": n >= MUESTRA_CONFIABLE,
                })
            except Exception:
                continue
    filas.sort(key=lambda f: -f["edge"])
    return filas
