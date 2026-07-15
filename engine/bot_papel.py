"""
bot_papel.py — El bot que OPERA solo el método en papel (Alpaca), con primas reales.

Ciclo (cada vez que corre):
  1) RECONCILIAR: mira qué posiciones hay de verdad en Alpaca. Las nuevas (recién
     llenadas) las adopta y les arma su plan de salida; las registra en la bitácora.
  2) GESTIONAR: para cada posición, aplica la salida partida del método
     (vende un pedazo al +30%, otro al +100%, y deja CORRER el resto con stop desde el
     pico). Cuando se cierra del todo, cierra la fila en la bitácora.
  3) BUSCAR: si hay cupo, escanea señales (método) que además tengan la OPCIÓN BARATA
     (vol baja del activo = el edge que validó el laboratorio) y manda la compra.

Filosofía: riesgo pequeño y topado (la prima), ganancia grande (el pedazo que corre).
Alpaca es la fuente de verdad de lo que se tiene; el bot solo lleva el plan de salida.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np

from config import (UNIVERSO_NUCLEO, ESTRATEGIAS, BOT_RIESGO_POR_TRADE,
                    BOT_MAX_POSICIONES, BOT_GASOLINA_MAX_VOL, BOT_SALIDA,
                    BOT_CORRE_STOP_DESDE_PICO, BOT_MAX_PRIMA_1_CONTRATO, BOT_HORA_INICIO,
                    BOT_OTM_PCT, BOT_ESTRATEGIAS)
from engine import data, method, broker, bitacora
from engine.laboratorio import precio_bs

ESTADO = Path(__file__).resolve().parent.parent / "data" / "bot_papel.json"


# ---------------------------------------------------------------------------
# Estado (plan de salida por posición)
# ---------------------------------------------------------------------------
def _cargar() -> dict:
    if ESTADO.exists():
        try:
            return json.loads(ESTADO.read_text())
        except Exception:
            pass
    return {"posiciones": {}}


def _guardar(st: dict):
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(st, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# "Opción barata" = volatilidad BAJA del activo (el edge del laboratorio)
# ---------------------------------------------------------------------------
def vol_anual(ticker: str) -> float | None:
    """Volatilidad anual (realizada) de los últimos ~20 días. None si no hay datos."""
    try:
        df = data.obtener(ticker, "1d")
        rets = np.log(df["Close"] / df["Close"].shift(1)).dropna()
        if len(rets) < 15:
            return None
        return float(rets.tail(20).std() * np.sqrt(252))
    except Exception:
        return None


def gasolina_ok(ticker: str, cache: dict) -> tuple[bool, float | None]:
    if ticker not in cache:
        cache[ticker] = vol_anual(ticker)
    v = cache[ticker]
    return (v is not None and v <= BOT_GASOLINA_MAX_VOL), v


# ---------------------------------------------------------------------------
# Tamaño de la posición (riesgo pequeño)
# ---------------------------------------------------------------------------
def _prima_estimada(senal: dict) -> float:
    """Estima la prima con Black-Scholes para dimensionar (la real viene del llenado)."""
    op = senal["opcion"]
    precio = senal["precio"]
    v = vol_anual(senal["ticker"]) or 0.30
    dias = op["dias_vencimiento"]
    return max(0.05, precio_bs(precio, op["strike"], dias / 365.0, v, op["tipo"]))


def contratos_para(prima: float) -> int:
    """
    Cuántos contratos caben en el riesgo objetivo. Si ni uno cabe pero el contrato
    cuesta <= el tope, compra 1 (para no perder la señal). Si es carísimo, 0 (salta).
    """
    if prima <= 0:
        return 0
    n = int(BOT_RIESGO_POR_TRADE // (prima * 100))
    if n < 1:
        return 1 if prima * 100 <= BOT_MAX_PRIMA_1_CONTRATO else 0
    return min(n, 10)


# ---------------------------------------------------------------------------
# Escaneo: señales del método + opción barata
# ---------------------------------------------------------------------------
def escanear() -> list[dict]:
    """Señales ENTRADA en el núcleo (ETFs + S&P500) que además pasan el filtro barato.
    Cubre estrategias diarias e intradía (cada una con su marco de datos)."""
    # agrupar las estrategias del bot por el marco de datos que necesitan
    por_intervalo: dict = {}
    for e in BOT_ESTRATEGIAS:
        por_intervalo.setdefault(ESTRATEGIAS[e]["intervalo"], []).append(e)
    senales = []
    for iv, ests in por_intervalo.items():
        datos = data.obtener_todos(iv, UNIVERSO_NUCLEO)
        senales += method.escanear(datos, ests)
    cache: dict = {}
    out = []
    for s in senales:
        if s["estado"] != "ENTRADA":
            continue
        ok, v = gasolina_ok(s["ticker"], cache)
        s["vol_anual"] = v
        s["barata"] = ok
        if ok:
            out.append(s)
    out.sort(key=lambda s: -s["score"])   # más fuerte primero
    return out


# ---------------------------------------------------------------------------
# El ciclo
# ---------------------------------------------------------------------------
def _underlying(option_symbol: str) -> str:
    """Saca el ticker del símbolo de opción (ej. SPY260727C00752000 -> SPY)."""
    i = 0
    while i < len(option_symbol) and option_symbol[i].isalpha():
        i += 1
    return option_symbol[:i]


def _parse_symbol(sym: str) -> tuple[str, str, str, float]:
    """OCC: ROOT + YYMMDD + C/P + strike*1000. -> (root, exp_iso, tipo, strike)."""
    strike = int(sym[-8:]) / 1000.0
    tipo = "CALL" if sym[-9] == "C" else "PUT"
    yy = sym[-15:-9]
    exp = f"20{yy[:2]}-{yy[2:4]}-{yy[4:6]}"
    return sym[:-15], exp, tipo, strike


def _quote_yf(ticker: str, exp: str, strike: float, tipo: str):
    """Bid/ask real de la opción vía yfinance (Alpaca gratis no da feed de opciones)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        if exp not in (t.options or []):
            return None
        tab = t.option_chain(exp)
        tab = tab.calls if tipo.upper() == "CALL" else tab.puts
        row = tab.loc[(tab["strike"] - strike).abs().idxmin()]
        bid, ask = float(row["bid"] or 0), float(row["ask"] or 0)
        if bid <= 0 and ask <= 0:
            return None
        return bid, ask
    except Exception:
        return None


