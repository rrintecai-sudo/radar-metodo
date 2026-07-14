"""
bot.py — Lanza el bot de papel (Alpaca).

Uso:
    python bot.py --dry        # prueba en seco: muestra qué haría, sin ejecutar
    python bot.py              # un ciclo real (reconcilia, gestiona, abre)
    python bot.py --loop 5     # corre solo cada 5 minutos (en horario de mercado)
"""
from __future__ import annotations

import argparse
import time

from engine import bot_papel


def main() -> None:
    ap = argparse.ArgumentParser(description="Bot de papel del método (Alpaca)")
    ap.add_argument("--dry", action="store_true", help="prueba en seco (no ejecuta órdenes)")
    ap.add_argument("--loop", type=int, default=0, help="repetir cada N minutos")
    args = ap.parse_args()

    if args.loop:
        print(f"Bot en marcha: un ciclo cada {args.loop} min. Ctrl+C para parar.\n")
        while True:
            try:
                bot_papel.correr_una_vez(dry=args.dry)
            except Exception as e:
                print(f"[bot] error en el ciclo: {e}")
            time.sleep(args.loop * 60)
    else:
        bot_papel.correr_una_vez(dry=args.dry)


if __name__ == "__main__":
    main()
