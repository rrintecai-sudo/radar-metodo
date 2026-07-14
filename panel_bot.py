"""
panel_bot.py — Ventana de supervisión del bot de papel (se actualiza sola).

Corre:  streamlit run panel_bot.py   (o doble clic en "Ver Bot.command")
Muestra: si el bot está operando, las posiciones en vivo, lo último que hizo y la bitácora.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from engine import broker, bitacora

RAIZ = Path(__file__).resolve().parent
LOG = RAIZ / "data" / "bot_papel.log"

st.set_page_config(page_title="Bot en vivo", page_icon="🤖", layout="wide")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=30_000, key="ref")  # refresca cada 30 s
except Exception:
    pass

st.title("🤖 Bot de papel — en vivo")
st.caption("Se actualiza solo cada 30 segundos. Cierra esta pestaña cuando quieras.")

# ---- ¿Está operando? (según el último ciclo escrito en el log) ----
ultimo, lineas = None, []
if LOG.exists():
    lineas = [l for l in LOG.read_text(errors="ignore").splitlines()
              if l.strip() and "warning" not in l.lower()]
    for l in reversed(lineas):
        if "Ciclo" in l:
            ultimo = l
            break

edad_min = None
if LOG.exists():
    edad_min = (datetime.now().timestamp() - LOG.stat().st_mtime) / 60

c1, c2, c3 = st.columns(3)
if edad_min is not None and edad_min < 8:
    c1.success("🟢 Operando")
else:
    c1.error("🔴 Detenido")
    c1.caption("Enciéndelo con «Iniciar Bot Papel.command»")
c2.metric("Último ciclo", ultimo.split("·")[0].replace("—", "").strip() if ultimo else "—")

try:
    clk = broker._trading().get_clock()
    c3.metric("Mercado", "ABIERTO" if clk.is_open else "cerrado")
except Exception:
    c3.metric("Mercado", "—")

# ---- Posiciones abiertas (en vivo) ----
st.subheader("📌 Posiciones abiertas")
try:
    pos = broker.posiciones()
except Exception as e:
    pos = []
    st.warning(f"No pude leer las posiciones: {e}")
if not pos:
    st.info("Ninguna posición abierta ahora mismo.")
else:
    for p in pos:
        a, b, c, d = st.columns([3, 2, 2, 2])
        a.write(f"**{p['symbol']}**  ×{p['qty']:g}")
        b.write(f"Costo ${p['costo']:.0f}")
        c.write(f"Valor ${p['valor']:.0f}")
        color = "green" if p["pl_pct"] >= 0 else "red"
        d.markdown(f":{color}[**{p['pl_pct']:+.0f}%**]")

# ---- Bitácora (resultados que se van cerrando) ----
st.subheader("📔 Bitácora (libro simulación)")
m = bitacora.metricas("simulacion")
if m.get("n", 0) == 0:
    st.info("Aún no hay operaciones cerradas — el bot está juntando muestras.")
else:
    x1, x2, x3, x4 = st.columns(4)
    x1.metric("Operaciones", m["n"])
    x2.metric("Acierto", f"{m['win_rate']:.0f}%")
    x3.metric("Expectativa", f"{m['expectativa']:+.0f}%")
    x4.metric("Total", f"${m['total_usd']:+.0f}")

filas = bitacora.listar("simulacion")
if filas:
    st.dataframe(
        [{"#": t["id"], "Activo": t["ticker"], "Estrategia": t["estrategia"],
          "Contratos": t["contratos"], "Prima entrada": t["prima_entrada"],
          "Estado": t["estado"], "Resultado %": t.get("resultado_pct")}
         for t in filas],
        use_container_width=True, hide_index=True)

# ---- Últimas acciones del bot ----
st.subheader("🧾 Lo último que hizo el bot")
if lineas:
    st.code("\n".join(lineas[-16:]), language=None)
else:
    st.info("El bot todavía no ha escrito nada.")