def _limite(bid: float, ask: float, lado: str) -> float:
    """Precio límite razonable: compra cerca del medio-alto, venta cerca del medio-bajo."""
    if bid <= 0:
        return round(ask, 2)
    if ask <= 0:
        return round(bid, 2)
    frac = 0.6 if lado == "compra" else 0.4
    return round(bid + frac * (ask - bid), 2)


def reconciliar(st: dict, log) -> None:
    """Adopta posiciones nuevas de Alpaca y arma su plan de salida."""
    pos = {p["symbol"]: p for p in broker.posiciones()}
    # nuevas: están en Alpaca pero no en el estado
    for sym, p in pos.items():
        if sym in st["posiciones"]:
            continue
        qty = int(p["qty"])
        if qty <= 0:
            continue
        prima_ent = p["costo"] / qty / 100.0  # prima real por contrato (del llenado)
        tk = _underlying(sym)
        b = bitacora.agregar("simulacion", tk, "call", "bot", 0.0, round(prima_ent, 3),
                             qty, nota=f"bot · {sym}")
        st["posiciones"][sym] = {
            "ticker": tk, "contratos_inicial": qty, "contratos_actual": qty,
            "prima_entrada": prima_ent, "pico_plpc": 0.0, "vendido": [],
            "proceeds": 0.0, "bitacora_id": b["id"],
            "fecha": datetime.now().isoformat(timespec="minutes"),
        }
        log(f"➕ Adoptada {sym} x{qty} @ ${prima_ent:.2f} (riesgo ${prima_ent*100*qty:.0f})")


