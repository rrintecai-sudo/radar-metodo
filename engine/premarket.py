"""
premarket.py — El contexto EN VIVO (lo que pasa antes/durante la sesión).

El método técnico lee el gráfico (pasado). Pero antes de entrar hay que mirar
lo que está pasando AHORA: el pre-market. Cardona lo usa para confirmar o abstenerse.

Este módulo trae el precio de pre-market (o el precio en vivo si el mercado está
abierto) y dice si CONFIRMA o CONTRADICE la dirección de la señal:
  - señal CALL (alcista): pre-market en verde confirma; en rojo contradice.
  - señal PUT (bajista):  pre-market en rojo confirma; en verde contradice.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import yfinance as yf

# Movimiento mínimo (%) para no llamar "señal" al ruido.
UMBRAL_NEUTRO = 0.15

ET = timezone(timedelta(hours=-4))  # Nueva York (verano). Coincide con Venezuela.


def estado_sesion(ahora: datetime | None = None) -> str:
    """
    En qué momento de la sesión estamos, según la hora (sin llamar a la red):
      'pre'     = 4:00–9:30 (pre-market)
      'abierto' = 9:30–16:00 (sesión regular)
      'post'    = 16:00–20:00 (after-hours)
      'cerrado' = resto / fin de semana
    """
    ahora = ahora or datetime.now(ET)
    if ahora.weekday() >= 5:  # sábado/domingo
        return "cerrado"
    t = ahora.time()
    if time(4, 0) <= t < time(9, 30):
        return "pre"
    if time(9, 30) <= t < time(16, 0):
        return "abierto"
    if time(16, 0) <= t < time(20, 0):
        return "post"
    return "cerrado"


def hay_actividad(ahora: datetime | None = None) -> bool:
    """¿Vale la pena escanear? (pre-market o mercado abierto)."""
    return estado_sesion(ahora) in ("pre", "abierto")

ESTADOS = {
    "PRE": "pre-market (antes de abrir)",
    "REGULAR": "mercado abierto",
    "POST": "after-hours (cerró)",
    "CLOSED": "mercado cerrado",
    "PREPRE": "madrugada (pre-pre-market)",
    "POSTPOST": "noche (post cierre)",
}


def contexto(ticker: str) -> dict:
    """Devuelve precio y variación en vivo (pre-market o sesión) para un ticker."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        estado = info.get("marketState", "CLOSED")
        prev = info.get("regularMarketPreviousClose") or info.get("previousClose")

        if estado == "PRE" and info.get("preMarketPrice"):
            precio = info["preMarketPrice"]
            cambio = info.get("preMarketChangePercent")
        elif estado == "POST" and info.get("postMarketPrice"):
            precio = info["postMarketPrice"]
            cambio = info.get("postMarketChangePercent")
        else:  # REGULAR o cerrado: usar el precio de mercado
            precio = info.get("regularMarketPrice") or info.get("currentPrice")
            cambio = info.get("regularMarketChangePercent")

        if cambio is None and precio and prev:
            cambio = (precio - prev) / prev * 100
        return {"ok": precio is not None, "estado": estado,
                "estado_txt": ESTADOS.get(estado, estado),
                "precio": precio, "cambio_pct": cambio, "cierre_prev": prev}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def evaluar(ctx: dict, direccion: str) -> dict:
    """Dice si el contexto en vivo confirma o contradice la señal."""
    if not ctx.get("ok") or ctx.get("cambio_pct") is None:
        return {"nivel": "sin_dato", "texto": "Sin dato de pre-market/mercado en vivo."}
    ch = ctx["cambio_pct"]
    verde = ch > UMBRAL_NEUTRO
    rojo = ch < -UMBRAL_NEUTRO
    signo = f"{ch:+.2f}%"
    est = ctx["estado_txt"]

    if abs(ch) <= UMBRAL_NEUTRO:
        return {"nivel": "neutral",
                "texto": f"{est.capitalize()}: prácticamente plano ({signo}). Sin sesgo claro aún."}

    if direccion == "call":
        if verde:
            return {"nivel": "confirma",
                    "texto": f"✅ {est}: en VERDE ({signo}) — apoya la señal alcista (CALL)."}
        return {"nivel": "contradice",
                "texto": f"🔴 {est}: en ROJO ({signo}) — CONTRADICE la señal alcista (CALL). "
                         "El precio viene bajando; la ruptura al alza está fallando en la apertura."}
    else:  # put
        if rojo:
            return {"nivel": "confirma",
                    "texto": f"✅ {est}: en ROJO ({signo}) — apoya la señal bajista (PUT)."}
        return {"nivel": "contradice",
                "texto": f"🟢 {est}: en VERDE ({signo}) — CONTRADICE la señal bajista (PUT). "
                         "El precio viene subiendo; la ruptura a la baja está fallando en la apertura."}
