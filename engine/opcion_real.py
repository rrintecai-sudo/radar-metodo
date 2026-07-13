"""
opcion_real.py — Cotiza la opción REAL y proyecta cuánto dinero podrías hacer.

Trae la prima real de la opción (del mercado, vía yfinance), estima su
apalancamiento (delta) y proyecta, según el movimiento histórico típico del
activo, cuánto ganarías en dólares. Números concretos, no ejemplos inventados.

Honesto: es una estimación con delta (ignora el decaimiento temporal y el gamma).
Sirve para tener una IDEA del tamaño del negocio, no una promesa.
"""
from __future__ import annotations

from datetime import date, timedelta

import yfinance as yf


def cotizar(ticker: str, tipo: str, strike_sugerido: float, dias: int) -> dict | None:
    """Busca la opción real más cercana al strike y vencimiento sugeridos."""
    try:
        t = yf.Ticker(ticker)
        exps = t.options
        if not exps:
            return None
        objetivo = date.today() + timedelta(days=dias)
        exp = min(exps, key=lambda e: abs((date.fromisoformat(e) - objetivo).days))
        ch = t.option_chain(exp)
        tabla = ch.calls if tipo == "CALL" else ch.puts
        if tabla is None or not len(tabla):
            return None
        # strike más cercano al sugerido
        idx = (tabla["strike"] - strike_sugerido).abs().idxmin()
        row = tabla.loc[idx]
        premium = float(row.get("lastPrice") or 0)
        bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
        if premium <= 0 and (bid or ask):
            premium = (bid + ask) / 2
        if premium <= 0:
            return None
        strike = float(row["strike"])

        # delta aproximado: cómo cambia la prima entre strikes vecinos
        serie = tabla.set_index("strike")["lastPrice"].dropna()
        delta = 0.4  # valor por defecto razonable para OTM
        try:
            strikes = list(serie.index)
            paso = strikes[1] - strikes[0] if len(strikes) > 1 else 1
            arriba = serie.get(strike + 2 * paso)
            abajo = serie.get(strike - 2 * paso)
            if arriba is not None and abajo is not None and paso:
                delta = abs((abajo - arriba) / (4 * paso))
                delta = min(max(delta, 0.15), 0.9)
        except Exception:
            pass

        dias_real = (date.fromisoformat(exp) - date.today()).days
        return {"exp": exp, "dias": dias_real, "strike": strike,
                "premium": round(premium, 2), "delta": round(delta, 2)}
    except Exception:
        return None


def proyeccion(precio: float, cot: dict, favorable_pct: float, contratos: int = 1) -> dict:
    """
    Proyecta la ganancia en dólares según escenarios de movimiento del activo.
    `favorable_pct` = movimiento a favor típico (del backtest).
    """
    premium = cot["premium"]
    delta = cot["delta"]
    costo = premium * 100 * contratos  # lo que pagas = tu riesgo máximo

    def escenario(mov_activo_pct: float) -> dict:
        cambio_precio = precio * mov_activo_pct / 100.0
        gan_por_accion = delta * cambio_precio        # sube la opción (aprox por delta)
        gan_pct = gan_por_accion / premium * 100
        gan_dolares = gan_por_accion * 100 * contratos
        return {"mov": mov_activo_pct, "opcion_pct": round(gan_pct), "dolares": round(gan_dolares)}

    # movimiento del activo necesario para que la opción haga +50% (regla de salida)
    mov_para_50 = 0.5 * premium / (delta * precio) * 100 if delta and precio else 0

    return {
        "costo": round(costo),
        "contratos": contratos,
        "mov_para_50": round(mov_para_50, 2),
        "ganancia_50": round(0.5 * premium * 100 * contratos),  # +50% en dólares
        "tipico": escenario(favorable_pct),          # movimiento a favor típico
        "grande": escenario(favorable_pct * 1.8),    # un buen día
        "riesgo_max": round(costo),                  # pérdida máxima = la prima
    }


def prob_movimiento(targets: dict, mov_pct: float) -> float:
    """
    Probabilidad histórica de que el activo se mueva a favor >= mov_pct%.
    Interpola entre los umbrales medidos (1,2,3,5,8%). 100% en 0.
    """
    if mov_pct <= 0:
        return 100.0
    def _wr(w):
        return w["win_rate"] if isinstance(w, dict) else w
    pts = sorted((float(t), float(_wr(w))) for t, w in targets.items())
    xs = [0.0] + [t for t, _ in pts]
    ys = [100.0] + [w for _, w in pts]
    if mov_pct >= xs[-1]:
        # extrapolación lineal desde los dos últimos puntos, con piso en 0
        x0, x1 = xs[-2], xs[-1]
        y0, y1 = ys[-2], ys[-1]
        pend = (y1 - y0) / (x1 - x0) if x1 != x0 else 0
        return max(0.0, y1 + pend * (mov_pct - x1))
    for i in range(1, len(xs)):
        if mov_pct <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            return y0 + (y1 - y0) * (mov_pct - x0) / (x1 - x0)
    return 0.0


def _valor_futuro(precio: float, cot: dict, mov_pct: float, tipo: str) -> float:
    """
    Valor estimado de la opción tras un movimiento a favor de `mov_pct`.
    Usa el máximo entre: (a) estimación lineal por delta y (b) el valor intrínseco
    (lo que vale si queda dentro del dinero). El intrínseco captura la explosión
    'gamma' de las opciones muy fuera del dinero en movimientos grandes.
    """
    P, delta, K = cot["premium"], cot["delta"], cot["strike"]
    m = abs(mov_pct)
    if tipo.upper() == "CALL":
        s2 = precio * (1 + m / 100.0)
        intrinseco = max(0.0, s2 - K)
    else:
        s2 = precio * (1 - m / 100.0)
        intrinseco = max(0.0, K - s2)
    lineal = P + delta * abs(s2 - precio)
    return max(intrinseco, lineal)


