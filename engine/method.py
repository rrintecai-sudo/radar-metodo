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

from config import (ESTRATEGIAS, PESOS_CONFLUENCIA, UMBRAL_SENAL)
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
    if intervalo != "1h" or len(df) < 3:
        return df, None
    try:
        idx = df.index
        idx_et = idx.tz_convert(ET) if idx.tz is not None else idx.tz_localize(ET)
        cierre = idx_et + pd.Timedelta(hours=1)          # yfinance etiqueta por inicio
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


_EVALUADORES = {
    "ma40": _eval_ma40,
    "canal": _eval_canal,
    "piso_fuerte": _eval_piso_fuerte,
    "tres_semanas": _eval_tres_semanas,
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

    r = _EVALUADORES[estrategia](df)
    chk = r["checklist"]
    score = _score(chk)
    estado = _estado(score, chk)

    # CANDADO DE HORARIO: nunca una ENTRADA de call antes de las 11am ET.
    # Si la vela que confirma cerró antes de las 11, se degrada a VIGILAR.
    aviso_horario = None
    if intervalo == "1h" and estado == "ENTRADA" and hora_cierre is not None \
            and hora_cierre < HORA_MINIMA_CALL:
        estado = "VIGILAR"
        aviso_horario = ("⏳ Antes de las 11am ET — regla de Cardona: espera. "
                         "La vela de las 10 y la primera vela verde engañan.")

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
