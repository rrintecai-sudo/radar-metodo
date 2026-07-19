#!/bin/bash
# ============================================================
#  RADAR DEL MÉTODO — arranca TODO con un solo doble clic
#  · El Radar (tablero en tu navegador)
#  · El Vigilante (te avisa al Telegram: compras y ventas)
#  Deja esta ventana abierta durante el día. Ciérrala para parar todo.
# ============================================================
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Preparando el entorno por primera vez (tarda un minuto)..."
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

echo "============================================================"
echo "  RADAR DEL METODO - modo local (datos completos y fiables)"
echo "============================================================"
echo ""

# --- 1) El Vigilante, en segundo plano ---
echo "-> Arrancando el Vigilante (avisos al Telegram)..."
.venv/bin/python vigilante.py --cada 10 > vigilante.log 2>&1 &
VIG_PID=$!
sleep 2
if kill -0 $VIG_PID 2>/dev/null; then
  echo "   OK. Vigilante activo (compras 10am-4pm + ventas todo el dia)."
else
  echo "   AVISO: el Vigilante no arranco. Revisa vigilante.log"
fi

# Al cerrar esta ventana, se detiene el Vigilante tambien.
trap "echo ''; echo 'Cerrando el Vigilante...'; kill $VIG_PID 2>/dev/null; exit 0" INT TERM EXIT

echo ""
echo "-> Abriendo el Radar en tu navegador..."
echo "   (Deja esta ventana ABIERTA mientras operes)"
echo ""

# --- 2) El Radar, en primer plano (mantiene la ventana viva) ---
.venv/bin/streamlit run app.py
