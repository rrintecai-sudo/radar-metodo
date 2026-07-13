"""
screener.py — "Oportunidades del día": escanea TODO el universo y las rankea.

Amplía el motor de los 5 ETFs a las acciones individuales, y ordena las
oportunidades por una mezcla equilibrada de:
  1) MÉTODO      — cuántas condiciones de Cardona cumple (0 a 5)
  2) CONFIABILIDAD — probabilidad histórica de que se moviera a favor
  3) BENEFICIO    — cuánto se mueve TÍPICAMENTE a favor (aquí TSLA/NVDA le ganan a GLD)

El "beneficio grande" del método sale de la BENEFICIO: los activos que se mueven
5-10% dan opciones que suben mucho más que los que se mueven 2-3%.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import ESTRATEGIAS, UNIVERSO_TICKERS
from engine import backtest, data, method

# Estrategias diarias (las que usa el escaneo amplio; solo necesitan datos 1d).
ESTRATEGIAS_DIARIAS = ["piso_fuerte", "tres_semanas"]
# Cuántas señales activas backtesteamos a fondo (para no saturar).
TOPE_BACKTEST = 18

# Pesos del score de oportunidad (equilibrado, con un pelín más a beneficio).
W_BENEFICIO = 0.40
W_CONFIABILIDAD = 0.35
W_METODO = 0.25


def confianza(n: int) -> dict:
    """Qué tan confiable es la estadística según el tamaño de la muestra."""
    if n < 12:
        return {"emoji": "🔴", "label": "muestra baja", "nivel": "baja"}
    if n < 25:
        return {"emoji": "🟡", "label": "muestra media", "nivel": "media"}
    if n < 50:
        return {"emoji": "🟢", "label": "muestra buena", "nivel": "buena"}
    return {"emoji": "🟢", "label": "muestra sólida", "nivel": "solida"}


def confiab_ajustada(win_rate: float, n: int, k: int = 12) -> float:
    """
    Confiabilidad AJUSTADA por el tamaño de muestra: acerca los porcentajes de
    muestra pequeña hacia el 50% (moneda al aire), porque no son de fiar todavía.
    Un 93% de 15 casos baja a ~74%; un 93% de 100 casos casi no se mueve (~88%).
    """
    wins = win_rate / 100 * n
    return (wins + 0.5 * k) / (n + k) * 100


def volatilidad(df: pd.DataFrame) -> dict:
    """Mide qué tan 'explosivo' es un activo (cuánto se mueve al día)."""
    r = df["Close"].pct_change().dropna() * 100
    reciente = r[-60:] if len(r) >= 60 else r
    absr = reciente.abs()
    return {
        "mov_diario_mediana": float(absr.median()) if len(absr) else 0.0,
        "mov_diario_prom": float(absr.mean()) if len(absr) else 0.0,
        "pct_dias_1pct": float((absr >= 1.0).mean() * 100) if len(absr) else 0.0,
    }


def _oportunidad(n_cond: int, beneficio_pct: float, confiabilidad_pct: float, estado: str) -> float:
    """Score 0-100 que combina método + confiabilidad + beneficio."""
    metodo = n_cond / 5 * 100
    # 8% de movimiento a favor ya es excelente -> normalizamos a esa escala
    beneficio = min(beneficio_pct / 8.0 * 100, 100)
    score = W_BENEFICIO * beneficio + W_CONFIABILIDAD * confiabilidad_pct + W_METODO * metodo
    if estado == "ENTRADA":
        score += 12  # bono: lista para hoy
    return round(min(score, 100), 1)


def escanear_universo(tickers: list[str] | None = None,
                      estrategias: list[str] | None = None,
                      con_backtest: bool = True,
                      incluir_horario: bool = False) -> list[dict]:
    """
    Escanea el universo y devuelve las oportunidades ACTIVAS (ENTRADA / VIGILAR)
    rankeadas por score de oportunidad.

    incluir_horario=True agrega las estrategias intradía (MA40, canal), que
    generan entradas DURANTE el día. Baja datos horarios además de los diarios.
    """
    from config import UNIVERSO
    tickers = tickers or UNIVERSO_TICKERS
    if estrategias is None:
        estrategias = list(ESTRATEGIAS_DIARIAS)
        if incluir_horario:
            estrategias += ["ma40", "canal"]

    # agrupamos las estrategias por el marco de datos que necesitan
    por_intervalo: dict[str, list[str]] = {}
    for est in estrategias:
        iv = ESTRATEGIAS[est]["intervalo"]
        por_intervalo.setdefault(iv, []).append(est)

    señales = []
    datos_diario = None
    for iv, ests in por_intervalo.items():
        datos = data.descargar_lote(tickers, iv)
        if iv == "1d":
            datos_diario = datos
        señales += method.escanear(datos, estrategias=ests)
    if datos_diario is None:
        datos_diario = data.descargar_lote(tickers, "1d")

    # nos quedamos con las activas y les pegamos volatilidad (siempre desde 1d)
    activas = []
    for s in señales:
        if s["estado"] == "NADA":
            continue
        df = datos_diario.get(s["ticker"])
        vol = volatilidad(df) if df is not None else {"mov_diario_mediana": 0}
        s["volatilidad"] = vol
        s["n_cond"] = sum(1 for v in s["checklist"].values() if v["ok"])
        s["indice"] = UNIVERSO.get(s["ticker"], {}).get("indice", "")
        activas.append(s)

    # preseleccionamos por (estado, condiciones, volatilidad) para backtestear el top
    orden_estado = {"ENTRADA": 0, "VIGILAR": 1}
    activas.sort(key=lambda s: (orden_estado[s["estado"]], -s["n_cond"],
                                -s["volatilidad"]["mov_diario_mediana"]))

    for i, s in enumerate(activas):
        h = None
        if con_backtest and i < TOPE_BACKTEST:
            h = backtest.historial_senal(s["ticker"], s["estrategia"])
        if h and not h.get("sin_datos"):
            s["historial"] = h
            beneficio = h["mfe_mediana"]
            confiab = h["principal"]["win_rate"]
            n_m = h["n"]
            s["riesgo_pct"] = round(h["mae_mediana"], 1)          # en contra típico (negativo)
            s["beneficio_1d"] = round(h.get("fav_1d_mediana", 0), 1)  # a favor en 1 día
            s["mfe_max"] = round(h.get("mfe_max", beneficio), 1)      # mejor caso histórico
            s["mfe_p90"] = round(h.get("mfe_p90", beneficio), 1)      # buen caso
        else:
            s["historial"] = None
            # proxy cuando no hay backtest: beneficio ~ 2 días de movimiento típico
            beneficio = s["volatilidad"]["mov_diario_mediana"] * 2
            confiab = 55.0  # neutro
            n_m = 0
            s["riesgo_pct"] = round(-s["volatilidad"]["mov_diario_mediana"] * 1.5, 1)
            s["beneficio_1d"] = round(s["volatilidad"]["mov_diario_mediana"], 1)
            s["mfe_max"] = round(beneficio * 2, 1)
            s["mfe_p90"] = round(beneficio * 1.5, 1)
        # confiabilidad AJUSTADA por tamaño de muestra (para el ranking)
        confiab_aj = confiab_ajustada(confiab, n_m) if n_m else confiab
        s["n_muestra"] = n_m
        s["confianza"] = confianza(n_m)
        s["beneficio_pct"] = round(beneficio, 1)
        s["confiabilidad_pct"] = round(confiab, 0)            # observada (para mostrar)
        s["confiab_ajustada"] = round(confiab_aj, 0)          # ajustada por muestra
        s["ratio_br"] = round(beneficio / abs(s["riesgo_pct"]), 1) if s["riesgo_pct"] else None
        # el ranking usa la confiabilidad AJUSTADA: una muestra chica pesa menos
        s["oportunidad"] = _oportunidad(s["n_cond"], beneficio, confiab_aj, s["estado"])

    activas.sort(key=lambda s: -s["oportunidad"])
    return activas
