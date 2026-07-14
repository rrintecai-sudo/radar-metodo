"""
lab.py — Lanza el Laboratorio de Muestras desde la consola.

Uso:
    python lab.py                      # ETFs base, estrategias diarias, 10 años
    python lab.py --universo nucleo    # ETFs + acciones del S&P 500
    python lab.py --universo todo      # todo el universo
    python lab.py --vol 1.3            # escenario con 30% más de volatilidad
    python lab.py --guardar            # guarda las operaciones en data/laboratorio.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

from config import (TICKERS, UNIVERSO_NUCLEO, STOCKS_SP500, STOCKS_FUERA,
                    SP500_DESDE, ESTRATEGIAS_INICIALES)
from engine import laboratorio as lab


def _barra(n: int, total: int, ancho: int = 28) -> str:
    llenos = int(ancho * n / total) if total else 0
    return "█" * llenos + "·" * (ancho - llenos)


def informe(trades, stats) -> None:
    if stats.get("sin_datos"):
        print("\nNo se generaron operaciones. Revisa la conexión de datos o el universo.")
        return
    n = stats["n"]
    print("\n" + "=" * 60)
    print(f"  LABORATORIO — {n} operaciones simuladas")
    print("=" * 60)

    print(f"\n  Acertó (terminó en verde): {stats['win_rate']}%")
    print(f"  Días típicos por operación: {stats['dias_medianos']}")
    print(f"\n  ── LA ASIMETRÍA ──")
    print(f"  Por cada $1 arriesgado, vuelven:  ${stats['exp_por_dolar']:.2f}  "
          f"({'A FAVOR ✅' if stats['exp_por_dolar'] > 1 else 'EN CONTRA ❌'})")
    print(f"  Retorno medio por operación:      {stats['exp_pct']:+.1f}%")
    pf = stats["profit_factor"]
    print(f"  Profit factor (ganan/pierden):    {pf if pf is not None else '∞'}")
    print(f"  Ganadora media: {stats['gan_media_ganadora_pct']:+.0f}%   "
          f"Perdedora media: {stats['perd_media_perdedora_pct']:+.0f}%")
    print(f"  Mejor operación: {stats['mult_maximo']:.1f}×   "
          f"(la más alta llegó a valer, con mano perfecta, más)")

    print(f"\n  ── DISTRIBUCIÓN (la firma del método) ──")
    for b in stats["distribucion"]:
        print(f"  {b['rango']:28s} {_barra(b['n'], n)} {b['n']:4d}  ({b['pct']}%)")

    print(f"\n  ── SI ARRIESGAS ${stats['riesgo_por_trade']:.0f} CADA VEZ ──")
    print(f"  Invertido en total:   ${stats['total_invertido']:,.0f}")
    print(f"  Resultado (P&L):      ${stats['ganancia_total']:,.0f}   "
          f"(ROI {stats['roi']:+.0f}%)")
    print(f"  Peor racha (drawdown): ${stats['max_drawdown']:,.0f}")
    print("=" * 60)
    print("  Recuerda: primas MODELADAS (vol estimada). La FORMA manda,")
    print("  no el decimal. Corré con --vol 0.8 y --vol 1.3 para estresar.")
    print("=" * 60 + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Laboratorio de Muestras del método")
    ap.add_argument("--universo", choices=["etf", "acciones", "nucleo", "paralelo"], default="etf",
                    help="etf=5 ETFs base · acciones=S&P500 · nucleo=ETFs+S&P500 · paralelo=FUERA del S&P500")
    ap.add_argument("--vol", type=float, default=1.0, help="escenario de volatilidad (1.0 = normal)")
    ap.add_argument("--periodo", default="10y", help="cuánta historia (ej. 5y, 10y, max)")
    ap.add_argument("--guardar", action="store_true", help="guardar operaciones en CSV")
    args = ap.parse_args()

    # Cada acción respeta su fecha de entrada al S&P 500 (regla "nunca salir del índice"
    # + evita la trampa del superviviente). Los ETFs no llevan corte.
    universos = {
        "etf": TICKERS,
        "acciones": STOCKS_SP500,
        "nucleo": UNIVERSO_NUCLEO,
        "paralelo": STOCKS_FUERA,   # ⚠️ FUERA del S&P 500: rompe la regla, solo para comparar
    }
    tickers = universos[args.universo]
    estrategias = ESTRATEGIAS_INICIALES  # piso_fuerte + tres_semanas (diarias)

    if args.universo == "paralelo":
        print("\n⚠️  OJO: 'paralelo' opera acciones FUERA del S&P 500 — rompe la regla")
        print("   del método. Solo para comparar potencial, no es el método puro.\n")

    print(f"\nLaboratorio: {len(tickers)} activos × {len(estrategias)} estrategias "
          f"· {args.periodo} · vol×{args.vol}")
    print("(las acciones se operan solo desde que entraron al S&P 500)")
    print("Bajando historia y simulando (esto puede tardar unos minutos)...\n")

    trades = lab.correr(tickers, estrategias, periodo=args.periodo, escenario_vol=args.vol,
                        desde_por_ticker=SP500_DESDE)
    stats = lab.estadisticas(trades)
    informe(trades, stats)

    if args.guardar and len(trades):
        p = Path(__file__).resolve().parent / "data" / "laboratorio.csv"
        trades.to_csv(p, index=False)
        print(f"Operaciones guardadas en {p}\n")


if __name__ == "__main__":
    main()
