"""
backtest.py — El "turbo": mide la probabilidad HISTÓRICA de una señal.

La idea, en simple: recorremos TODO el histórico del activo, encontramos cada vez
que esta misma señal (misma estrategia) se disparó en el pasado, y miramos qué
pasó DESPUÉS: ¿el precio se movió a favor?, ¿cuánto?, ¿en cuántos días?

Esto NO adivina el futuro. Lee el pasado y cuenta. Responde dos preguntas que un
humano no puede calcular de memoria:
  1) De las veces que apareció esta señal, ¿cuántas se movieron a mi favor?
  2) ¿Cuánto tiempo suele tardar en darse el movimiento?

Nota honesta: medimos el movimiento del ACTIVO (el oro, el índice), no el precio
exacto de la opción (no existe histórico gratuito de primas). Como la opción se
apalanca sobre el activo, el movimiento del activo es el que manda. Por eso también
reportamos el TIEMPO: si el movimiento tarda mucho, el decaimiento de la opción se
come parte de la ganancia — y eso hay que saberlo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import ESTRATEGIAS
from engine import data
from engine import method

# Umbrales de movimiento del activo que nos interesan (%), alineados con los
# escenarios que se muestran en la ficha (1, 2, 3, 5, 8%).
TARGETS = [1.0, 2.0, 3.0, 5.0, 8.0]
# Umbral principal para el "medidor" (un movimiento sólido, no el mínimo).
TARGET_PRINCIPAL = 1.0


def _ventana_dias(estrategia: str) -> int:
    """Cuántos días hacia adelante miramos = el vencimiento típico de la estrategia."""
    from engine.options import sugerir_opcion
    return sugerir_opcion(100, "call", estrategia)["dias_vencimiento"]


def historial_senal(ticker: str, estrategia: str, max_ocurrencias: int = 400) -> dict:
    """
    Recorre el histórico y mide qué pasó cada vez que esta señal se disparó.
    Devuelve estadísticas listas para mostrar.
    """
    intervalo = ESTRATEGIAS[estrategia]["intervalo"]
    df = method.preparar(data.obtener(ticker, intervalo))
    ventana = _ventana_dias(estrategia)

    if len(df) < 220:
        return {"sin_datos": True, "motivo": "poco histórico"}

    ocurrencias = []
    i = 210  # necesitamos histórico para el MA200
    ultima = -999
    while i < len(df) - 1:
        sub = df.iloc[: i + 1]
        try:
            s = method.evaluar(ticker, sub, estrategia)
        except Exception:
            i += 1
            continue
        # una "ocurrencia" es cuando la señal llegó a ENTRADA (se dio la confirmación)
        if s["estado"] == "ENTRADA" and (i - ultima) > 2:
            ultima = i
            t0 = df.index[i]
            entrada = float(df.iloc[i]["Close"])
            direccion = s["direccion"]
            # ventana hacia adelante, por fecha (sirve para diario y horario)
            fwd = df[(df.index > t0) & (df.index <= t0 + pd.Timedelta(days=ventana))]
            if len(fwd):
                if direccion == "call":
                    fav = (fwd["High"] - entrada) / entrada * 100      # excursión a favor
                    adv = (fwd["Low"] - entrada) / entrada * 100       # en contra (negativa)
                else:
                    fav = (entrada - fwd["Low"]) / entrada * 100
                    adv = (entrada - fwd["High"]) / entrada * 100
                mfe = float(fav.max())    # máximo movimiento a favor
                mae = float(adv.min())    # peor movimiento en contra
                # máximo movimiento a favor DENTRO de 1, 2, 3, 5 días
                # (para calcular "prob de ×N dentro de D días" -> los "logros posibles")
                mfe_por_dia = {}
                for d in (1, 2, 3, 5):
                    fwd_d = fwd[fwd.index <= t0 + pd.Timedelta(days=d)]
                    mfe_por_dia[d] = float(fav.loc[fwd_d.index].max()) if len(fwd_d) else 0.0
                fav_1d = mfe_por_dia[1]
                adv_1d = float(adv.loc[fwd[fwd.index <= t0 + pd.Timedelta(days=1)].index].min()) \
                    if len(fwd[fwd.index <= t0 + pd.Timedelta(days=1)]) else 0.0
                # tiempo hasta alcanzar cada target
                dias_target = {}
                for t in TARGETS:
                    alcanza = fwd[fav >= t]
                    dias_target[t] = ((alcanza.index[0] - t0).total_seconds() / 86400
                                      if len(alcanza) else None)
                ocurrencias.append({"mfe": mfe, "mae": mae, "fav_1d": fav_1d, "adv_1d": adv_1d,
                                    "mfe_por_dia": mfe_por_dia, "dias_target": dias_target})
        i += 1
        if len(ocurrencias) >= max_ocurrencias:
            break

    n = len(ocurrencias)
    if n == 0:
        return {"sin_datos": True, "motivo": "esta señal no apareció en el histórico disponible",
                "ventana_dias": ventana}

    resumen_targets = {}
    for t in TARGETS:
        gana = [o for o in ocurrencias if o["mfe"] >= t]
        dias = [o["dias_target"][t] for o in gana if o["dias_target"][t] is not None]
        resumen_targets[t] = {
            "win_rate": len(gana) / n * 100,
            "dias_mediana": float(np.median(dias)) if dias else None,
            "dias_p25": float(np.percentile(dias, 25)) if dias else None,
            "dias_p75": float(np.percentile(dias, 75)) if dias else None,
        }

    mfes = [o["mfe"] for o in ocurrencias]
    maes = [o["mae"] for o in ocurrencias]
    return {
        "sin_datos": False,
        "ticker": ticker,
        "estrategia": estrategia,
        "n": n,
        "ventana_dias": ventana,
        "targets": resumen_targets,
        "mfe_mediana": float(np.median(mfes)),   # a favor típico (en toda la ventana)
        "mfe_p90": float(np.percentile(mfes, 90)),   # buen caso
        "mfe_max": float(np.max(mfes)),              # mejor caso histórico
        "mae_mediana": float(np.median(maes)),   # en contra típico (riesgo)
        "fav_1d_mediana": float(np.median([o["fav_1d"] for o in ocurrencias])),   # a favor en 1 día
        "adv_1d_mediana": float(np.median([o["adv_1d"] for o in ocurrencias])),   # en contra en 1 día
        # movimiento a favor por cada ventana de días (para "prob de ×N en D días")
        "mfe_dias": {d: [o["mfe_por_dia"][d] for o in ocurrencias] for d in (1, 2, 3, 5)},
        "principal": resumen_targets[TARGET_PRINCIPAL],
        "target_principal": TARGET_PRINCIPAL,
    }
