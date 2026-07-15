"""
laboratorio.py — El "acelerador de muestras".

Revive el método completo sobre AÑOS de historia y simula CADA operación como si
la hubiéramos hecho de verdad: compra la opción, la revalora día a día con un
modelo real (Black-Scholes, que SÍ descuenta el paso del tiempo), aplica la regla
de salida del método (al +50% vende la mitad, deja correr el resto) y anota el
resultado. Miles de operaciones simuladas en minutos = las "muchas muestras".

Honestidad (léela, importa):
  - El precio del activo es REAL (histórico de Yahoo).
  - La prima de la opción es MODELADA: estimamos la volatilidad de cada activo de
    su propia historia y la metemos a Black-Scholes. No compramos el histórico real
    de primas (cuesta). Por eso las primas son APROXIMADAS. Lo que es SÓLIDO es la
    FORMA del resultado: cuántas migajas vs cuántos ×N, y si la expectativa da a
    favor o en contra. La volatilidad es una perilla (escenario_vol) para estresar
    la conclusión: si aguanta con más y con menos vol, es de fiar.
  - Mantenemos la volatilidad constante durante la vida de la opción (simplificación
    estándar). No modelamos saltos de IV por earnings/noticias.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from config import ESTRATEGIAS, SALIDA_GANANCIA_PCT, SALIDA_VENDER_FRACCION
from engine import data, method
from engine.options import sugerir_opcion

# Tasa libre de riesgo anual (aprox). Perilla.
TASA_LIBRE = 0.04
# Cómo estimamos la volatilidad implícita a partir de la realizada del activo.
IV_VENTANA = 20      # días para medir la volatilidad reciente
IV_MARKUP = 1.15     # la implícita suele estar algo por encima de la realizada
IV_PISO = 0.12       # nunca menos de 12% anual
IV_TECHO = 1.50      # nunca más de 150% anual (topamos memes salvajes)


# ---------------------------------------------------------------------------
# Modelo de precio de la opción (Black-Scholes)
# ---------------------------------------------------------------------------
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def precio_bs(S: float, K: float, T: float, sigma: float, tipo: str,
              r: float = TASA_LIBRE) -> float:
    """Precio de una opción europea. T en años. Si ya venció, vale su intrínseco."""
    call = tipo.upper() == "CALL"
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if call:
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _iv_estimada(cierres: pd.Series, escenario_vol: float = 1.0) -> float:
    """Volatilidad anual estimada de los últimos IV_VENTANA cierres."""
    rets = np.log(cierres / cierres.shift(1)).dropna()
    if len(rets) < 5:
        return IV_PISO
    sigma_diaria = float(rets.tail(IV_VENTANA).std())
    sigma_anual = sigma_diaria * math.sqrt(252) * IV_MARKUP * escenario_vol
    return float(min(max(sigma_anual, IV_PISO), IV_TECHO))


# ---------------------------------------------------------------------------
# Datos con historia LARGA (más años = más muestras)
# ---------------------------------------------------------------------------
def cargar_largo(ticker: str, intervalo: str = "1d", periodo: str = "10y",
                 forzar: bool = False) -> pd.DataFrame | None:
    """
    Baja historia larga para el laboratorio, con caché propia (no pisa la del
    dashboard, que solo guarda 2 años).
    """
    import yfinance as yf
    p = data.CACHE_DIR / f"{ticker}_{intervalo}_lab_{periodo}.parquet"
    if not forzar and p.exists():
        try:
            return pd.read_parquet(p)
        except Exception:
            pass
    try:
        df = yf.download(ticker, period=periodo, interval=intervalo,
                         auto_adjust=True, progress=False)
        if df is None or not len(df):
            return None
        df = data._normalizar(df)
        try:
            df.to_parquet(p)
        except Exception:
            pass
        return df
    except Exception as e:
        print(f"[lab] {ticker} ({intervalo}) falló: {e}")
        return None


# ---------------------------------------------------------------------------
# Simulación de UNA operación
# ---------------------------------------------------------------------------
def simular_operacion(df: pd.DataFrame, i: int, estrategia: str, direccion: str,
                      escenario_vol: float = 1.0, otm_pct: float | None = None) -> dict | None:
    """
    Simula la compra de la opción en la barra `i` y su vida hasta el vencimiento,
    aplicando la regla del método. Devuelve el resultado o None si no se puede.

    `otm_pct`: si se da, usa ese % fuera del dinero para el strike (para probar
    opciones más baratas/agresivas). Si es None, usa el del método (config).
    """
    S0 = float(df.iloc[i]["Close"])
    t0 = df.index[i]
    opt = sugerir_opcion(S0, direccion, estrategia)
    dias = opt["dias_vencimiento"]
    tipo = opt["tipo"]
    if otm_pct is None:
        K = opt["strike"]
    else:
        K = round(S0 * (1 + otm_pct / 100), 2) if tipo == "CALL" else round(S0 * (1 - otm_pct / 100), 2)

    sigma = _iv_estimada(df["Close"].iloc[: i + 1], escenario_vol)
    T0 = dias / 365.0
    prima_entrada = precio_bs(S0, K, T0, sigma, tipo)
    if prima_entrada <= 0.01:
        return None

    exp_date = t0 + pd.Timedelta(days=dias)
    fwd = df[(df.index > t0) & (df.index <= exp_date)]
    if not len(fwd):
        return None  # sin barras hacia adelante -> no se puede cerrar (trade "en curso")

    umbral_50 = prima_entrada * (1 + SALIDA_GANANCIA_PCT / 100.0)  # precio al +50%
    pos = 1.0                 # fracción del contrato que aún tengo
    proceeds = 0.0            # lo cobrado (en unidades de prima por contrato)
    vendio_mitad = False
    dia_50 = None
    max_mult = 1.0
    val = prima_entrada
    fecha_salida = fwd.index[-1]

    for j in range(len(fwd)):
        fecha = fwd.index[j]
        Sj = float(fwd.iloc[j]["Close"])
        dias_restan = max((exp_date - fecha).total_seconds() / 86400.0, 0.0)
        Tj = dias_restan / 365.0
        val = precio_bs(Sj, K, Tj, sigma, tipo)
        max_mult = max(max_mult, val / prima_entrada)
        if not vendio_mitad and val >= umbral_50:
            # regla del método: al +50%, vender la mitad y dejar correr el resto
            proceeds += SALIDA_VENDER_FRACCION * val
            pos -= SALIDA_VENDER_FRACCION
            vendio_mitad = True
            dia_50 = (fecha - t0).total_seconds() / 86400.0

    # el resto (o todo, si nunca llegó al +50%) sale al valor de la última barra
    proceeds += pos * val
    fecha_salida = fwd.index[-1]

    mult = proceeds / prima_entrada                 # múltiplo de TODA la posición
    pct = (proceeds - prima_entrada) / prima_entrada * 100.0
    dias_aguant = (fecha_salida - t0).total_seconds() / 86400.0

    return {
        "ticker": None,  # lo rellena el llamador
        "estrategia": estrategia,
        "direccion": direccion,
        "fecha_entrada": t0.isoformat(),
        "fecha_salida": fecha_salida.isoformat(),
        "dias_aguantados": round(dias_aguant, 1),
        "precio_entrada": round(S0, 2),
        "strike": K,
        "prima_entrada": round(prima_entrada, 3),
        "prima_salida": round(proceeds, 3),
        "iv_estimada": round(sigma, 3),
        "mult": round(mult, 3),          # 1.0 = ni gana ni pierde; 0 = pérdida total
        "pct": round(pct, 1),
        "dolares_x_contrato": round((proceeds - prima_entrada) * 100, 2),
        "toco_50": vendio_mitad,
        "dia_50": round(dia_50, 1) if dia_50 is not None else None,
        "max_mult": round(max_mult, 2),  # lo más alto que llegó a valer (mano perfecta)
    }


# ---------------------------------------------------------------------------
# Simulación de UN ticker + UNA estrategia (recorre toda la historia)
# ---------------------------------------------------------------------------
def simular_ticker(ticker: str, estrategia: str, periodo: str = "10y",
                   escenario_vol: float = 1.0, min_sep_barras: int = 2,
                   max_trades: int = 2000, desde: str | None = None,
                   otm_pct: float | None = None) -> list[dict]:
    """
    Encuentra cada ENTRADA histórica de esta estrategia y simula la operación.

    `desde` (fecha ISO): solo se aceptan entradas en/después de esa fecha. Sirve
    para respetar la regla "nunca salir del S&P 500": una acción solo se opera
    desde que ENTRÓ al índice (evita la trampa del superviviente).
    """
    intervalo = ESTRATEGIAS[estrategia]["intervalo"]
    # el intradía (1h) no tiene historia larga en Yahoo; para esas usamos lo que haya
    per = periodo if intervalo == "1d" else "3mo"
    df = cargar_largo(ticker, intervalo, per)
    if df is None or len(df) < 220:
        return []
    df = method.preparar(df)
    corte = pd.Timestamp(desde) if desde else None

    def _naive(ts):
        return ts.tz_localize(None) if ts.tzinfo is not None else ts

    trades: list[dict] = []
    i = 210
    ultima = -999
    n = len(df)
    while i < n - 1:
        # respeta la fecha de entrada al índice (no operar antes de ser S&P 500)
        if corte is not None and _naive(df.index[i]) < corte:
            i += 1
            continue
        sub = df.iloc[: i + 1]
        try:
            s = method.evaluar(ticker, sub, estrategia)
        except Exception:
            i += 1
            continue
        if s["estado"] == "ENTRADA" and (i - ultima) > min_sep_barras:
            op = simular_operacion(df, i, estrategia, s["direccion"], escenario_vol, otm_pct)
            if op:
                op["ticker"] = ticker
                trades.append(op)
                ultima = i
        i += 1
        if len(trades) >= max_trades:
            break
    return trades


# ---------------------------------------------------------------------------
# Correr el laboratorio completo
# ---------------------------------------------------------------------------
def correr(tickers: list[str], estrategias: list[str], periodo: str = "10y",
           escenario_vol: float = 1.0, verbose: bool = True,
           desde_por_ticker: dict | None = None, otm_pct: float | None = None) -> pd.DataFrame:
    """
    Corre todas las combinaciones ticker×estrategia y junta todas las operaciones.

    `desde_por_ticker`: mapa {ticker: fecha_ISO} para respetar la fecha de entrada
    al S&P 500 de cada acción (los ETFs no llevan corte).
    """
    desde_por_ticker = desde_por_ticker or {}
    filas: list[dict] = []
    total = len(tickers) * len(estrategias)
    hecho = 0
    for t in tickers:
        desde = desde_por_ticker.get(t)
        for est in estrategias:
            trades = simular_ticker(t, est, periodo, escenario_vol, desde=desde, otm_pct=otm_pct)
            filas.extend(trades)
            hecho += 1
            if verbose:
                marca = f" (desde {desde})" if desde else ""
                print(f"  [{hecho}/{total}] {t:6s} · {est:12s} -> {len(trades)} operaciones{marca}")
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Estadísticas de la ASIMETRÍA
# ---------------------------------------------------------------------------
def estadisticas(trades: pd.DataFrame, riesgo_por_trade: float = 100.0) -> dict:
    """
    Convierte las operaciones en las conclusiones que importan:
    cuántas migajas vs cuántos ×N, expectativa por dólar, y curva de capital.
    """
    if trades is None or not len(trades):
        return {"sin_datos": True}

    df = trades.copy().sort_values("fecha_entrada").reset_index(drop=True)
    n = len(df)
    mult = df["mult"].to_numpy()
    pct = df["pct"].to_numpy()

    ganadoras = df[df["pct"] > 0]
    perdedoras = df[df["pct"] <= 0]
    win_rate = len(ganadoras) / n * 100

    # expectativa: por cada $1 arriesgado, cuánto vuelve EN PROMEDIO (contando todo)
    exp_por_dolar = float(mult.mean())          # >1 = ventaja
    exp_pct = float(pct.mean())                 # retorno medio por operación (%)

    # profit factor = ganancias / pérdidas, TODO a riesgo fijo por operación
    # (misma base que el ROI: $1 arriesgado por trade -> P&L = mult - 1).
    pnl_unit = mult - 1.0
    ganan = float(pnl_unit[pnl_unit > 0].sum())
    pierden = float(abs(pnl_unit[pnl_unit <= 0].sum()))
    profit_factor = (ganan / pierden) if pierden > 0 else float("inf")

    # distribución de múltiplos (la firma de la asimetría)
    bordes = [(0.0, 0.25, "pérdida casi total (<0.25×)"),
              (0.25, 0.75, "pérdida (0.25–0.75×)"),
              (0.75, 1.0, "casi tablas (0.75–1×)"),
              (1.0, 2.0, "ganancia chica (1–2×)"),
              (2.0, 5.0, "buena (2–5×)"),
              (5.0, 10.0, "grande (5–10×)"),
              (10.0, float("inf"), "enorme (10×+)")]
    distribucion = []
    for lo, hi, etq in bordes:
        c = int(((mult >= lo) & (mult < hi)).sum())
        distribucion.append({"rango": etq, "n": c, "pct": round(c / n * 100, 1)})

    # curva de capital arriesgando $ fijo por operación (en orden cronológico)
    equity = 0.0
    pico = 0.0
    max_dd = 0.0
    curva = []
    for _, row in df.iterrows():
        equity += row["mult"] * riesgo_por_trade - riesgo_por_trade  # P&L de la op
        pico = max(pico, equity)
        max_dd = min(max_dd, equity - pico)
        curva.append(round(equity, 2))

    total_invertido = n * riesgo_por_trade
    ganancia_total = equity  # = suma de P&L
    roi = ganancia_total / total_invertido * 100 if total_invertido else 0

    return {
        "sin_datos": False,
        "n": n,
        "win_rate": round(win_rate, 1),
        "exp_por_dolar": round(exp_por_dolar, 3),
        "exp_pct": round(exp_pct, 1),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "gan_media_ganadora_pct": round(float(ganadoras["pct"].mean()), 1) if len(ganadoras) else 0,
        "perd_media_perdedora_pct": round(float(perdedoras["pct"].mean()), 1) if len(perdedoras) else 0,
        "mejor_pct": round(float(pct.max()), 1),
        "peor_pct": round(float(pct.min()), 1),
        "mult_maximo": round(float(mult.max()), 1),
        "dias_medianos": round(float(df["dias_aguantados"].median()), 1),
        "distribucion": distribucion,
        "riesgo_por_trade": riesgo_por_trade,
        "total_invertido": round(total_invertido, 2),
        "ganancia_total": round(ganancia_total, 2),
        "roi": round(roi, 1),
        "max_drawdown": round(max_dd, 2),
        "curva": curva,
    }
