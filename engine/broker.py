"""
broker.py — El puente al bróker (Alpaca, cuenta de PAPEL).

Le da manos al método: encuentra el contrato de opción real que pide la señal,
lee su prima REAL del mercado, y compra/vende en papel. Todo con dinero de juguete
(paper), sin riesgo real. Las llaves se leen de alpaca.json (local, no se sube a git).

Honesto: los "llenados" en papel los simula Alpaca con datos reales del mercado, así
que las primas son de verdad. Es el juez que el laboratorio no podía ser.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

_CFG = Path(__file__).resolve().parent.parent / "alpaca.json"


def _cfg() -> dict:
    return json.load(open(_CFG))


def _trading():
    from alpaca.trading.client import TradingClient
    c = _cfg()
    return TradingClient(c["api_key_id"], c["api_secret_key"], paper=c.get("paper", True))


def _data():
    from alpaca.data.historical.option import OptionHistoricalDataClient
    c = _cfg()
    return OptionHistoricalDataClient(c["api_key_id"], c["api_secret_key"])


def cuenta() -> dict:
    a = _trading().get_account()
    return {"estado": str(a.status), "efectivo": float(a.cash),
            "poder_compra": float(a.buying_power),
            "nivel_opciones": getattr(a, "options_trading_level", None)}


def buscar_contrato(ticker: str, tipo: str, strike_objetivo: float, dias: int) -> dict | None:
    """
    Encuentra el contrato real más cercano a lo que pide el método:
    strike ~OTM y vencimiento ~`dias`. `tipo` = 'CALL' o 'PUT'.
    """
    from alpaca.trading.requests import GetOptionContractsRequest
    from alpaca.trading.enums import ContractType, AssetStatus

    objetivo = date.today() + timedelta(days=dias)
    req = GetOptionContractsRequest(
        underlying_symbols=[ticker],
        status=AssetStatus.ACTIVE,
        type=ContractType.CALL if tipo.upper() == "CALL" else ContractType.PUT,
        expiration_date_gte=(objetivo - timedelta(days=7)).isoformat(),
        expiration_date_lte=(objetivo + timedelta(days=10)).isoformat(),
        strike_price_gte=str(round(strike_objetivo * 0.90, 2)),
        strike_price_lte=str(round(strike_objetivo * 1.10, 2)),
        limit=500,
    )
    res = _trading().get_option_contracts(req)
    contratos = res.option_contracts or []
    if not contratos:
        return None
    # el más cercano al strike objetivo y a la fecha objetivo
    def dist(c):
        ds = abs(float(c.strike_price) - strike_objetivo)
        dd = abs((date.fromisoformat(str(c.expiration_date)) - objetivo).days)
        return (dd, ds)  # primero la fecha, luego el strike
    mejor = min(contratos, key=dist)
    return {"symbol": mejor.symbol, "strike": float(mejor.strike_price),
            "vencimiento": str(mejor.expiration_date), "tipo": tipo.upper(),
            "subyacente": ticker}


def precio_opcion(option_symbol: str) -> dict | None:
    """Lee la prima real (bid/ask) del contrato. None si no hay datos."""
    from alpaca.data.requests import OptionLatestQuoteRequest
    try:
        req = OptionLatestQuoteRequest(symbol_or_symbols=option_symbol)
        q = _data().get_option_latest_quote(req)[option_symbol]
        bid, ask = float(q.bid_price or 0), float(q.ask_price or 0)
        mid = (bid + ask) / 2 if (bid and ask) else (ask or bid)
        return {"bid": bid, "ask": ask, "mid": round(mid, 3)}
    except Exception as e:
        return {"error": str(e)}


def _orden(option_symbol: str, contratos: int, lado, limit_price: float | None) -> dict:
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import TimeInForce
    if limit_price and limit_price > 0:
        req = LimitOrderRequest(symbol=option_symbol, qty=contratos, side=lado,
                                time_in_force=TimeInForce.DAY, limit_price=round(limit_price, 2))
    else:
        req = MarketOrderRequest(symbol=option_symbol, qty=contratos, side=lado,
                                 time_in_force=TimeInForce.DAY)
    o = _trading().submit_order(req)
    return {"id": str(o.id), "symbol": o.symbol, "qty": float(o.qty or 0),
            "estado": str(o.status), "limite": limit_price}


def comprar(option_symbol: str, contratos: int = 1, limit_price: float | None = None) -> dict:
    """Compra en papel. Con `limit_price` usa orden LÍMITE (no regala el spread)."""
    from alpaca.trading.enums import OrderSide
    return _orden(option_symbol, contratos, OrderSide.BUY, limit_price)


def vender(option_symbol: str, contratos: int = 1, limit_price: float | None = None) -> dict:
    from alpaca.trading.enums import OrderSide
    return _orden(option_symbol, contratos, OrderSide.SELL, limit_price)


def ordenes_abiertas() -> list[str]:
    """Símbolos con órdenes AÚN pendientes (para no apilar compras sobre lo mismo)."""
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus
    try:
        os = _trading().get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=100))
        return [o.symbol for o in os]
    except Exception:
        return []


def posiciones() -> list[dict]:
    """Posiciones abiertas (paper)."""
    out = []
    for p in _trading().get_all_positions():
        out.append({"symbol": p.symbol, "qty": float(p.qty),
                    "costo": float(p.cost_basis), "valor": float(p.market_value),
                    "pl": float(p.unrealized_pl), "pl_pct": round(float(p.unrealized_plpc) * 100, 1)})
    return out
