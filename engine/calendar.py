"""
calendar.py — El "cuándo": calendario económico (eventos que mueven el mercado).

Cardona: los eventos (inflación/CPI, decisiones de la Fed, empleo) mueven el
mercado. Sirven de dos formas:
  - CATALIZADOR: si tu señal técnica ya apunta en una dirección y viene un evento
    que puede empujar en esa dirección, refuerza.
  - PRECAUCIÓN: ante un evento grande e impredecible, muchas veces lo más sabio es
    NO entrar y esperar a que pase (puede mover en contra de lo que uno cree).

Fuente: calendario semanal gratuito de faireconomy (Forex Factory). Filtramos
eventos de EE.UU. (USD) de alto impacto, que son los que mueven SPY/QQQ/GLD.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ET = timezone(timedelta(hours=-4))  # hora de Nueva York (verano). Coincide con Venezuela.
URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache" / "calendar.json"
FRESCURA = 6 * 3600  # refrescar cada 6 horas

# Cuántas horas antes de un evento grande consideramos que hay "riesgo inminente".
# 36 h para que un dato de mañana temprano (CPI, Fed, empleo) se avise HOY: como
# el método aguanta 1-2 días, entrarías cargando la posición hacia ese evento.
HORAS_RIESGO = 36


def _descargar() -> list[dict]:
    if CACHE.exists() and (time.time() - CACHE.stat().st_mtime) < FRESCURA:
        try:
            return json.loads(CACHE.read_text())
        except Exception:
            pass
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    data = json.load(urllib.request.urlopen(req, timeout=20))
    try:
        CACHE.write_text(json.dumps(data))
    except Exception:
        pass
    return data


def eventos(solo_alto: bool = True, pais: str = "USD") -> list[dict]:
    """Lista de eventos de la semana (US, alto impacto por defecto), ordenados por fecha."""
    try:
        crudos = _descargar()
    except Exception:
        return []
    out = []
    for e in crudos:
        if pais and e.get("country") != pais:
            continue
        if solo_alto and e.get("impact") != "High":
            continue
        try:
            cuando = datetime.fromisoformat(e["date"])
        except Exception:
            continue
        out.append({
            "cuando": cuando,
            "titulo": e.get("title", ""),
            "impacto": e.get("impact", ""),
            "forecast": e.get("forecast", ""),
            "previous": e.get("previous", ""),
        })
    return sorted(out, key=lambda x: x["cuando"])


def _ahora() -> datetime:
    return datetime.now(ET)


def proximos(horas: int = 24 * 7) -> list[dict]:
    """Eventos de alto impacto que aún no han pasado, dentro de las próximas `horas`."""
    ahora = _ahora()
    lim = ahora + timedelta(hours=horas)
    return [e for e in eventos() if ahora <= e["cuando"] <= lim]


def riesgo_inminente(horas: int = HORAS_RIESGO) -> dict | None:
    """
    ¿Viene un evento grande dentro de las próximas `horas`? (motivo para NO entrar).
    Devuelve el evento más cercano y cuántas horas faltan, o None.
    """
    prox = proximos(horas)
    if not prox:
        return None
    e = prox[0]
    faltan = (e["cuando"] - _ahora()).total_seconds() / 3600
    return {"titulo": e["titulo"], "cuando": e["cuando"], "horas": faltan,
            "forecast": e.get("forecast", ""), "previous": e.get("previous", "")}


def es_dia_fed(ahora: datetime | None = None) -> dict | None:
    """
    ¿HOY es día de reunión de la Reserva Federal (FOMC)? Regla de Cardona: ese día
    NO se invierte (7-8 de 10 veces el mercado cae al día siguiente). Devuelve el
    evento si hoy hay una reunión/decisión de la Fed, o None.
    """
    ahora = ahora or _ahora()
    hoy = ahora.date()
    claves = ("fomc", "federal funds", "fed interest", "fed rate", "interest rate decision")
    for e in eventos():
        if e["cuando"].date() == hoy and any(k in e["titulo"].lower() for k in claves):
            return {"titulo": e["titulo"], "cuando": e["cuando"]}
    return None


def contexto_senal() -> dict:
    """Contexto de calendario para mostrar junto a una señal."""
    r = riesgo_inminente()
    if r is None:
        return {"nivel": "despejado",
                "texto": "Sin eventos de alto impacto en las próximas 24 h. Camino despejado por el lado del calendario."}
    horas = r["horas"]
    cuando = r["cuando"].strftime("%a %d, %H:%M")
    if horas <= 3:
        nivel = "peligro"
    else:
        nivel = "precaucion"
    det = f" (previo {r['previous']}, se espera {r['forecast']})" if r["forecast"] else ""
    return {"nivel": nivel,
            "titulo": r["titulo"], "cuando": cuando, "horas": horas,
            "texto": f"⚠️ Evento grande próximo: **{r['titulo']}** el {cuando} "
                     f"(faltan ~{horas:.0f} h){det}. Puede mover el mercado en cualquier dirección. "
                     "Cardona muchas veces esperaría a que pase antes de entrar."}
