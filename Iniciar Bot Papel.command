#!/bin/bash
# Doble clic para encender el bot de papel. Opera solo durante el mercado.
# Ctrl+C en la ventana para pararlo.
cd "$(dirname "$0")"
./.venv/bin/python bot.py --loop 5
