#!/bin/bash
# Doble clic para abrir la ventana de supervisión del bot (en el navegador).
cd "$(dirname "$0")"
./.venv/bin/streamlit run panel_bot.py
