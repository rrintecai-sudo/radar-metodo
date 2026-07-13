#!/bin/bash
# Doble clic para que el Vigilante empiece a vigilar y avisarte.
# Déjalo corriendo en su ventana durante el día. Ciérralo cuando quieras parar.
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "Falta preparar el entorno. Abre primero 'Iniciar Radar.command'."
  read -p "Enter para cerrar..."
  exit 1
fi
echo "El Vigilante está activo. Te avisaré cuando haya una entrada."
echo "(Deja esta ventana abierta. Ciérrala para detenerlo.)"
.venv/bin/python vigilante.py --cada 10
