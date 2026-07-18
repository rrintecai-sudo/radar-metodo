"""
method.py — EL MOTOR. Une todo en una señal con score de confluencia.

Este es el cerebro: para un activo y una estrategia, evalúa las condiciones del
método (zona + confluencias + vela + ruptura), les pone un puntaje de confluencia
(0-100) y, si supera el umbral, entrega una SEÑAL con:
  - dirección (call/put)
  - qué ingredientes se cumplieron y cuáles no (checklist vivo)
  - la opción sugerida (strike + vencimiento)
  - una explicación en español de POR QUÉ disparó

Principio de Cardona respetado en todo: la ZONA dice DÓNDE mirar; la RUPTURA dice
CUÁNDO entrar. Sin ruptura no hay entrada confirmada, por más que todo lo demás
coincida — eso se refleja en el score y en el estado de la señal.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from config import (CAIDA_FUERTE_MIN_PCT, CAIDA_NORMAL_MAX_PCT, CAIDA_NORMAL_MIN_PCT,
                    CERCANIA_MEDIA_PCT, ESTRATEGIAS, PESOS_CONFLUENCIA, UMBRAL_SENAL,
                    ZONA_CARA_PCT)
from engine import indicators as ind
from engine import zones as zn
from engine.options import sugerir_opcion

# Nueva York (verano). La regla de horarios de Cardona se mide en hora ET.
ET = timezone(timedelta(hours=-4))
# Regla de Cardona: nunca comprar calls antes de las 11am. Solo cuenta la señal
# cuando la vela horaria que la confirma YA CERRÓ a las 11 o después.
HORA_MINIMA_CALL = 11.0


def _vela_final_intradia(df: pd.DataFrame, intervalo: str, ahora: datetime) -> tuple[pd.DataFrame, float | None]:
    """
    Aplica dos reglas de Cardona sobre datos horarios:
      1) Vela FINAL: descarta la vela de la hora en curso (aún en formación).
      2) Devuelve la hora ET de CIERRE de la última vela ya cerrada (para el
         candado de las 11am). None si no es intradía o no se pudo calcular.
    En datos históricos (backtest) no recorta nada: todas las velas ya cerraron.
    """
    if intervalo not in ("1h", "30m") or len(df) < 3:
        return df, None
    try:
        dur = pd.Timedelta(hours=1) if intervalo == "1h" else pd.Timedelta(minutes=30)
        idx = df.index
        idx_et = idx.tz_convert(ET) if idx.tz is not None else idx.tz_localize(ET)
        cierre = idx_et + dur                             # yfinance etiqueta por inicio
        cerradas = cierre <= ahora                        # solo velas ya terminadas
        df2 = df[cerradas] if cerradas.any() else df
        ult_cierre = (idx_et[cerradas][-1] + pd.Timedelta(hours=1)) if cerradas.any() else None
        hora_cierre = (ult_cierre.hour + ult_cierre.minute / 60.0) if ult_cierre is not None else None
        return df2, hora_cierre
    except Exception:
        return df, None


def _nuevo_checklist() -> dict:
    return {k: {"ok": False, "detalle": ""} for k in PESOS_CONFLUENCIA}


def _score(checklist: dict) -> int:
    return sum(PESOS_CONFLUENCIA[k] for k, v in checklist.items() if v["ok"])


def _estado(score: int, chk: dict) -> str:
    """
    Estado según las DOS condiciones obligatorias del método (Cardona):
      ZONA (estar en piso/techo) + RUPTURA (la confirmación).
    Sin las dos, NUNCA es ENTRADA — por más score que sumen los refuerzos.
    Los refuerzos (promedio, soporte, vela) suben la calidad, no habilitan la entrada.
    """
    zona_ok = chk["zona"]["ok"]
    ruptura_ok = chk["ruptura"]["ok"]
    if zona_ok and ruptura_ok and score >= UMBRAL_SENAL:
        return "ENTRADA"        # las dos obligatorias + suficiente confluencia
    if zona_ok and score >= UMBRAL_SENAL - PESOS_CONFLUENCIA["ruptura"]:
        return "VIGILAR"        # en zona y armándose; falta la confirmación (ruptura)
    return "NADA"


# ---------------------------------------------------------------------------
# Estrategias basadas en promedio + ruptura de línea (MA40 / canal)
# ---------------------------------------------------------------------------
def _eval_ma40(df: pd.DataFrame) -> dict:
    """
    Estrategia MA40 (marco 1h): 20 sobre 40, caída toca el MA40, y una vela
    verde rompe la línea bajista -> CALL.
    """
    chk = _nuevo_checklist()
    dist = zn.distancia_a_medias(df)
    precio = float(df.iloc[-1]["Close"])

    # zona: cerca del MA40 y por debajo/encima de forma leíble
    if zn.tocando_media(df, 40):
        chk["zona"] = {"ok": True, "detalle": f"Precio tocando el MA40 ({dist.get('MA40', 0):+.2f}%)"}
    # media: alineación 20 sobre 40
    if ind.medias_alineadas(df, 20, 40):
        chk["media"] = {"ok": True, "detalle": "Promedios alineados 20 sobre 40"}
    # soporte: confluencia con MA100/200 cercano
    for p in (100, 200):
        if zn.tocando_media(df, p):
            chk["soporte"] = {"ok": True, "detalle": f"Confluencia con MA{p}"}
            break
    # vela de señal alcista
    sv = ind.senal_vela(df, "call")
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
    # ruptura de la línea bajista con vela verde
    lb = zn.linea_bajista(df)
    rup = {"hay": False, "texto": "Sin línea bajista clara"}
    if lb:
        rup = zn.ruptura(df, lb["valor_actual"], "call")
        if rup["hay"]:
            chk["ruptura"] = {"ok": True, "detalle": rup["texto"]}
    geo = {"linea_bajista": lb, "enfasis_medias": [20, 40], "ruptura": rup,
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"]}
    return {"direccion": "call", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


def _eval_canal(df: pd.DataFrame) -> dict:
    """
    Estrategia canal: canal bajista -> ruptura de techo con vela verde -> CALL.
    Espejo: canal alcista -> ruptura de piso con vela roja -> PUT.
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    canal = zn.detectar_canal(df, ventana=40)
    rup = {"hay": False, "texto": "Sin canal claro"}
    direccion = "call"

    if canal and canal["direccion"] == "bajista":
        direccion = "call"
        chk["zona"] = {"ok": True, "detalle": "Precio dentro de un canal bajista (zona para CALL)"}
        rup = zn.ruptura(df, canal["techo"], "call")
    elif canal and canal["direccion"] == "alcista":
        direccion = "put"
        chk["zona"] = {"ok": True, "detalle": "Precio dentro de un canal alcista (zona para PUT)"}
        rup = zn.ruptura(df, canal["piso"], "put")

    # confluencia con promedios
    for p in (40, 100, 200):
        if zn.tocando_media(df, p):
            chk["media"] = {"ok": True, "detalle": f"Confluencia con MA{p}"}
            break
    # vela de señal según dirección
    sv = ind.senal_vela(df, direccion)
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
    if rup["hay"]:
        chk["ruptura"] = {"ok": True, "detalle": rup["texto"]}
    geo = {"canal": canal, "enfasis_medias": [40, 100, 200], "ruptura": rup,
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"]}
    return {"direccion": direccion, "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


# ---------------------------------------------------------------------------
# Estrategias de caída (normal / fuerte) — reusan línea bajista + ruptura
# ---------------------------------------------------------------------------
def _eval_caida_normal(df: pd.DataFrame) -> dict:
    """
    Caída normal (1h): caída PEQUEÑA (<1.5%) que ni siquiera llega al MA40, en
    tendencia al alza, y una vela verde rompe la línea bajista -> CALL.
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    caida = zn.caida_reciente(df)
    d40 = zn.distancia_a_medias(df).get("MA40")
    # zona: caída pequeña que NO bajó hasta el MA40 (el precio sigue por encima)
    no_toco_40 = d40 is None or d40 > -CERCANIA_MEDIA_PCT
    if CAIDA_NORMAL_MIN_PCT <= caida <= CAIDA_NORMAL_MAX_PCT and no_toco_40:
        chk["zona"] = {"ok": True, "detalle": f"Caída normal de {caida:.1f}% (no llegó al MA40)"}
    # tendencia al alza (20 sobre 40) — el contexto ideal según Cardona
    if ind.medias_alineadas(df, 20, 40):
        chk["media"] = {"ok": True, "detalle": "Tendencia al alza (20 sobre 40)"}
    sv = ind.senal_vela(df, "call")
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
    # línea bajista CORTA: una caída normal es de pocas velas (Cardona la traza corta)
    lb = zn.linea_bajista(df, ventana=6)
    rup = {"hay": False, "texto": "Sin línea bajista clara"}
    if lb:
        rup = zn.ruptura(df, lb["valor_actual"], "call")
        if rup["hay"]:
            chk["ruptura"] = {"ok": True, "detalle": rup["texto"]}
    geo = {"linea_bajista": lb, "enfasis_medias": [20, 40], "ruptura": rup,
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"], "caida_pct": caida}
    return {"direccion": "call", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


def _eval_caida_fuerte(df: pd.DataFrame) -> dict:
    """
    Caída fuerte (1h): caída GRANDE (>1.5%) que pasa el MA40 (a veces toca MA100/200),
    y una vela verde rompe la línea bajista -> CALL. Rebote desde zona barata.
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    caida = zn.caida_reciente(df)
    d40 = zn.distancia_a_medias(df).get("MA40")
    # zona: caída fuerte que llegó/pasó el MA40 (o cerca de MA100/200)
    llego_fondo = zn.tocando_media(df, 40) or (d40 is not None and d40 < 0) \
        or zn.tocando_media(df, 100) or zn.tocando_media(df, 200)
    if caida >= CAIDA_FUERTE_MIN_PCT and llego_fondo:
        chk["zona"] = {"ok": True, "detalle": f"Caída fuerte de {caida:.1f}% (pasó el MA40)"}
    # confluencia con los promedios de fondo = zona barata
    for p in (40, 100, 200):
        if zn.tocando_media(df, p):
            chk["soporte"] = {"ok": True, "detalle": f"Confluencia con MA{p} (zona barata)"}
            break
    sv = ind.senal_vela(df, "call")
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
    lb = zn.linea_bajista(df)
    rup = {"hay": False, "texto": "Sin línea bajista clara"}
    if lb:
        rup = zn.ruptura(df, lb["valor_actual"], "call")
        if rup["hay"]:
            chk["ruptura"] = {"ok": True, "detalle": rup["texto"]}
    geo = {"linea_bajista": lb, "enfasis_medias": [40, 100, 200], "ruptura": rup,
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"], "caida_pct": caida}
    return {"direccion": "call", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


# ---------------------------------------------------------------------------
# Estrategia gap al alza (diario)
# ---------------------------------------------------------------------------
def _eval_gap(df: pd.DataFrame) -> dict:
    """
    Gap al alza (1d): la acción abrió con un salto por encima del máximo previo.
    Mientras el precio RESPETE el piso del gap y confirme con vela verde -> CALL.
    El gap suele anticipar la ruptura del canal (Cardona: 'primer gap al alza').
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    gap = zn.gap_al_alza(df)
    rup = {"hay": False, "texto": "Sin gap al alza reciente"}

    if gap:
        chk["zona"] = {"ok": True,
                       "detalle": f"Gap al alza de {gap['gap_pct']:.1f}% (piso del gap {gap['piso']:.2f})"}
        # confirmación: la última vela es verde y RESPETA el piso del gap (no lo cerró)
        v = df.iloc[-1]
        o, c, low = float(v["Open"]), float(v["Close"]), float(v["Low"])
        verde = c > o
        respeta = low >= gap["piso"] * (1 - 0.003) and c > gap["piso"]
        if verde and respeta:
            chk["ruptura"] = {"ok": True, "detalle": "Vela verde respeta el piso del gap (confirmación)"}
            rup = {"hay": True, "texto": "Vela verde respeta el piso del gap"}
    # confluencia con promedios de fondo
    for p in (40, 100, 200):
        if zn.tocando_media(df, p):
            chk["media"] = {"ok": True, "detalle": f"Confluencia con MA{p}"}
            break
    # soporte histórico cercano
    piso = zn.piso_fuerte_cercano(df)
    if piso:
        chk["soporte"] = {"ok": True, "detalle": f"Cerca de soporte histórico {piso['precio']:.2f}"}
    sv = ind.senal_vela(df, "call")
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
    geo = {"gap": gap, "enfasis_medias": [40, 100, 200], "ruptura": rup,
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"]}
    return {"direccion": "call", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


# ---------------------------------------------------------------------------
# CALLS del día 2: gap bajista al alza y primer gap al alza
# ---------------------------------------------------------------------------
def _dos_velas_verdes(df: pd.DataFrame, i0: int) -> bool:
    """
    Las DOS PRIMERAS velas de la sesión (desde i0) son verdes.
    Este es el corazón de los gaps: "abre abajo, verde, verde".
    """
    if i0 is None or len(df) < i0 + 2:
        return False
    a, b = df.iloc[i0], df.iloc[i0 + 1]
    return (float(a["Close"]) > float(a["Open"])) and (float(b["Close"]) > float(b["Open"]))


def _eval_gap_bajista_alza(df: pd.DataFrame) -> dict:
    """
    Gap bajista al alza (1h): ABRE ABAJO y las dos velas siguientes son verdes -> CALL.
    Excepción de Cardona: SÍ se puede dentro de un canal bajista. Además anuncia
    que la ruptura del techo viene cerca.
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    g = zn.gap_de_sesion(df)
    rup = {"hay": False, "texto": "Sin gap bajista"}
    if g and g["direccion"] == "abajo" and abs(g["gap_pct"]) >= 0.15:
        chk["zona"] = {"ok": True, "detalle": f"Abrió ABAJO {g['gap_pct']:.1f}% (gap bajista)"}
        if _dos_velas_verdes(df, g.get("idx_apertura")):
            chk["ruptura"] = {"ok": True, "detalle": "Las dos velas siguientes son VERDES (abre abajo, verde, verde)"}
            rup = {"hay": True, "texto": "Gap bajista al alza confirmado"}
    if ind.medias_alineadas(df, 20, 40):
        chk["media"] = {"ok": True, "detalle": "Tendencia al alza (20 sobre 40)"}
    for p in (40, 100, 200):
        if zn.tocando_media(df, p):
            chk["soporte"] = {"ok": True, "detalle": f"Confluencia con MA{p}"}
            break
    sv = ind.senal_vela(df, "call")
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
    geo = {"gap": g, "enfasis_medias": [20, 40], "ruptura": rup,
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"]}
    return {"direccion": "call", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


def _eval_primer_gap_alza(ticker: str, df: pd.DataFrame) -> dict:
    """
    Primer gap al alza (1d, se decide al CIERRE). La más exigente:
    viene de caída + zona de piso fuerte + salta arriba + PRIMERA VELA VERDE +
    respeta el piso del gap con el cuerpo + una vela verde sólida con ALTO VOLUMEN.
    """
    from config import VOLUMEN_ALTO, VOLUMEN_ALTO_DEFECTO
    chk = _nuevo_checklist()
    v = df.iloc[-1]
    precio = float(v["Close"])
    g = zn.gap_de_apertura(df)
    rup = {"hay": False, "texto": "No cumple el primer gap al alza"}

    piso = zn.piso_fuerte_cercano(df)
    cerca_fondo = piso is not None or zn.tocando_media(df, 100) or zn.tocando_media(df, 200)
    if piso:
        chk["soporte"] = {"ok": True, "detalle": f"Zona de piso fuerte {piso['precio']:.2f} ({piso['toques']} toques)"}
    elif cerca_fondo:
        chk["soporte"] = {"ok": True, "detalle": "En zona de piso (MA100/MA200)"}

    if g and g["direccion"] == "arriba" and cerca_fondo:
        chk["zona"] = {"ok": True,
                       "detalle": f"Salto al alza {g['gap_pct']:.1f}% desde zona de piso fuerte"}
        verde = float(v["Close"]) > float(v["Open"])
        # respeta el piso del gap CON EL CUERPO (la cola puede salirse)
        respeta = min(float(v["Open"]), float(v["Close"])) >= g["cierre_prev"]
        vol = float(v.get("Volume") or 0)
        vol_alto = vol >= VOLUMEN_ALTO.get(ticker.upper(), VOLUMEN_ALTO_DEFECTO)
        if vol_alto:
            chk["media"] = {"ok": True, "detalle": f"Volumen ALTO ({vol/1e6:.1f}M) — requisito exclusivo de esta estrategia"}
        if verde and respeta and vol_alto:
            chk["ruptura"] = {"ok": True,
                              "detalle": "Primera vela VERDE, respeta el piso del gap y hay volumen alto"}
            rup = {"hay": True, "texto": "Primer gap al alza confirmado"}
    sv = ind.senal_vela(df, "call")
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
    geo = {"gap": g, "piso": piso, "enfasis_medias": [100, 200], "ruptura": rup,
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"]}
    return {"direccion": "call", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


# ---------------------------------------------------------------------------
# Estrategias basadas en nivel fijo (piso fuerte / tres semanas)
# ---------------------------------------------------------------------------
def _eval_piso_fuerte(df: pd.DataFrame) -> dict:
    """
    Estrategia piso fuerte (marco 1d): precio en piso histórico fuerte + señal
    alcista -> CALL. La confirmación aquí es la vela de señal en el piso
    (martillo / verde sólida), que hace las veces de ruptura.
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    piso = zn.piso_fuerte_cercano(df)
    ruptura_ok = False

    if piso:
        chk["zona"] = {"ok": True, "detalle": f"En piso fuerte {piso['precio']:.2f} ({piso['toques']} toques)"}
        chk["soporte"] = {"ok": True, "detalle": f"Nivel histórico con {piso['toques']} rebotes previos"}
    # confluencia con MA100/200 (los pisos de fondo)
    for p in (100, 200):
        if zn.tocando_media(df, p):
            chk["media"] = {"ok": True, "detalle": f"Confluencia con MA{p}"}
            break
    # vela de señal alcista = la confirmación en el piso
    sv = ind.senal_vela(df, "call")
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
        if piso:  # vela alcista confirmando en el piso = confirmación válida
            chk["ruptura"] = {"ok": True, "detalle": "Vela alcista confirmando el rebote en el piso"}
            ruptura_ok = True
    geo = {"piso": piso, "enfasis_medias": [100, 200],
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"]}
    return {"direccion": "call", "checklist": chk, "ruptura_ok": ruptura_ok,
            "precio": precio, "geo": geo}


def _eval_tres_semanas(df: pd.DataFrame) -> dict:
    """
    Estrategia tres semanas (marco 1d): igual que piso fuerte en la lectura de
    zona, pero pensada para dejar madurar el movimiento con vencimiento largo.
    Aquí basta con estar en zona barata leíble (cerca de MA40/100/200) + señal.
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    dist = zn.distancia_a_medias(df)
    ruptura_ok = False

    # zona barata: por debajo o tocando los promedios de fondo
    en_zona = any(zn.tocando_media(df, p) for p in (40, 100, 200)) or \
        (dist.get("MA40", 99) < 0 and dist.get("MA40", 0) > -5)
    if en_zona:
        chk["zona"] = {"ok": True, "detalle": "Precio en zona barata leíble (cerca de los promedios)"}
    for p in (40, 100, 200):
        if zn.tocando_media(df, p):
            chk["media"] = {"ok": True, "detalle": f"Confluencia con MA{p}"}
            break
    piso = zn.piso_fuerte_cercano(df)
    if piso:
        chk["soporte"] = {"ok": True, "detalle": f"Cerca de soporte histórico {piso['precio']:.2f}"}
    sv = ind.senal_vela(df, "call")
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
        if en_zona:
            chk["ruptura"] = {"ok": True, "detalle": "Señal alcista en zona barata (entrada de horizonte largo)"}
            ruptura_ok = True
    geo = {"piso": piso, "enfasis_medias": [40, 100, 200],
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"]}
    return {"direccion": "call", "checklist": chk, "ruptura_ok": ruptura_ok,
            "precio": precio, "geo": geo}


# ---------------------------------------------------------------------------
# PUTS (día 2) — las cinco estrategias bajistas
# ---------------------------------------------------------------------------
def _vela_apertura(df: pd.DataFrame):
    """La vela de APERTURA (9:30-10:00) de la sesión más reciente. None si no está."""
    try:
        idx = df.index
        idx_et = idx.tz_convert(ET) if idx.tz is not None else idx.tz_localize(ET)
        es_apertura = [(t.hour == 9 and t.minute == 30) for t in idx_et]
        pos = [i for i, ok in enumerate(es_apertura) if ok]
        return df.iloc[pos[-1]] if pos else None
    except Exception:
        return None


def _eval_primera_vela_roja(df: pd.DataFrame) -> dict:
    """
    Primera vela roja de apertura (30m, 10:00 en punto). LA ÚNICA que se compra
    a las 10am: si la vela 9:30-10:00 cierra ROJA -> PUT.
    Contexto ideal: canal bajista o zona cara/techo.
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    v = _vela_apertura(df)
    if v is None:
        geo = {"enfasis_medias": [20, 40], "ruptura": {"hay": False, "texto": "Sin vela de apertura"},
               "vela_patron": None, "vela_ok": False}
        return {"direccion": "put", "checklist": chk, "ruptura_ok": False,
                "precio": precio, "geo": geo}
    roja = float(v["Close"]) < float(v["Open"])
    rup = {"hay": False, "texto": "La primera vela no es roja"}

    # zona: cara / techo / canal bajista (donde esta señal tiene poder)
    d40 = zn.distancia_a_medias(df).get("MA40")
    techo = zn.techo_fuerte_cercano(df)
    canal = zn.detectar_canal(df, ventana=40)
    en_zona = (techo is not None) or (d40 is not None and d40 > 0) or \
              (canal is not None and canal["direccion"] == "bajista")
    if en_zona:
        det = "Zona cara / de techo" if (techo or (d40 or 0) > 0) else "Dentro de canal bajista"
        chk["zona"] = {"ok": True, "detalle": f"{det} — donde la primera vela roja tiene poder"}
    if techo:
        chk["soporte"] = {"ok": True, "detalle": f"Techo histórico {techo['precio']:.2f} ({techo['toques']} toques)"}
    if ind.medias_alineadas(df, 40, 20):
        chk["media"] = {"ok": True, "detalle": "Tendencia bajista (40 sobre 20)"}
    if roja:
        chk["vela"] = {"ok": True, "detalle": "Primera vela del día ROJA (señal bajista)"}
        if en_zona:
            chk["ruptura"] = {"ok": True, "detalle": "Primera vela roja de apertura confirmada — compra a las 10:00"}
            rup = {"hay": True, "texto": "Primera vela roja de apertura"}
    geo = {"enfasis_medias": [20, 40], "ruptura": rup, "techo": techo,
           "vela_patron": "primera_roja" if roja else None, "vela_ok": roja}
    return {"direccion": "put", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


def _eval_ruptura_piso_gap(df: pd.DataFrame) -> dict:
    """
    Ruptura del piso del gap (1h, desde las 11). La primera vela verde marca el
    piso del gap; una vela ROJA final lo rompe -> PUT.
    Mejor: lejos del MA40 en tendencia alcista, o pegado al techo en canal bajista.
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    g = zn.gap_de_sesion(df)
    rup = {"hay": False, "texto": "Sin ruptura del piso del gap"}
    d40 = zn.distancia_a_medias(df).get("MA40")

    if g:
        piso = g["piso_gap"]
        chk["zona"] = {"ok": True, "detalle": f"Piso del gap en {piso:.2f} (trazado con la cola)"}
        r = zn.ruptura(df, piso, "put")   # vela roja sólida cierra por debajo
        if r["hay"]:
            chk["ruptura"] = {"ok": True, "detalle": "Vela ROJA final rompió el piso del gap"}
            rup = r
    # contextos que Cardona marcó como los mejores
    if d40 is not None and d40 > 3:
        chk["media"] = {"ok": True, "detalle": f"Lejos del MA40 ({d40:+.1f}%) — contexto ideal para este put"}
    canal = zn.detectar_canal(df, ventana=40)
    if canal and canal["direccion"] == "bajista":
        chk["soporte"] = {"ok": True, "detalle": "Dentro de canal bajista (mejor cuanto más cerca del techo)"}
    sv = ind.senal_vela(df, "put")
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
    geo = {"gap": g, "enfasis_medias": [20, 40], "ruptura": rup,
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"]}
    return {"direccion": "put", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


def _eval_modelo_4_pasos(df: pd.DataFrame) -> dict:
    """
    Modelo de los 4 pasos (1h): dentro de canal bajista + zona cara +
    una vela roja borra a la verde + rompe la línea de piso -> PUT.
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    canal = zn.detectar_canal(df, ventana=40)
    rup = {"hay": False, "texto": "Sin ruptura de la línea de piso"}

    # 1 y 2: dentro de canal bajista y en la parte ALTA (zona cara)
    if canal and canal["direccion"] == "bajista":
        alto = canal["techo"] - 0.35 * (canal["techo"] - canal["piso"])
        if precio >= alto:
            chk["zona"] = {"ok": True, "detalle": "Dentro de canal bajista y en la parte ALTA (zona cara)"}
        else:
            chk["soporte"] = {"ok": True, "detalle": "Dentro de canal bajista (aún no en la parte alta)"}
    # 3: verde-rojo (la roja borra a la verde)
    if len(df) >= 2:
        a, b = df.iloc[-2], df.iloc[-1]
        verde_prev = float(a["Close"]) > float(a["Open"])
        roja_hoy = float(b["Close"]) < float(b["Open"])
        borra = roja_hoy and float(b["Close"]) <= float(a["Open"])
        if verde_prev and borra:
            chk["vela"] = {"ok": True, "detalle": "Verde-rojo: la vela roja BORRA a la verde"}
    # 4: línea de piso rota por vela roja
    lp = zn.canal_alcista_corto(df, ventana=10)
    if lp:
        r = zn.ruptura(df, lp["valor_actual"], "put")
        if r["hay"]:
            chk["ruptura"] = {"ok": True, "detalle": "Vela ROJA rompió la línea de piso de la subida"}
            rup = r
    if ind.medias_alineadas(df, 40, 20):
        chk["media"] = {"ok": True, "detalle": "Tendencia bajista (40 sobre 20)"}
    geo = {"canal": canal, "linea_piso": lp, "enfasis_medias": [20, 40], "ruptura": rup,
           "vela_patron": None, "vela_ok": chk["vela"]["ok"]}
    return {"direccion": "put", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


def _eval_hanger_diario(df: pd.DataFrame) -> dict:
    """
    Hanger en diario (1d, se decide 3:57pm): vela diaria con cola larga ARRIBA y
    cuerpo pequeño (el COLOR da igual) en zona cara -> PUT.
    """
    chk = _nuevo_checklist()
    v = df.iloc[-1]
    precio = float(v["Close"])
    hg = zn.es_hanger(v)
    rup = {"hay": False, "texto": "La vela de hoy no es un hanger"}

    d40 = zn.distancia_a_medias(df).get("MA40")
    techo = zn.techo_fuerte_cercano(df)
    cara = (d40 is not None and d40 > 0) or techo is not None
    if cara:
        det = f"Zona cara ({d40:+.1f}% sobre el MA40)" if d40 is not None else "Zona de techo"
        chk["zona"] = {"ok": True, "detalle": f"{det} — espacio para caer"}
    if techo:
        chk["soporte"] = {"ok": True, "detalle": f"Techo histórico {techo['precio']:.2f} ({techo['toques']} toques)"}
    if ind.medias_alineadas(df, 200, 100):
        chk["media"] = {"ok": True, "detalle": "Diario bajista (200 sobre 100)"}
    if hg["hay"]:
        chk["vela"] = {"ok": True,
                       "detalle": f"HANGER diario (cuerpo {hg['cuerpo_pct']}% del rango, cola arriba ×{hg['cola_sup_x']}) — el color da igual"}
        if cara:
            chk["ruptura"] = {"ok": True, "detalle": "Hanger confirmado en zona cara — compra 3:57pm"}
            rup = {"hay": True, "texto": "Hanger en diario"}
    geo = {"enfasis_medias": [100, 200], "ruptura": rup, "techo": techo,
           "vela_patron": "hanger" if hg["hay"] else None, "vela_ok": hg["hay"]}
    return {"direccion": "put", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


def _eval_techo_fuerte(df: pd.DataFrame) -> dict:
    """
    Techo fuerte (1d): el espejo exacto del piso fuerte.
    Diario MA200 sobre MA100 + techo tocado varias veces; una vela roja sólida
    rompe la línea de piso -> PUT. La de mayor magnitud (15-22x según Cardona).
    """
    chk = _nuevo_checklist()
    precio = float(df.iloc[-1]["Close"])
    techo = zn.techo_fuerte_cercano(df)
    rup = {"hay": False, "texto": "Sin ruptura de la línea de piso"}

    if techo:
        chk["zona"] = {"ok": True, "detalle": f"En techo fuerte {techo['precio']:.2f} ({techo['toques']} rechazos)"}
        chk["soporte"] = {"ok": True, "detalle": f"Nivel histórico con {techo['toques']} caídas previas"}
    if ind.medias_alineadas(df, 200, 100):
        chk["media"] = {"ok": True, "detalle": "MA200 sobre MA100 en diario (contexto de techo)"}
    sv = ind.senal_vela(df, "put")
    if sv["hay"]:
        chk["vela"] = {"ok": True, "detalle": sv["texto"]}
    lp = zn.canal_alcista_corto(df, ventana=10)
    if lp and techo:
        r = zn.ruptura(df, lp["valor_actual"], "put")
        if r["hay"]:
            chk["ruptura"] = {"ok": True, "detalle": "Vela ROJA sólida rompió la línea de piso en el techo"}
            rup = r
    geo = {"techo": techo, "linea_piso": lp, "enfasis_medias": [100, 200], "ruptura": rup,
           "vela_patron": sv.get("patron"), "vela_ok": sv["hay"]}
    return {"direccion": "put", "checklist": chk, "ruptura_ok": rup["hay"],
            "precio": precio, "geo": geo}


_EVALUADORES = {
    "ma40": _eval_ma40,
    "canal": _eval_canal,
    "caida_normal": _eval_caida_normal,
    "caida_fuerte": _eval_caida_fuerte,
    "gap": _eval_gap,
    "piso_fuerte": _eval_piso_fuerte,
    "tres_semanas": _eval_tres_semanas,
    # día 2 — calls
    "gap_bajista_alza": _eval_gap_bajista_alza,
    "primer_gap_alza": None,          # necesita el ticker (volumen) -> caso especial
    # día 2 — puts
    "primera_vela_roja": _eval_primera_vela_roja,
    "ruptura_piso_gap": _eval_ruptura_piso_gap,
    "modelo_4_pasos": _eval_modelo_4_pasos,
    "hanger_diario": _eval_hanger_diario,
    "techo_fuerte": _eval_techo_fuerte,
}


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------
def evaluar(ticker: str, df: pd.DataFrame, estrategia: str) -> dict:
    """
    Evalúa UN activo con UNA estrategia. Devuelve la señal completa con score,
    estado, checklist, opción sugerida y explicación.

    `df` debe traer ya las columnas de promedios móviles (usa preparar()).
    """
    intervalo = ESTRATEGIAS[estrategia].get("intervalo", "1d")
    ahora = datetime.now(ET)
    # Reglas de horario de Cardona (solo intradía): vela final + candado 11am.
    df, hora_cierre = _vela_final_intradia(df, intervalo, ahora)

    ev = _EVALUADORES[estrategia]
    r = _eval_primer_gap_alza(ticker, df) if ev is None else ev(df)
    chk = r["checklist"]
    score = _score(chk)
    estado = _estado(score, chk)

    # CANDADO DE HORARIO POR ESTRATEGIA (Cardona día 1 + las 3 excepciones del día 2):
    #   "desde_11" -> la vela que confirma debe cerrar a las 11:00 ET o después
    #   "vela_10"  -> primera vela roja de apertura: se compra a las 10:00 en punto
    #   "cierre"   -> primer gap al alza / hanger diario: se deciden ~3:57-3:59pm
    aviso_horario = None
    horario = ESTRATEGIAS[estrategia].get("horario", "desde_11")
    hora_ahora = ahora.hour + ahora.minute / 60.0
    # Los candados de RELOJ solo tienen sentido si la señal es de HOY y está viva.
    # En backtest (velas históricas) o fin de semana no aplican: esa vela ya cerró.
    try:
        es_hoy = df.index[-1].date() == ahora.date()
    except Exception:
        es_hoy = False
    en_mercado = es_hoy and ahora.weekday() < 5 and 9.5 <= hora_ahora <= 16.25

    if estado == "ENTRADA":
        if horario == "desde_11" and intervalo in ("1h", "30m") \
                and hora_cierre is not None and hora_cierre < HORA_MINIMA_CALL:
            estado = "VIGILAR"
            aviso_horario = ("⏳ Antes de las 11am ET — regla de Cardona: espera. "
                             "La vela de las 10 y la primera vela verde engañan.")
        elif horario == "vela_10" and en_mercado and hora_ahora < 10.0:
            estado = "VIGILAR"
            aviso_horario = "⏳ Espera a que cierre la primera vela (10:00 en punto) para comprar el PUT."
        elif horario == "vela_10" and en_mercado and hora_ahora > 11.0:
            estado = "VIGILAR"
            aviso_horario = ("⌛ El momento de esta estrategia era a las 10:00 y ya pasó. "
                             "Déjala para mañana; no la persigas.")
        elif horario == "cierre" and en_mercado and hora_ahora < 15.9:
            estado = "VIGILAR"
            aviso_horario = ("🔔 Esta estrategia se decide AL CIERRE (3:57-3:59pm). "
                             "La vela del día todavía se está formando.")

    # REGLA DE ZONA CARA: no comprar calls muy por encima del promedio (Cardona:
    # "no comprar lejos del promedio, tras una gran subida — esperar la corrección").
    # NO aplica al gap: un gap al alza ES un salto por encima del promedio a propósito
    # (es estrategia de impulso, no de comprar-en-la-caída).
    ES_GAP = ("gap", "gap_bajista_alza", "primer_gap_alza")
    if r["direccion"] == "call" and estado == "ENTRADA" and estrategia not in ES_GAP:
        d40 = zn.distancia_a_medias(df).get("MA40")
        if d40 is not None and d40 > ZONA_CARA_PCT:
            estado = "VIGILAR"
            aviso_horario = (f"📈 Zona cara: el precio está {d40:+.1f}% sobre el MA40 — "
                             "Cardona: no comprar lejos del promedio; espera la corrección.")

    ult = df.iloc[-1]
    hoy = df.index[-1]

    opcion = sugerir_opcion(r["precio"], r["direccion"], estrategia, hoy=hoy)

    # explicación en español: qué se cumplió
    cumplidos = [v["detalle"] for v in chk.values() if v["ok"]]
    faltan = [k for k, v in chk.items() if not v["ok"]]

    return {
        "ticker": ticker,
        "estrategia": estrategia,
        "estrategia_nombre": ESTRATEGIAS[estrategia]["nombre"],
        "marco": ESTRATEGIAS[estrategia]["marco"],
        "direccion": r["direccion"],
        "precio": r["precio"],
        "fecha": hoy.isoformat(),
        "score": score,
        "estado": estado,          # ENTRADA / VIGILAR / NADA
        "checklist": chk,
        "cumplidos": cumplidos,
        "faltan": faltan,
        "opcion": opcion,
        "aviso_horario": aviso_horario,   # regla 11am de Cardona (None si no aplica)
        "geo": r.get("geo", {}),   # geometría que usó el motor, para dibujarla
    }


def preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega los promedios móviles necesarios antes de evaluar."""
    return ind.agregar_medias(df)


def escanear_completo(estrategias: list[str] | None = None) -> list[dict]:
    """
    Escaneo de alto nivel: baja los datos en el marco correcto de cada estrategia
    (diario para piso fuerte / tres semanas; horario para MA40 / canal) y devuelve
    todas las señales ordenadas por fuerza. Es la función que usa el dashboard.
    """
    from engine import data
    estrategias = estrategias or list(ESTRATEGIAS.keys())
    # agrupamos las estrategias por el intervalo de datos que necesitan
    por_intervalo: dict[str, list[str]] = {}
    for est in estrategias:
        iv = ESTRATEGIAS[est].get("intervalo", "1d")
        por_intervalo.setdefault(iv, []).append(est)

    señales: list[dict] = []
    for intervalo, ests in por_intervalo.items():
        datos = data.obtener_todos(intervalo)
        señales += escanear(datos, estrategias=ests)

    # REGLA DE CARDONA (global, día en vivo): el día de la reunión de la FED (FOMC)
    # NO se invierte. Degradamos toda ENTRADA a VIGILAR con el aviso.
    try:
        from engine import calendar as cal
        fed = cal.es_dia_fed()
    except Exception:
        fed = None
    if fed:
        for s in señales:
            if s["estado"] == "ENTRADA":
                s["estado"] = "VIGILAR"
                s["aviso_horario"] = (f"🏛️ Día de la FED ({fed['titulo']}) — "
                                      "Cardona: hoy NO se invierte (el mercado suele caer mañana)")

    orden = {"ENTRADA": 0, "VIGILAR": 1, "NADA": 2}
    señales.sort(key=lambda s: (orden[s["estado"]], -s["score"]))
    return señales


def escanear(datos: dict[str, pd.DataFrame], estrategias: list[str] | None = None) -> list[dict]:
    """
    Corre TODAS las estrategias sobre TODOS los activos y devuelve las señales
    ordenadas de más fuerte (mayor score, estado ENTRADA primero) a más débil.
    """
    estrategias = estrategias or list(ESTRATEGIAS.keys())
    orden_estado = {"ENTRADA": 0, "VIGILAR": 1, "NADA": 2}
    señales: list[dict] = []
    for ticker, df in datos.items():
        if df is None or len(df) < 210:  # necesitamos histórico para MA200
            continue
        dfp = preparar(df)
        for est in estrategias:
            try:
                señales.append(evaluar(ticker, dfp, est))
            except Exception as e:
                print(f"[method] {ticker}/{est} falló: {e}")
    señales.sort(key=lambda s: (orden_estado[s["estado"]], -s["score"]))
    return señales
