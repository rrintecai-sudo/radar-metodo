"""
indicators.py — Los ingredientes técnicos del método.

Dos cosas:
  1) Promedios móviles (los niveles DINÁMICOS que caminan con el precio).
  2) Patrones de vela de señal (martillo, hanger, vela sólida verde/roja).

Todo se calcula sobre un DataFrame OHLC como el que entrega engine/data.py.
"""
from __future__ import annotations

import pandas as pd

from config import MEDIAS, VELA


# ---------------------------------------------------------------------------
# Promedios móviles
# ---------------------------------------------------------------------------
def agregar_medias(df: pd.DataFrame, periodos: list[int] | None = None) -> pd.DataFrame:
    """Agrega columnas MA20, MA40, MA100, MA200 (las que pida `periodos`)."""
    periodos = periodos or MEDIAS
    df = df.copy()
    for p in periodos:
        df[f"MA{p}"] = df["Close"].rolling(p).mean()
    return df


def medias_alineadas(df: pd.DataFrame, corta: int = 20, larga: int = 40) -> bool:
    """
    ¿Está el promedio corto POR ENCIMA del largo? (requisito 1 de la estrategia MA40:
    'los promedios deben estar alineados 20 sobre 40').
    """
    c, l = f"MA{corta}", f"MA{larga}"
    if c not in df or l not in df:
        df = agregar_medias(df, [corta, larga])
    ult = df.iloc[-1]
    return bool(ult[c] > ult[l]) if pd.notna(ult[c]) and pd.notna(ult[l]) else False


# ---------------------------------------------------------------------------
# Anatomía de una vela
# ---------------------------------------------------------------------------
def _partes(v: pd.Series) -> dict:
    """Descompone una vela en cuerpo, mecha superior e inferior."""
    o, h, l, c = float(v["Open"]), float(v["High"]), float(v["Low"]), float(v["Close"])
    cuerpo = abs(c - o)
    rango = h - l
    mecha_sup = h - max(o, c)
    mecha_inf = min(o, c) - l
    return {
        "open": o, "high": h, "low": l, "close": c,
        "cuerpo": cuerpo, "rango": rango,
        "mecha_sup": mecha_sup, "mecha_inf": mecha_inf,
        "verde": c > o, "roja": c < o,
    }


def es_martillo(v: pd.Series) -> bool:
    """
    Martillo (ALCISTA): mecha inferior larga, poco cuerpo, casi nada de mecha
    superior. "Trata de caer y sube." Solo tiene poder en zona de piso.
    """
    p = _partes(v)
    if p["cuerpo"] <= 0:
        return False
    return (p["mecha_inf"] >= VELA["martillo_mecha_inf_min"] * p["cuerpo"]
            and p["mecha_sup"] <= VELA["martillo_mecha_sup_max"] * p["cuerpo"])


def es_hanger(v: pd.Series) -> bool:
    """
    Hanger / martillo invertido (BAJISTA): imagen espejo del martillo. Mecha
    superior larga. "Trata de subir, cae." Solo tiene poder en zona de techo.
    """
    p = _partes(v)
    if p["cuerpo"] <= 0:
        return False
    return (p["mecha_sup"] >= VELA["hanger_mecha_sup_min"] * p["cuerpo"]
            and p["mecha_inf"] <= VELA["hanger_mecha_inf_max"] * p["cuerpo"])


def es_verde_solida(v: pd.Series) -> bool:
    """Vela verde grande, cuerpo dominante, colas cortas. Fuerza compradora."""
    p = _partes(v)
    if p["rango"] <= 0:
        return False
    return p["verde"] and (p["cuerpo"] >= VELA["solida_cuerpo_min"] * p["rango"])


def es_roja_solida(v: pd.Series) -> bool:
    """Vela roja grande, cuerpo dominante. Debilidad / fuerza vendedora."""
    p = _partes(v)
    if p["rango"] <= 0:
        return False
    return p["roja"] and (p["cuerpo"] >= VELA["solida_cuerpo_min"] * p["rango"])


def senal_vela(df: pd.DataFrame, direccion: str) -> dict:
    """
    Evalúa la ÚLTIMA vela buscando la señal de la dirección pedida.
      direccion="call" -> señales alcistas (martillo, verde sólida)
      direccion="put"  -> señales bajistas (hanger, roja sólida)
    Devuelve qué patrón encontró (si alguno).
    """
    v = df.iloc[-1]
    if direccion == "call":
        if es_martillo(v):
            return {"hay": True, "patron": "martillo", "texto": "Martillo (alcista) en la última vela"}
        if es_verde_solida(v):
            return {"hay": True, "patron": "verde_solida", "texto": "Vela verde sólida (fuerza compradora)"}
    else:  # put
        if es_hanger(v):
            return {"hay": True, "patron": "hanger", "texto": "Hanger / martillo invertido (bajista)"}
        if es_roja_solida(v):
            return {"hay": True, "patron": "roja_solida", "texto": "Vela roja sólida (debilidad)"}
    return {"hay": False, "patron": None, "texto": "Sin vela de señal clara"}