def gestionar(st: dict, log, dry: bool) -> None:
    """Aplica la salida partida a cada posición abierta."""
    pos = {p["symbol"]: p for p in broker.posiciones()}
    for sym, plan in list(st["posiciones"].items()):
        p = pos.get(sym)
        if p is None:
            # ya no está en Alpaca -> se cerró (manual o total). Cierra en bitácora.
            _cerrar_bitacora(plan)
            del st["posiciones"][sym]
            log(f"✔️ {sym} cerrada (ya no está en la cuenta)")
            continue
        qty = int(p["qty"])
        valor_contrato = p["valor"] / qty / 100.0 if qty else 0
        plpc = p["pl_pct"] / 100.0          # ganancia actual sobre el costo
        plan["pico_plpc"] = max(plan["pico_plpc"], plpc)

        # SIEMPRE se reserva 1 contrato "corredor" (dejar correr = lo que hace ganar).
        # Solo se pueden escalonar (vender por metas) los contratos por encima de esa reserva.
        reserva = 1
        escala_max = max(0, plan["contratos_inicial"] - reserva)
        ya_escalado = plan["contratos_inicial"] - qty  # ya vendidos por metas

        # 1) metas de venta parcial (+30%, +100%): 1 contrato por meta, sin tocar la reserva
        for idx, (meta, _frac) in enumerate(BOT_SALIDA):
            if idx in plan["vendido"] or ya_escalado >= escala_max:
                continue
            if plpc >= meta and qty > reserva:
                vender_lote(sym, 1, valor_contrato, plan, log, dry)
                plan["vendido"].append(idx)
                qty -= 1
                ya_escalado += 1
        # 2) el CORREDOR (lo que queda): stop desde el pico protege la ganancia grande
        if qty > 0 and qty <= reserva:
            if plan["pico_plpc"] > 0.30 and plpc <= plan["pico_plpc"] * (1 - BOT_CORRE_STOP_DESDE_PICO):
                vender_lote(sym, qty, valor_contrato, plan, log, dry)
                qty = 0

        if qty <= 0 and not dry:
            _cerrar_bitacora(plan)
            del st["posiciones"][sym]


def vender_lote(sym: str, n: int, valor_contrato: float, plan: dict, log, dry: bool) -> None:
    plan["proceeds"] = plan.get("proceeds", 0.0) + valor_contrato * 100 * n
    plan["contratos_actual"] = max(0, plan["contratos_actual"] - n)
    mult = valor_contrato / plan["prima_entrada"] if plan["prima_entrada"] else 0
    if dry:
        log(f"   [dry] vendería {n}x {sym} @ ${valor_contrato:.2f} ({mult:.1f}×)")
    else:
        root, exp, tipo, strike = _parse_symbol(sym)
        q = _quote_yf(root, exp, strike, tipo)
        limite = _limite(q[0], q[1], "venta") if q else None
        broker.vender(sym, n, limit_price=limite)
        log(f"   💰 vendí {n}x {sym} @ ${valor_contrato:.2f} ({mult:.1f}×)")


def _cerrar_bitacora(plan: dict) -> None:
    """Cierra la fila de la bitácora con la prima de salida MEZCLADA (todos los pedazos)."""
    n0 = plan["contratos_inicial"]
    prima_salida_mezcla = (plan.get("proceeds", 0.0) / 100.0) / n0 if n0 else 0
    bitacora.cerrar(plan["bitacora_id"], round(prima_salida_mezcla, 3))


