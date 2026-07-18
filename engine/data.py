"""
data.py — De dónde salen los precios.

Baja OHLC (Open/High/Low/Close) de los 5 ETFs desde Yahoo (yfinance) y los
cachea en disco. La caché evita el error 429 de Yahoo (demasiadas peticiones) y
hace que el dashboard cargue instantáneo si ya pedimos los datos hace poco.

Marcos de tiempo que usa el método:
  - "1d"  (diario)  -> estrategias piso fuerte y tres semanas
  - "1h"  (horario) -> estrategias MA40 y canal bajista
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Cuánto tiempo consideramos "fresca" la caché, por marco (segundos).
FRESCURA = {
    "1d": 60 * 60,      # datos diarios: 1 hora
    "1h": 8 * 60,       # datos horarios: 8 minutos (para sensación "en vivo")
    "30m": 5 * 60,      # media hora: 5 minutos (la vela de apertura importa)
    "1wk": 6 * 60 * 60,
}

# Cuánto histórico bajamos por marco (suficiente para el MA de 200).
PERIODO = {
    "1d": "2y",
    "1h": "3mo",   # Yahoo limita el intradía; 3 meses de horas alcanza para MA200(h)
    "30m": "1mo",  # Yahoo solo da ~60 días de 30m; 1 mes basta para la vela de apertura
    "1wk": "5y",
}


def _cache_path(ticker: str, intervalo: str) -> Path:
    return CACHE_DIR / f"{ticker}_{intervalo}.parquet"


def _leer_cache(ticker: str, intervalo: str) -> pd.DataFrame | None:
    p = _cache_path(ticker, intervalo)
    if not p.exists():
        return None
    edad = time.time() - p.stat().st_mtime
    if edad > FRESCURA.get(intervalo, 3600):
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Deja columnas simples Open/High/Low/Close/Volume y el índice como fecha."""
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance devuelve columnas (campo, ticker) cuando se baja 1 ticker
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.title)
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[cols].dropna()
    df.index = pd.to_datetime(df.index)
    df.index.name = "Fecha"
    return df


def obtener(ticker: str, intervalo: str = "1d", forzar: bool = False) -> pd.DataFrame:
    """
    Devuelve un DataFrame OHLC para un ticker y marco de tiempo.
    Usa caché salvo que `forzar=True`.
    """
    if not forzar:
        cache = _leer_cache(ticker, intervalo)
        if cache is not None and len(cache):
            return cache

    df = yf.download(
        ticker,
        period=PERIODO.get(intervalo, "1y"),
        interval=intervalo,
        auto_adjust=True,
        progress=False,
    )
    if df is None or not len(df):
        # Si Yahoo falla, intentamos servir la caché aunque esté vieja.
        p = _cache_path(ticker, intervalo)
        if p.exists():
            return pd.read_parquet(p)
        raise RuntimeError(f"No se pudieron obtener datos de {ticker} ({intervalo}).")

    df = _normalizar(df)
    try:
        df.to_parquet(_cache_path(ticker, intervalo))
    except Exception:
        pass  # sin parquet no pasa nada grave; seguimos sin caché
    return df


def descargar_lote(tickers: list[str], intervalo: str = "1d", forzar: bool = False) -> dict[str, pd.DataFrame]:
    """
    Descarga MUCHOS tickers de una sola vez (una llamada de red) y los cachea.
    Mucho más rápido que pedirlos uno por uno cuando el universo es grande.
    """
    out: dict[str, pd.DataFrame] = {}
    faltan: list[str] = []
    # primero servimos de caché lo que esté fresco
    for t in tickers:
        if not forzar:
            c = _leer_cache(t, intervalo)
            if c is not None and len(c):
                out[t] = c
                continue
        faltan.append(t)

    if faltan:
        raw = yf.download(faltan, period=PERIODO.get(intervalo, "1y"), interval=intervalo,
                          auto_adjust=True, progress=False, group_by="ticker", threads=True)
        for t in faltan:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    sub = raw[t].copy() if t in raw.columns.get_level_values(0) else None
                else:
                    sub = raw.copy()  # un solo ticker devuelto
                if sub is None or not len(sub.dropna(how="all")):
                    continue
                df = _normalizar(sub)
                if len(df):
                    out[t] = df
                    try:
                        df.to_parquet(_cache_path(t, intervalo))
                    except Exception:
                        pass
            except Exception as e:
                print(f"[data] lote: {t} ({intervalo}) falló: {e}")
    return out


def obtener_todos(intervalo: str = "1d", tickers: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Baja los 5 activos (o la lista dada) y los devuelve en un diccionario."""
    from config import TICKERS
    tickers = tickers or TICKERS
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            out[t] = obtener(t, intervalo)
        except Exception as e:  # no dejamos que un activo tumbe a los demás
            print(f"[data] aviso: {t} ({intervalo}) falló: {e}")
    return out
