#!/bin/bash
# Doble clic para abrir el Radar del Método en tu navegador.
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "Preparando el entorno por primera vez (esto tarda un minuto)..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi
echo "Abriendo el Radar del Método en tu navegador..."
.venv/bin/streamlit run app.py
