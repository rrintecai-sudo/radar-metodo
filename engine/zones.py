"""
zones.py — DÓNDE está el precio y CUÁNDO rompe la línea.

Aquí vive lo que en el método hace "el ojo de Cardona":
  - distancia a cada promedio móvil (¿está tocando el de 40? ¿el de 200?)
  - soportes/resistencias históricos (los niveles FIJOS que él traza a mano)
  - canales (techo y piso paralelos)
  - la RUPTURA de la línea con la vela del color correcto (la confirmación real)

Nada de esto adivina el futuro: mide lo que ya pasó y detecta cuándo se cumple
una condición del método.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import (CAIDA_VENTANA, CERCANIA_MEDIA_PCT, GAP_LOOKBACK, GAP_MIN_PCT,
                    PIVOTE_VENTANA, SR_CERCANIA_PCT, SR_MIN_TOQUES, SR_TOLERANCIA_PCT)


# ---------------------------------------------------------------------------
# Distancia a los promedios móviles (niveles dinámicos)
# ---------------------------------------------------------------------------
def distancia_a_medias(df: pd.DataFrame) -> dict[str, float]:
    """
    % de distancia del cierre actual a cada promedio (MA20, MA40, ...).
    Negativo = el precio está POR DEBAJO del promedio (zona barata para ese MA).
    Positivo = por encima (zona cara).
    """
    ult = df.iloc[-1]
    cierre = float(ult["Close"])
    out: dict[str, float] = {}
    for col in [c for c in df.columns if c.startswith("MA")]:
        val = ult[col]
        if pd.notna(val) and val:
            out[col] = (cierre - float(val)) / float(val) * 100.0
    return out


def tocando_media(df: pd.DataFrame, periodo: int) -> bool:
    """¿El precio está 'tocando' (a ±CERCANIA_MEDIA_PCT) el promedio dado?"""
    d = distancia_a_medias(df).get(f"MA{periodo}")
    return d is not None and abs(d) <= CERCANIA_MEDIA_PCT


def caida_reciente(df: pd.DataFrame, ventana: int = CAIDA_VENTANA) -> float:
    """
    % de caída reciente = del máximo del tramo al mínimo POSTERIOR a ese máximo.
    Sirve para clasificar la caída (normal <1.5% vs fuerte >1.5%) como hace Cardona.
    Devuelve 0 si no hay caída (el mínimo va antes del máximo = venía subiendo).
    """
    if len(df) < ventana + 1:
        ventana = max(2, len(df) - 1)
    seg = df.iloc[-ventana:]
    highs = seg["High"].values
    lows = seg["Low"].values
    i_max = int(highs.argmax())
    pico = float(highs[i_max])
    post_low = float(lows[i_max:].min())   # mínimo desde el pico hacia adelante
    if pico <= 0:
        return 0.0
    return max(0.0, (pico - post_low) / pico * 100.0)


def gap_al_alza(df: pd.DataFrame, lookback: int = GAP_LOOKBACK,
                gap_min_pct: float = GAP_MIN_PCT) -> dict | None:
    """
    Detecta un gap al alza reciente: la apertura de una vela salta por encima del
    MÁXIMO de la vela anterior (queda un hueco). El 'piso del gap' = ese máximo previo.
    Devuelve el gap más reciente dentro de `lookback` velas, o None.
    """
    n = len(df)
    if n < 3:
        return None
    lim = max(1, n - lookback)
    for i in range(n - 1, lim - 1, -1):
        op = float(df.iloc[i]["Open"])
        prev_high = float(df.iloc[i - 1]["High"])
        prev_close = float(df.iloc[i - 1]["Close"])
        if prev_close <= 0:
            continue
        gap_pct = (op - prev_high) / prev_close * 100.0
        if gap_pct >= gap_min_pct:
            return {"idx": i, "piso": prev_high, "gap_pct": gap_pct,
                    "apertura": op, "cierre_previo": prev_close,
                    "velas_desde": (n - 1) - i}
    return None


# ---------------------------------------------------------------------------
# Soportes y resistencias históricos (niveles fijos que Cardona traza a mano)
# ---------------------------------------------------------------------------
def _pivotes(df: pd.DataFrame, ventana: int) -> tuple[list[float], list[float]]:
    """Encuentra máximos y mínimos locales (pivotes) del precio."""
    highs, lows = df["High"].values, df["Low"].values
    n = len(df)
    piv_alto, piv_bajo = [], []
    for i in range(ventana, n - ventana):
        vent_h = highs[i - ventana:i + ventana + 1]
        vent_l = lows[i - ventana:i + ventana + 1]
        if highs[i] == vent_h.max():
            piv_alto.append(float(highs[i]))
        if lows[i] == vent_l.min():
            piv_bajo.append(float(lows[i]))
    return piv_bajo, piv_alto


def _agrupar_niveles(valores: list[float], tol_pct: float, min_toques: int) -> list[dict]:
    """
    Agrupa pivotes cercanos en niveles de soporte/resistencia.
    Un nivel es "fuerte" si el precio rebotó ahí varias veces (min_toques).
    """
    if not valores:
        return []
    vals = sorted(valores)
    grupos: list[list[float]] = [[vals[0]]]
    for v in vals[1:]:
        if abs(v - grupos[-1][-1]) / grupos[-1][-1] * 100 <= tol_pct:
            grupos[-1].append(v)
        else:
            grupos.append([v])
    niveles = []
    for g in grupos:
        if len(g) >= min_toques:
            niveles.append({"precio": float(np.mean(g)), "toques": len(g)})
    return sorted(niveles, key=lambda x: x["toques"], reverse=True)


def soportes_resistencias(df: pd.DataFrame) -> dict[str, list[dict]]:
    """Devuelve niveles de soporte (pisos) y resistencia (techos) históricos."""
    piv_bajo, piv_alto = _pivotes(df, PIVOTE_VENTANA)
    return {
        "soportes": _agrupar_niveles(piv_bajo, SR_TOLERANCIA_PCT, SR_MIN_TOQUES),
        "resistencias": _agrupar_niveles(piv_alto, SR_TOLERANCIA_PCT, SR_MIN_TOQUES),
    }


def piso_fuerte_cercano(df: pd.DataFrame) -> dict | None:
    """
    ¿El precio está SOBRE un piso histórico fuerte? (estrategia piso fuerte).
    Devuelve el nivel y cuántas veces rebotó ahí, o None.
    """
    cierre = float(df.iloc[-1]["Close"])
    soportes = soportes_resistencias(df)["soportes"]
    for s in soportes:
        dist = (cierre - s["precio"]) / s["precio"] * 100
        # "en" el piso: entre justo encima y un poco por debajo del nivel.
        if -SR_CERCANIA_PCT <= dist <= SR_CERCANIA_PCT * 2:
            return {"precio": s["precio"], "toques": s["toques"], "distancia_pct": dist}
    return None


# ---------------------------------------------------------------------------
# Canales y ruptura de línea (la confirmación)
# ---------------------------------------------------------------------------
def _recta(x: list[int], y: list[float]) -> tuple[float, float]:
    """Ajusta una recta y=m*x+b por mínimos cuadrados. Devuelve (m, b)."""
    m, b = np.polyfit(x, y, 1)
    return float(m), float(b)


def detectar_canal(df: pd.DataFrame, ventana: int = 40) -> dict | None:
    """
    Ajusta una línea de techo (sobre los máximos) y una de piso (sobre los
    mínimos) en las últimas `ventana` velas. Si ambas tienen pendiente parecida,
    es un canal. Devuelve la dirección y los valores actuales de cada línea.
    """
    if len(df) < ventana + 2:
        return None
    seg = df.iloc[-ventana:]
    x = list(range(len(seg)))
    m_techo, b_techo = _recta(x, list(seg["High"].values))
    m_piso, b_piso = _recta(x, list(seg["Low"].values))
    xf = len(seg)  # posición de la vela actual sobre la recta
    techo_ahora = m_techo * (xf - 1) + b_techo
    piso_ahora = m_piso * (xf - 1) + b_piso
    pendiente = (m_techo + m_piso) / 2
    ancho = techo_ahora - piso_ahora
    if ancho <= 0:
        return None
    # dirección por la pendiente media, relativa al ancho del canal
    if pendiente < -0.02 * ancho:
        direccion = "bajista"
    elif pendiente > 0.02 * ancho:
        direccion = "alcista"
    else:
        direccion = "lateral"
    return {
        "direccion": direccion,
        "techo": float(techo_ahora),
        "piso": float(piso_ahora),
        "m_techo": m_techo, "b_techo": b_techo,
        "m_piso": m_piso, "b_piso": b_piso,
        "ventana": ventana,
    }


def linea_bajista(df: pd.DataFrame, ventana: int = 12) -> dict | None:
    """
    Traza la 'línea de techo siguiendo las velas rojas de la caída' (estrategia
    MA40 / canal). Ajusta una recta descendente sobre los máximos recientes.
    """
    if len(df) < ventana + 1:
        return None
    seg = df.iloc[-ventana:]
    x = list(range(len(seg)))
    m, b = _recta(x, list(seg["High"].values))
    if m >= 0:
        return None  # no es una línea bajista si no baja
    return {"m": m, "b": b, "ventana": ventana, "valor_actual": m * (len(seg) - 1) + b}


def es_hanger(vela) -> dict:
    """
    ¿Esta vela es un HANGER? (cola larga ARRIBA, cuerpo pequeño).
    Cardona (día 2): "no interesa el color del hanger; puede ser verde o rojo".
    Señal BAJISTA cuando aparece en zona cara.
    """
    o, c = float(vela["Open"]), float(vela["Close"])
    h, l = float(vela["High"]), float(vela["Low"])
    rango = h - l
    if rango <= 0:
        return {"hay": False}
    cuerpo = abs(c - o)
    cola_sup = h - max(o, c)
    cola_inf = min(o, c) - l
    # Cardona: cola larga arriba, cuerpo pequeño. Umbrales prácticos:
    hay = (cuerpo <= 0.45 * rango            # cuerpo pequeño respecto al rango
           and cola_sup >= 1.5 * cuerpo      # cola de arriba claramente larga
           and cola_sup >= 0.45 * rango      # y domina la vela
           and cola_inf <= 1.0 * cuerpo)     # poca cola abajo (no es martillo)
    return {"hay": bool(hay), "cuerpo_pct": round(cuerpo / rango * 100),
            "cola_sup_x": round(cola_sup / cuerpo, 1) if cuerpo else 99}


def gap_de_apertura(df: pd.DataFrame) -> dict | None:
    """
    Gap del día actual respecto al cierre anterior, y el 'piso del gap'.
    Cardona: el piso del gap se traza teniendo en cuenta la COLA de la primera vela.
    Devuelve: direccion ('arriba'/'abajo'), piso del gap y tamaño.
    """
    if len(df) < 2:
        return None
    hoy, ayer = df.iloc[-1], df.iloc[-2]
    ap, cierre_prev = float(hoy["Open"]), float(ayer["Close"])
    if cierre_prev <= 0:
        return None
    pct = (ap - cierre_prev) / cierre_prev * 100
    return {"direccion": "arriba" if ap > cierre_prev else "abajo",
            "gap_pct": round(pct, 2), "apertura": ap, "cierre_prev": cierre_prev,
            "piso_gap": float(hoy["Low"])}   # el piso se traza con la cola


def gap_de_sesion(df: pd.DataFrame) -> dict | None:
    """
    Gap de APERTURA de la sesión, para datos INTRADÍA (1h/30m).
    Compara la PRIMERA vela del día con el CIERRE del día anterior — que es donde
    de verdad existe el gap (entre hora y hora dentro del día no hay gap).
    El 'piso del gap' se traza con la COLA de esa primera vela (regla de Cardona).
    """
    if len(df) < 3:
        return None
    try:
        fechas = [t.date() for t in df.index]
    except Exception:
        return None
    hoy = fechas[-1]
    pos_hoy = [i for i, f in enumerate(fechas) if f == hoy]
    if not pos_hoy or pos_hoy[0] == 0:
        return None
    i0 = pos_hoy[0]
    # CRÍTICO: las estrategias de gap miran las DOS primeras velas de la sesión.
    # Si solo hay una (la de apertura, aún formándose), no hay nada que confirmar.
    if len(pos_hoy) < 2:
        return None
    ap = float(df.iloc[i0]["Open"])
    cierre_prev = float(df.iloc[i0 - 1]["Close"])
    if cierre_prev <= 0:
        return None
    pct = (ap - cierre_prev) / cierre_prev * 100
    return {"direccion": "arriba" if ap > cierre_prev else "abajo",
            "gap_pct": round(pct, 2), "apertura": ap, "cierre_prev": cierre_prev,
            "piso_gap": float(df.iloc[i0]["Low"]), "idx_apertura": i0,
            "velas_sesion": len(pos_hoy)}


def canal_alcista_corto(df: pd.DataFrame, ventana: int = 12) -> dict | None:
    """
    Línea de PISO que sigue una subida (para PUT: cuando una vela roja la rompe).
    Es el espejo de linea_bajista: ajusta una recta ascendente sobre los mínimos.
    """
    if len(df) < ventana + 1:
        return None
    seg = df.iloc[-ventana:]
    x = list(range(len(seg)))
    m, b = _recta(x, list(seg["Low"].values))
    if m <= 0:
        return None  # no es una línea de piso ascendente
    return {"m": m, "b": b, "ventana": ventana, "valor_actual": m * (len(seg) - 1) + b}


def techo_fuerte_cercano(df: pd.DataFrame) -> dict | None:
    """
    ¿El precio está BAJO un techo histórico fuerte? (espejo de piso_fuerte_cercano).
    Nivel donde el precio se aproximó varias veces y siempre cayó.
    """
    cierre = float(df.iloc[-1]["Close"])
    resistencias = soportes_resistencias(df)["resistencias"]
    for r in resistencias:
        dist = (r["precio"] - cierre) / r["precio"] * 100
        if -SR_CERCANIA_PCT <= dist <= SR_CERCANIA_PCT * 2:
            return {"precio": r["precio"], "toques": r["toques"], "distancia_pct": dist}
    return None


def ruptura(df: pd.DataFrame, linea_valor: float, direccion: str) -> dict:
    """
    ¿La ÚLTIMA vela rompió la línea con el color correcto?
      direccion="call": una vela VERDE cierra POR ENCIMA de la línea de techo.
      direccion="put":  una vela ROJA cierra POR DEBAJO de la línea de piso.
    Esta es la confirmación que Cardona exige: "que rompa la línea".
    """
    v = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else v
    o, c = float(v["Open"]), float(v["Close"])
    h, l = float(v["High"]), float(v["Low"])
    prev_c = float(prev["Close"])
    # Regla de Cardona: la vela de ruptura debe ser SÓLIDA (cuerpo mayor que las colas),
    # no un hanger ni un doji con cola larga. Exigimos cuerpo >= la mitad del rango.
    rango = h - l
    cuerpo = abs(c - o)
    solida = rango <= 0 or (cuerpo / rango) >= 0.5
    if direccion == "call":
        rompio = c > linea_valor and prev_c <= linea_valor and c > o and solida  # verde sólida cruza arriba
    else:
        rompio = c < linea_valor and prev_c >= linea_valor and c < o and solida  # roja sólida cruza abajo
    return {
        "hay": bool(rompio),
        "cierre": c,
        "linea": float(linea_valor),
        "texto": ("Vela verde SÓLIDA rompió la línea de techo hacia arriba" if direccion == "call"
                  else "Vela roja SÓLIDA rompió la línea de piso hacia abajo") if rompio
                 else "Todavía sin ruptura sólida de la línea",
    }