def _mov_para_multiplo(precio: float, cot: dict, n: float, tipo: str) -> float:
    """Movimiento del activo (%) necesario para que la opción multiplique por `n`."""
    P, delta, K = cot["premium"], cot["delta"], cot["strike"]
    objetivo = n * P
    if tipo.upper() == "CALL":
        mov_intr = (K + objetivo - precio) / precio * 100      # rama intrínseca (OTM + grande)
    else:
        mov_intr = (precio - (K - objetivo)) / precio * 100
    mov_lineal = max(0.0, (objetivo - P) / delta) / precio * 100  # rama lineal (movimiento chico)
    cands = [m for m in (mov_intr, mov_lineal) if m > 0]
    return min(cands) if cands else 0.0


def tiempo_movimiento(targets: dict, mov_pct: float):
    """Días típicos (mediana) que tarda el activo en moverse a favor `mov_pct`%. None si nunca lo hizo."""
    pts = sorted((float(t), d["dias_mediana"]) for t, d in targets.items()
                 if isinstance(d, dict) and d.get("dias_mediana") is not None)
    if not pts:
        return None
    xs = [t for t, _ in pts]
    ys = [d for _, d in pts]
    if mov_pct <= xs[0]:
        return ys[0]
    if mov_pct >= xs[-1]:
        if len(xs) >= 2 and xs[-1] != xs[-2]:
            pend = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
            return max(ys[-1], ys[-1] + pend * (mov_pct - xs[-1]))
        return ys[-1]
    for i in range(1, len(xs)):
        if mov_pct <= xs[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            return y0 + (y1 - y0) * (mov_pct - x0) / (x1 - x0)
    return ys[-1]


def prob_de_multiplo(precio: float, cot: dict, targets: dict, n: float, tipo: str = "CALL") -> float:
    """Probabilidad histórica de que la opción multiplique por `n` (ej. n=2, 5, 10)."""
    if not cot or not cot.get("premium") or not cot.get("delta"):
        return 0.0
    return round(prob_movimiento(targets, _mov_para_multiplo(precio, cot, n, tipo)))


def tiempo_de_multiplo(precio: float, cot: dict, targets: dict, n: float, tipo: str = "CALL"):
    """Días típicos (mediana) para que la opción multiplique por `n`. None si no hay dato."""
    if not cot or not cot.get("premium") or not cot.get("delta"):
        return None
    return tiempo_movimiento(targets, _mov_para_multiplo(precio, cot, n, tipo))


def valor_esperado(precio: float, cot: dict, targets: dict, mfe_max: float,
                   tipo: str = "CALL", mult_perdida: float = 0.25) -> float:
    """
    Valor esperado = por cada $1 arriesgado, cuánto recuperas EN PROMEDIO
    (contando las que ganan Y las que pierden). >1 = ventaja; <1 = desventaja.
    Combina probabilidad y tamaño de ganancia en un solo número.
    """
    if not cot or not cot.get("premium"):
        return 0.0
    p = lambda m: prob_movimiento(targets, m) / 100.0
    buckets = [
        (0.0, 1.0, 0.5), (1.0, 2.0, 1.5), (2.0, 3.0, 2.5),
        (3.0, 5.0, 4.0), (5.0, 8.0, 6.5), (8.0, max(mfe_max, 8.0), min(mfe_max, 12.0)),
    ]
    ve = 0.0
    for lo, hi, rep in buckets:
        prob = max(0.0, p(lo) - p(hi))   # el bucket (0,1) ya captura las que pierden
        mult = mult_perdida if rep < 1.0 else multiplo(precio, cot, rep, tipo)
        ve += prob * mult
    return round(ve, 2)


def multiplo(precio: float, cot: dict, mov_activo_pct: float, tipo: str = "CALL") -> float:
    """Por cuánto se multiplica el contrato si el activo se mueve `mov_activo_pct` a favor."""
    if not cot or not cot.get("premium"):
        return 1.0
    return round(_valor_futuro(precio, cot, mov_activo_pct, tipo) / cot["premium"], 1)


def tabla_escenarios(precio: float, cot: dict, direccion: str,
                     movimientos=(1, 2, 3, 5), contratos: int = 1) -> list[dict]:
    """
    Cómo se revaloriza el CONTRATO según cuánto se mueva la ACCIÓN.
    Para CALL, la acción sube; para PUT, baja (ese es el movimiento a favor).
    """
    premium = cot["premium"]
    delta = cot["delta"]
    signo = 1 if direccion.upper() == "CALL" else -1
    flechas = "sube" if signo == 1 else "baja"
    filas = []
    for m in movimientos:
        precio_nuevo = precio * (1 + signo * m / 100.0)
        gan_por_accion = delta * abs(precio_nuevo - precio)   # cuánto sube la opción/acción
        opcion_nueva = premium + gan_por_accion
        opcion_pct = gan_por_accion / premium * 100 if premium else 0
        ganancia = gan_por_accion * 100 * contratos
        filas.append({
            "mov_accion": m, "dir_accion": flechas,
            "precio_nuevo": round(precio_nuevo, 2),
            "opcion_pct": round(opcion_pct),
            "opcion_valor": round(opcion_nueva, 2),
            "ganancia": round(ganancia),
        })
    return filas