def buscar_y_abrir(st: dict, log, dry: bool) -> None:
    """Si hay cupo, abre las mejores señales baratas que no tengamos ya."""
    abiertas = st["posiciones"]
    tickers_abiertos = {v["ticker"] for v in abiertas.values()}
    # ¡clave! también bloquear los que tienen una ORDEN pendiente (aún sin llenar),
    # para no apilar varias compras del mismo activo mientras el límite no llena.
    for sym in broker.ordenes_abiertas():
        tickers_abiertos.add(_underlying(sym))
    cupo = BOT_MAX_POSICIONES - len(abiertas)
    if cupo <= 0:
        log("Sin cupo (máximo de posiciones alcanzado).")
        return
    # una sola posición por activo (correlación mata la diversificación); escanear()
    # viene ordenado por fuerza, así que el primero de cada ticker es el mejor.
    candidatos = []
    vistos = set(tickers_abiertos)
    for s in escanear():
        if s["ticker"] in vistos:
            continue
        vistos.add(s["ticker"])
        candidatos.append(s)
    if not candidatos:
        log("No hay entradas baratas ahora mismo.")
        return
    for s in candidatos[:cupo]:
        op = s["opcion"]
        # strike al 6% OTM (más barato/asimétrico) en vez del 1.5% del método
        precio = s["precio"]
        strike_obj = (round(precio * (1 + BOT_OTM_PCT / 100), 2) if op["tipo"] == "CALL"
                      else round(precio * (1 - BOT_OTM_PCT / 100), 2))
        c = broker.buscar_contrato(s["ticker"], op["tipo"], strike_obj, op["dias_vencimiento"])
        if not c:
            log(f"   ⚠️  {s['ticker']}: no encontré contrato listable")
            continue
        # prima REAL del mercado (yfinance) para dimensionar y poner el límite
        q = _quote_yf(s["ticker"], c["vencimiento"], c["strike"], c["tipo"])
        if q:
            bid, ask = q
            prima = (bid + ask) / 2 if (bid and ask) else (ask or bid)
            limite = _limite(bid, ask, "compra")
        else:
            prima = _prima_estimada(s)   # sin quote: estima con modelo, va a mercado
            limite = None
        n = contratos_para(prima)
        if n < 1:
            log(f"   ⏭️  {s['ticker']} {op['tipo']}: opción muy cara (${prima*100:.0f}/contrato), salto")
            continue
        riesgo = prima * 100 * n
        if dry:
            lim = f" lím ${limite:.2f}" if limite else " a mercado"
            log(f"   [dry] COMPRARÍA {n}x {c['symbol']} (~${riesgo:.0f} riesgo{lim} · "
                f"{s['estrategia']} · vol {s['vol_anual']*100:.0f}%)")
        else:
            r = broker.comprar(c["symbol"], n, limit_price=limite)
            log(f"   🟢 COMPRÉ {n}x {c['symbol']} (~${riesgo:.0f}, lím ${limite or 0:.2f}) → {r['estado']}")


def correr_una_vez(dry: bool = False, log=print) -> None:
    """Un ciclo completo: reconciliar → gestionar → buscar."""
    clk = broker._trading().get_clock()
    ts = clk.timestamp  # hora actual en ET (aware)
    h, m = map(int, BOT_HORA_INICIO.split(":"))
    tras_inicio = (ts.hour, ts.minute) >= (h, m)
    st = _cargar()
    log(f"— Ciclo {ts.strftime('%H:%M')} ET · mercado "
        f"{'ABIERTO' if clk.is_open else 'cerrado'} · {len(st['posiciones'])} abiertas —")
    if not dry:
        reconciliar(st, log)
        gestionar(st, log, dry)
    if dry or (clk.is_open and tras_inicio):
        buscar_y_abrir(st, log, dry)
    elif clk.is_open:
        log(f"Mercado abierto pero antes de {BOT_HORA_INICIO} ET: espero (spreads anchos).")
    else:
        log("Mercado cerrado: no abro nuevas (gestiono al abrir).")
    _guardar(st)
