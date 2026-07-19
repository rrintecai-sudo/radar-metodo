"""
app.py — El dashboard del Radar del Método.

Se abre en el navegador. Muestra, para los 5 activos y las estrategias elegidas:
  - las señales del método ordenadas por fuerza (ENTRADA / VIGILAR)
  - el checklist vivo de cada una (qué se cumple, qué falta)
  - la opción sugerida (strike OTM + vencimiento)
  - el gráfico de velas con promedios y niveles

Ejecutar:   streamlit run app.py
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (ACTIVOS, UNIVERSO, TICKERS, UNIVERSO_NUCLEO, UNIVERSO_PARALELO,
                    UNIVERSO_TICKERS, ESTRATEGIAS, ESTRATEGIAS_INICIALES,
                    CAPITAL_PRUEBA, RIESGO_MAX_CAPITAL_PCT, SALIDA_GANANCIA_PCT,
                    PREMIO_MINIMO_POR_ESTRATEGIA, PREMIO_PISO_ABSOLUTO)
from streamlit_autorefresh import st_autorefresh

from engine import data, method, viz, backtest, premarket, screener, earnings, notify, opcion_real
from engine import calendar as cal
from engine import bitacora
from engine import zones as zn

st.set_page_config(page_title="Radar del Método", page_icon="📈", layout="wide")

COLOR = {"ENTRADA": "#0F6E56", "VIGILAR": "#B8860B", "NADA": "#888"}
ICONO = {"ENTRADA": "🟢", "VIGILAR": "🟡", "NADA": "⚪"}

ESTILO = """
<style>
:root{--ink:#141B26;--muted:#7A8494;--line:#E9E4DA;--accent:#0FB37E;--accent2:#0E7C6B;--bg:#F6F4EF;--card:#FFFFFF;}
.stApp{background:var(--bg);}
[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer{visibility:hidden;}
[data-testid="stMainBlockContainer"]{padding-top:2.2rem;max-width:1500px;}
html,body,[class*="css"]{font-family:-apple-system,"SF Pro Display","Segoe UI",Inter,system-ui,sans-serif;}
h1,h2,h3,h4{color:var(--ink);font-weight:700;letter-spacing:-0.015em;}
h1{font-weight:800;}
/* tarjetas */
[data-testid="stVerticalBlockBorderWrapper"]{
  background:var(--card);border:1px solid var(--line);border-radius:16px;
  box-shadow:0 1px 2px rgba(20,27,38,.04),0 4px 16px rgba(20,27,38,.03);
}
/* métricas */
[data-testid="stMetricValue"]{font-weight:700;font-variant-numeric:tabular-nums;color:var(--ink);}
[data-testid="stMetricLabel"] p{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.04em;}
/* botones */
.stButton>button{border-radius:11px;border:1px solid var(--line);font-weight:600;background:var(--card);
  color:var(--ink);transition:all .15s ease;}
.stButton>button:hover{border-color:var(--accent);color:var(--accent2);box-shadow:0 2px 10px rgba(15,179,126,.12);}
/* sidebar */
[data-testid="stSidebar"]{background:var(--card);border-right:1px solid var(--line);}
/* captions y dataframes */
[data-testid="stCaptionContainer"] p{color:var(--muted);}
[data-testid="stDataFrame"]{border-radius:12px;overflow:hidden;border:1px solid var(--line);}
/* radios/checkbox más compactos */
[data-testid="stWidgetLabel"] p{font-size:.85rem;color:var(--muted);}
hr{margin:.6rem 0;border-color:var(--line);}
</style>
"""

CABECERA = """
<div style="display:flex;align-items:center;gap:11px;padding:6px 0 2px 0;border-bottom:2px solid var(--accent);margin-bottom:14px;">
  <div style="width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#0FB37E,#0E7C6B);
       display:flex;align-items:center;justify-content:center;color:white;font-weight:800;font-size:17px;">◈</div>
  <div style="font-size:1.3rem;font-weight:800;color:#141B26;letter-spacing:-.02em;">radar-metodo</div>
</div>
"""


@st.cache_data(ttl=600, show_spinner=False)
def escanear(ests: tuple[str, ...]) -> list[dict]:
    return method.escanear_completo(estrategias=list(ests))


@st.cache_data(ttl=600, show_spinner=False)
def cargar(ticker: str, intervalo: str) -> pd.DataFrame:
    return method.preparar(data.obtener(ticker, intervalo))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def historial(ticker: str, estrategia: str) -> dict:
    # el histórico casi no cambia durante el día -> caché largo (6h) para ir rápido
    return backtest.historial_senal(ticker, estrategia)


@st.cache_data(ttl=120, show_spinner=False)
def contexto_vivo(ticker: str) -> dict:
    return premarket.contexto(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def calendario() -> dict:
    return {"proximos": cal.proximos(), "contexto": cal.contexto_senal()}


@st.cache_data(ttl=180, show_spinner=False)
def oportunidades_universo(tickers: tuple[str, ...], incluir_horario: bool) -> list[dict]:
    return screener.escanear_universo(tickers=list(tickers), incluir_horario=incluir_horario)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def earnings_ctx(ticker: str, dias_ventana: int, es_accion: bool) -> dict:
    return earnings.contexto(ticker, dias_ventana, es_accion)


@st.cache_data(ttl=300, show_spinner=False)
def chequear_senal(ticker: str, direccion: str) -> tuple[str, str]:
    """
    ¿El motor sigue A FAVOR de una posición abierta, o se volteó EN CONTRA?
    Compara la dirección de tu posición con lo que el motor ve AHORA.
    """
    favor_ent = favor_vig = contra_ent = contra_vig = False
    for est in ESTRATEGIAS:
        iv = ESTRATEGIAS[est]["intervalo"]
        try:
            df = method.preparar(data.obtener(ticker, iv))
            s = method.evaluar(ticker, df, est)
        except Exception:
            continue
        if s["estado"] == "ENTRADA":
            if s["direccion"] == direccion:
                favor_ent = True
            else:
                contra_ent = True
        elif s["estado"] == "VIGILAR":
            if s["direccion"] == direccion:
                favor_vig = True
            else:
                contra_vig = True
    # Filosofía Cardona: NUNCA cortar. La pérdida ya está topada en la prima.
    # El tool informa si el motor sigue de tu lado, pero SIEMPRE recuerda aguantar.
    if favor_ent:
        return "favor", "✅ Señal A FAVOR (confirmada) — el motor sigue de tu lado"
    if favor_vig:
        return "favor", "🟡 Señal a favor (vigilando) — sigue de tu lado"
    if contra_ent and not favor_vig:
        return "neutral", ("🟡 El motor ya no te apoya — pero tu pérdida está TOPADA en la prima. "
                           "Cardona: aguanta, no cortes por miedo; deja que el mercado trabaje")
    if contra_vig:
        return "neutral", ("🟡 El motivo se está enfriando — aguanta con calma. "
                           "Lo máximo que arriesgas ya lo sabías (la prima)")
    return "neutral", ("🔕 El motivo del método ya no está activo — no cortes por miedo. "
                       "Pérdida topada; deja correr hasta que doble o venza")


@st.cache_data(ttl=300, show_spinner=False)
def cotizacion(ticker: str, tipo: str, strike: float, dias: int) -> dict | None:
    return opcion_real.cotizar(ticker, tipo, strike, dias)


@st.cache_data(ttl=300, show_spinner=False)
def cotizacion_por_prima(ticker: str, tipo: str, precio: float, dias: int) -> dict | None:
    """La regla real de Cardona: el contrato se elige por PRECIO DE LA PRIMA."""
    return opcion_real.cotizar_por_prima(ticker, tipo, precio, dias)


@st.cache_data(ttl=300, show_spinner=False)
@st.cache_data(ttl=300, show_spinner=False)
def cotizacion_x10(ticker: str, tipo: str, precio: float) -> dict | None:
    """La opción de lotería, elegida por prima BARATA (donde viven los ×10)."""
    from config import VENCIMIENTO_DIAS_AGRESIVO
    # buscamos contratos muy baratos: entre 5 y 20 centavos
    return opcion_real.cotizar_por_prima(ticker, tipo, precio,
                                         VENCIMIENTO_DIAS_AGRESIVO, rango=(0.05, 0.20))


def cotizacion_agresiva(ticker: str, tipo: str, precio: float) -> dict | None:
    """La opción 'lotería': más fuera del dinero y vencimiento corto (×10 posible)."""
    from config import STRIKE_OTM_AGRESIVO, VENCIMIENTO_DIAS_AGRESIVO
    signo = 1 if tipo == "CALL" else -1
    strike = round(precio * (1 + signo * STRIKE_OTM_AGRESIVO / 100), 2)
    return opcion_real.cotizar(ticker, tipo, strike, VENCIMIENTO_DIAS_AGRESIVO)


def escalera_de_venta(prima: float, contratos: int, h: dict, s: dict, tp: str, cot: dict):
    """
    🪜 LA ESCALERA DE VENTA — así es como Cardona llega a ×10-×20.
    No se vende todo al doblar: se va vendiendo por partes y se DEJA CORRER
    un pedazo. "15, 20 veces la inversión, solamente por sostener."
    """
    costo_total = round(prima * 100 * contratos)
    # reparto: mitad al ×2 (recupera capital), luego por partes, y deja correr
    n2 = max(1, contratos // 2)
    resto = contratos - n2
    n3 = max(0, resto // 2) if resto >= 2 else 0
    n5 = max(0, (resto - n3) // 2) if (resto - n3) >= 2 else 0
    corre = resto - n3 - n5

    filas = []
    acum = 0
    for mult, n, etiqueta in [(2, n2, "Recuperas TODO tu capital"),
                              (3, n3, "Ganancia asegurada"),
                              (5, n5, "Más ganancia")]:
        if n <= 0:
            continue
        entra = round(prima * mult * 100 * n)
        acum += entra
        p = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], mult, tp) if not h.get("sin_datos") else None
        filas.append({"Escalón": f"×{mult}", "Vendes": f"{n} contrato(s)",
                      "Recibes": f"${entra:,}", "Acumulado": f"${acum:,}",
                      "Prob.": f"{p:.0f}%" if p else "—", "Qué logras": etiqueta})
    if corre > 0:
        p10 = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 10, tp) if not h.get("sin_datos") else None
        filas.append({"Escalón": "×10+", "Vendes": f"{corre} corriendo",
                      "Recibes": f"${round(prima*10*100*corre):,}", "Acumulado": "—",
                      "Prob.": f"{p10:.0f}%" if p10 else "—",
                      "Qué logras": "🚀 AQUÍ están los ×10 — por sostener"})
    if not filas:
        return
    st.markdown("**🪜 Tu escalera de venta** — así es como se llega a los ×10")
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)
    st.caption(f"Invertiste **${costo_total:,}**. Al ×2 ya lo recuperaste todo: de ahí en adelante "
               f"**juegas con dinero de la casa**. Por eso puedes dejar correr los últimos "
               f"contratos sin miedo — es exactamente lo que hace Alejandro para llegar a ×10-×20.")
    # honestidad sobre la granularidad: cuántos contratos hacen falta para escalar
    if contratos <= 1:
        st.warning("⚠️ Con **1 contrato** no hay escalera: es **todo o nada**. Para poder ir "
                   "asegurando ganancia y aun así cazar el ×10, necesitas **al menos 2-3 contratos** "
                   "(por eso los contratos baratos, como SPY/QQQ, te convienen para esto).")
    elif contratos < 4:
        st.caption(f"💡 Con **{contratos} contratos** haces una escalera básica (recuperas + dejas correr). "
                   "Para una escalera fina (vender también en ×3 y ×5) te vienen bien **4+ contratos**, "
                   "que consigues con primas baratas.")


def jugada_x10(s: dict, h: dict, tp: str):
    """
    🎰 LA JUGADA ×10 — el billete de lotería, visible y accionable.
    Es la opción MÁS BARATA y más lejos del dinero: improbable, pero cuando pega
    multiplica por 10 o más. Aquí es donde viven los ×10 de Alejandro.
    Regla de oro: se juega con una TAJADA CHICA, dinero que das por perdido.
    """
    # primero la lotería barata (prima 0.05-0.20); si no hay, la agresiva por % OTM
    cot_ag = (cotizacion_x10(s["ticker"], s["opcion"]["tipo"], s["precio"])
              or cotizacion_agresiva(s["ticker"], s["opcion"]["tipo"], s["precio"]))
    if not cot_ag or h.get("sin_datos"):
        return
    p10 = opcion_real.prob_de_multiplo(s["precio"], cot_ag, h["targets"], 10, tp)
    p5 = opcion_real.prob_de_multiplo(s["precio"], cot_ag, h["targets"], 5, tp)
    t10 = opcion_real.tiempo_de_multiplo(s["precio"], cot_ag, h["targets"], 10, tp)
    costo = round(cot_ag["premium"] * 100)
    if not p10 or p10 < 1:
        return  # si ni siquiera hay chance histórica, no se la ofrecemos

    with st.container(border=True):
        st.markdown("#### 🎰 La jugada ×10 (billete de lotería)")
        a, b, c = st.columns(3)
        a.metric("Cuesta", f"${costo}", help="Mucho más barata que la balanceada.")
        b.metric("Prob. de ×10", f"{p10:.0f}%", help="Histórica, con esta misma señal.")
        c.metric("Prob. de ×5", f"{p5:.0f}%")
        venc_x = _fecha_es(cot_ag["exp"])
        st.markdown(f"**{s['opcion']['tipo']} {s['ticker']} · strike {cot_ag['strike']}** · "
                    f"vence {venc_x} ({cot_ag['dias']} días)")
        if cot_ag.get("bid") is not None and cot_ag.get("ask"):
            st.caption(f"Pagas ${cot_ag['premium']} (ask) · bid ${cot_ag.get('bid')} / "
                       f"ask ${cot_ag.get('ask')}")
        st.markdown(f"👉 Si pega el ×10, **${costo} se convierten en ~${costo*10:,}**"
                    + (f" (tarda ~{t10:.0f} días)" if t10 else ""))
        st.warning(
            f"⚠️ **Es lotería, y hay que jugarla como tal.** Lo más probable ({100-p10:.0f}%) "
            "es que se vaya a **cero**. Métele solo una **tajada chica** — dinero que ya diste "
            "por perdido. **Nunca** el tamaño de una operación normal.")
        cuenta = int(st.session_state.get("cuenta_usd", 1000))
        sugerido = max(1, int((cuenta * 0.03) // costo)) if costo else 1
        st.info(f"💡 Tamaño sugerido: **3% de tu cuenta** (${round(cuenta*0.03)}) → "
                f"**{sugerido} contrato(s)** = ${sugerido*costo}. Si se va a cero, no te duele.")
        cc = st.columns([1, 2])
        n_x = cc[0].number_input("Contratos", min_value=1, value=sugerido, step=1,
                                 key=f"x10n_{s['ticker']}_{s['estrategia']}")
        if cc[1].button("🎰 La compré — registrar la lotería",
                        key=f"x10r_{s['ticker']}_{s['estrategia']}", use_container_width=True):
            bitacora.agregar("simulacion", s["ticker"], s["direccion"], s["estrategia"],
                             cot_ag["strike"], cot_ag["premium"], int(n_x),
                             nota="🎰 jugada ×10 (lotería, tajada chica)",
                             vencimiento=cot_ag["exp"])
            st.success(f"✅ Registrada la lotería: {s['ticker']} {cot_ag['strike']} × {n_x}")


def panel_dinero(s: dict):
    """💵 Cuánto dinero podrías hacer, con la prima REAL de la opción."""
    st.markdown("#### 💵 Cuánto podrías hacer (prima real, en vivo)")
    o = s["opcion"]
    cot = cotizacion(s["ticker"], o["tipo"], o["strike"], o["dias_vencimiento"])
    if not cot:
        st.caption("No pude traer la prima real ahora mismo (a veces el mercado tarda). Intenta refrescar.")
        return
    fav = s.get("beneficio_pct") or 2.0
    pr = opcion_real.proyeccion(s["precio"], cot, fav, contratos=1)
    h = historial(s["ticker"], s["estrategia"])   # histórico (se usa en varios bloques)

    # --- la relación acción vs. contrato ---
    valor_100 = round(s["precio"] * 100)
    a, b, c = st.columns(3)
    a.metric(f"Acción {s['ticker']}", f"${s['precio']:.2f}", help="Precio de la acción/activo ahora.")
    b.metric("Contrato (1)", f"${pr['costo']}", help="Lo que pagas = tu riesgo máximo.")
    c.metric("Controlas", f"${valor_100:,}", help=f"100 acciones a ${s['precio']:.2f}. Ese es el apalancamiento.")
    st.caption(f"Con **${pr['costo']}** (el contrato) controlas **100 acciones** de {s['ticker']} "
               f"(que valen ${valor_100:,}). Opción real: **{o['tipo']} strike {cot['strike']}**, "
               f"vence {cot['exp']} ({cot['dias']}d) · prima ${cot['premium']} · apalancamiento ×{cot['delta']}")

    # --- el marco de ASIMETRÍA: riesgo pequeño y topado vs. beneficio grande ---
    tp = o["tipo"]
    mult_tip = opcion_real.multiplo(s["precio"], cot, s.get("beneficio_pct") or 2.0, tp)
    mult_buen = opcion_real.multiplo(s["precio"], cot, s.get("mfe_p90") or 0, tp)
    mult_mejor = opcion_real.multiplo(s["precio"], cot, s.get("mfe_max") or 0, tp)
    st.markdown(
        f"**⚖️ Riesgo pequeño, beneficio grande** (el corazón del método):\n"
        f"- 🛡️ **Riesgo topado:** máximo pierdes **${pr['costo']}**. Ni un centavo más, pase lo que pase.\n"
        f"- 🎯 Caso típico: **×{mult_tip}** → ${pr['costo']} se vuelve **${round(pr['costo']*mult_tip):,}**\n"
        f"- 📈 Buen caso: **×{mult_buen}** → **${round(pr['costo']*mult_buen):,}**\n"
        f"- 🚀 Mejor caso histórico: **×{mult_mejor}** → **${round(pr['costo']*mult_mejor):,}**")

    # --- Valor Esperado + factibilidad de cada multiplicador ---
    if h and not h.get("sin_datos"):
        ve = opcion_real.valor_esperado(s["precio"], cot, h["targets"], s.get("mfe_max") or 0, tp)
        p2 = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 2, tp)
        p3 = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 3, tp)
        p5 = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 5, tp)
        p10 = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 10, tp)
        color_ve = "🟢" if ve >= 1.2 else ("🟡" if ve >= 1.0 else "🔴")
        st.markdown(f"**💡 Valor Esperado: {color_ve} ×{ve}**  "
                    f"— la MEJOR forma de comparar. Combina probabilidad y tamaño de ganancia en un número. "
                    f"Por cada $1 que arriesgas, esperas **${ve}** en promedio (>1 = tienes ventaja).")
        def fmt_d(d):
            if d is None:
                return "—"
            if d < 0.4:
                return "horas"
            if d < 1.5:
                return "~1 día"
            return f"~{d:.0f} días"
        t2 = opcion_real.tiempo_de_multiplo(s["precio"], cot, h["targets"], 2, tp)
        t3 = opcion_real.tiempo_de_multiplo(s["precio"], cot, h["targets"], 3, tp)
        t5 = opcion_real.tiempo_de_multiplo(s["precio"], cot, h["targets"], 5, tp)
        t10 = opcion_real.tiempo_de_multiplo(s["precio"], cot, h["targets"], 10, tp)
        # 📊 EL MAPA DE DECISIÓN (visual: probabilidad vs tiempo)
        st.markdown("**📊 Mapa de decisión — probabilidad vs. tiempo**")
        grafico_prob_tiempo(s, cot, h, tp, key=f"{s['ticker']}_{s['estrategia']}")

        with st.expander("Ver los mismos números en tabla"):
          fp = pd.DataFrame([
            {"Multiplicar": "×2 (doblar, +100%)", "Probabilidad": f"{p2}%", "⏱️ Tiempo típico": fmt_d(t2)},
            {"Multiplicar": "×3 (+200%)", "Probabilidad": f"{p3}%", "⏱️ Tiempo típico": fmt_d(t3)},
            {"Multiplicar": "×5 (+400%)", "Probabilidad": f"{p5}%", "⏱️ Tiempo típico": fmt_d(t5)},
            {"Multiplicar": "×10 (+1000%)", "Probabilidad": f"{p10}%", "⏱️ Tiempo típico": fmt_d(t10)},
          ])
          st.dataframe(fp, hide_index=True, use_container_width=True)
          st.caption("El multiplicador SIN el tiempo engaña: un ×2 en ~1 día es un negoción; "
                     "un ×2 en ~7 días, según tu regla, no vale la pena.")
        # --- la opción AGRESIVA (billete de lotería) — en desplegable para no cargar de más ---
        # ═══ 🪜 LA ESCALERA DE VENTA — así se llega a los ×10 (sostener) ═══
        n_esc = int(st.session_state.get(f"nc_{s['ticker']}_{s['estrategia']}", 4) or 4)
        escalera_de_venta(cot["premium"], max(2, n_esc), h, s, tp, cot)

        # ═══ 🎰 Y aparte, la lotería barata (opcional, tajada chica) ═══
        jugada_x10(s, h, tp)

        with st.expander("Comparar en detalle balanceada vs agresiva"):
          cot_ag = cotizacion_agresiva(s["ticker"], o["tipo"], s["precio"])
          if not cot_ag:
            st.caption("No pude cotizar la opción agresiva ahora.")
          else:
            costo_ag = round(cot_ag["premium"] * 100)
            ve_ag = opcion_real.valor_esperado(s["precio"], cot_ag, h["targets"], s.get("mfe_max") or 0, tp)
            p10_ag = opcion_real.prob_de_multiplo(s["precio"], cot_ag, h["targets"], 10, tp)
            p5_ag = opcion_real.prob_de_multiplo(s["precio"], cot_ag, h["targets"], 5, tp)
            mult_ag = opcion_real.multiplo(s["precio"], cot_ag, s.get("mfe_max") or 0, tp)
            comp = pd.DataFrame([
                {"Opción": "🎯 Balanceada", "Strike": f"{cot['strike']} (~1.5% OTM)",
                 "Cuesta": f"${pr['costo']}", "Prob ×5": f"{p5}%", "Prob ×10": f"{p10}%",
                 "Mejor caso": f"×{mult_mejor}", "Valor Esperado": f"×{ve}"},
                {"Opción": "🎰 Agresiva", "Strike": f"{cot_ag['strike']} (~6% OTM, {cot_ag['dias']}d)",
                 "Cuesta": f"${costo_ag}", "Prob ×5": f"{p5_ag}%", "Prob ×10": f"{p10_ag}%",
                 "Mejor caso": f"×{mult_ag}", "Valor Esperado": f"×{ve_ag}"},
            ])
            st.dataframe(comp, hide_index=True, use_container_width=True)
            if ve_ag > ve:
                veredicto_ag = (f"👉 Aquí la **agresiva tiene MEJOR valor esperado (×{ve_ag} vs ×{ve})** — porque "
                                f"{s['ticker']} se mueve fuerte y la opción barata captura ese movimiento grande. "
                                "Aun así, es más volátil: úsala con posición pequeña.")
            else:
                veredicto_ag = (f"👉 Aquí la **balanceada gana en valor esperado (×{ve} vs ×{ve_ag})** — el ×10 se ve "
                                "lindo pero, en promedio, no compensa. Pagas por el sueño. Trátala como lotería.")
            st.caption(f"La **agresiva** cuesta menos (**${costo_ag}**) y SÍ puede hacer ×10 (prob {p10_ag}%). "
                       + veredicto_ag +
                       " Idea pro ('barbell'): la mayoría en balanceadas + una apuesta chica en agresivas.")

    # --- tabla: si la acción se mueve X%, con QUÉ PROBABILIDAD, EN QUÉ TIEMPO, y cuánto ganas ---
    probs, tiempos, n_muestra = {}, {}, 0
    if h and not h.get("sin_datos"):
        probs = {t: d["win_rate"] for t, d in h["targets"].items()}
        tiempos = {t: d["dias_mediana"] for t, d in h["targets"].items()}
        n_muestra = h["n"]

    def etiqueta_prob(p):
        if p is None:
            return "—"
        # mostrar la FRACCIÓN real (ej. "100% (7/7)") para que se vea la muestra
        frac = f" ({round(p/100*n_muestra)}/{n_muestra})" if n_muestra else ""
        if p >= 70:
            cara = "🟢"
        elif p >= 45:
            cara = "🟡"
        elif p >= 20:
            cara = "🟠"
        else:
            cara = "🔴"
        return f"{p:.0f}%{frac} {cara}"

    def fmt_dias(d):
        if d is None:
            return "—"
        if d < 0.4:
            return "horas (mismo día)"
        if d < 1.5:
            return "~1 día"
        return f"~{d:.0f} días"

    esc = opcion_real.tabla_escenarios(s["precio"], cot, o["tipo"], movimientos=(1, 2, 3, 5))
    flecha = esc[0]["dir_accion"] if esc else "se mueve"
    st.markdown(f"**Si la acción {flecha}… con qué probabilidad, en qué tiempo, y cuánto ganas:**")
    filas = [{
        f"Acción {flecha}": f"{r['mov_accion']}%",
        "📊 Prob. histórica": etiqueta_prob(probs.get(float(r["mov_accion"]))),
        "⏱️ Tiempo típico": fmt_dias(tiempos.get(float(r["mov_accion"]))),
        "📈 Contrato": f"+{r['opcion_pct']}%",
        "💵 Ganas": f"+${r['ganancia']:,}",
    } for r in esc]
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)

    # advertencia anti-exceso-de-confianza
    if n_muestra and n_muestra < 15 and any(p >= 95 for p in probs.values()):
        st.warning(f"⚠️ Un **100%** aquí significa *'pasó en las {n_muestra} veces que se dio esta señal'* — "
                   "una muestra **pequeña**, NO una garantía. El mercado no está obligado a repetir. "
                   "Además es el movimiento de la ACCIÓN, no tu ganancia asegurada. **No existe el trade seguro.**")

    # --- la lectura clave: qué se mueve típicamente y hasta dónde puede llegar ---
    if h and not h.get("sin_datos"):
        signo = "+" if o["tipo"] == "CALL" else "−"
        st.success(
            f"📖 **Lectura:** cuando esta señal apareció ({h['n']} veces), la acción se movió a tu favor "
            f"**típicamente {signo}{h['mfe_mediana']:.1f}%**, en un buen caso **{signo}{h['mfe_p90']:.1f}%**, "
            f"y en el mejor caso histórico llegó a **{signo}{h['mfe_max']:.1f}%**. "
            f"Que {flecha} {esc[-1]['mov_accion']}% o más pasa el "
            f"**{probs.get(5.0, 0):.0f}%** de las veces.")
    st.caption(f"🎯 Regla de salida: con **{pr['mov_para_50']}%** a tu favor, la opción va +50% → vendes la mitad "
               f"y aseguras ~**${pr['ganancia_50']}**.  ·  ⚠️ Pérdida máxima: **${pr['riesgo_max']}**.")
    st.caption("El % de la ACCIÓN define el % del CONTRATO. La probabilidad viene del histórico de esta señal. "
               "Estimación con apalancamiento (ignora el desgaste del tiempo); es una guía, no una promesa.")


def medidor_historico(s: dict):
    """Muestra la probabilidad histórica de la señal: cuántas veces se movió a favor y en cuánto tiempo."""
    h = historial(s["ticker"], s["estrategia"])
    st.markdown("#### 📊 Probabilidad histórica")
    if h.get("sin_datos"):
        st.caption(f"No hay suficiente histórico para medir esta señal ({h.get('motivo','')}).")
        return
    p = h["principal"]
    tp = h["target_principal"]
    dias = f"~{p['dias_mediana']:.1f} días" if p["dias_mediana"] is not None else "n/d"

    st.caption(f"Cada vez que ESTA señal apareció en el histórico ({h['n']} veces), "
               f"esto fue lo que pasó después, dentro de la ventana de {h['ventana_dias']} días:")
    a, b, cc = st.columns(3)
    a.metric(f"Se movió a favor ≥{tp}%", f"{p['win_rate']:.0f}%",
             help="Porcentaje de veces que el precio del activo subió (call) o bajó (put) al menos esto.")
    b.metric("Tiempo típico", dias, help="Mediana de días que tardó en darse el movimiento.")
    cc.metric("Apariciones", h["n"], help="Cuántas veces se disparó esta señal en el histórico disponible.")

    # tabla de umbrales
    filas = []
    for t, d in h["targets"].items():
        dm = f"{d['dias_mediana']:.1f} d" if d["dias_mediana"] is not None else "—"
        filas.append({"Movimiento a favor": f"≥ {t}%", "% de veces": f"{d['win_rate']:.0f}%", "Tiempo típico": dm})
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)

    st.markdown(f"- Movimiento **a favor** típico: **+{h['mfe_mediana']:.1f}%**  ·  "
                f"peor movimiento **en contra**: **{h['mae_mediana']:.1f}%**")
    if h["n"] < 12:
        st.caption("⚠️ Muestra pequeña: son pocas apariciones, así que estos porcentajes son una guía, "
                   "no una ley. Se afinan con más histórico y con tu propia bitácora.")
    st.caption("Mide el movimiento del ACTIVO (no la prima exacta de la opción). Si el movimiento tarda "
               "muchos días, el decaimiento temporal se come parte de la ganancia — por eso importa el tiempo.")


def grafico(señal: dict):
    """Gráfica grande y anotada que explica la señal (usa engine/viz)."""
    intervalo = ESTRATEGIAS[señal["estrategia"]]["intervalo"]
    df = cargar(señal["ticker"], intervalo)
    n = 70 if intervalo == "1h" else 55
    return viz.figura_detallada(df, señal, n_velas=n)


# Bloques de correlación: activos que en la práctica se mueven JUNTOS.
# OJO: SPY y QQQ CONTIENEN a las mega-caps de tecnología (son sus mayores pesos),
# así que SPY/QQQ + una mega-cap = doble apuesta a lo mismo, no diversificación.
_TECH_GRANDE = {"QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA",
                "AMD", "NFLX", "QCOM", "MU", "MRVL", "INTC", "SMCI", "ADBE", "CRM",
                "NOW", "PLTR", "CRWD", "ARM", "TSM", "SNOW", "SHOP"}
_GRUPOS_CORR = {
    "tecnología grande": _TECH_GRANDE,
    "cripto": {"COIN", "MSTR", "MARA"},
    "energía / petróleo": {"XOM", "CVX", "USO"},
    "metales": {"GLD", "SLV"},
    "especulativas": {"GME", "SOFI", "RIVN"},
}


def _grupo_corr(tk: str):
    tk = tk.upper()
    for nombre, conj in _GRUPOS_CORR.items():
        if tk in conj:
            return nombre
    return None


def choque_correlacion(ticker: str, abiertos: list[str]) -> list[str]:
    """
    Nota SUAVE de correlación (no es un bloqueo). Las mega-caps son empresas
    independientes con vida propia; solo tienden a moverse juntas en días de
    MERCADO (correlación ~0.7, no 1.0). Es un dato para tener en cuenta, no un
    'estás doblando la apuesta'.
    """
    tk = ticker.upper()
    ab = {a.upper() for a in abiertos if a.upper() != tk}
    avisos = []
    g = _grupo_corr(tk)
    if g:
        mismos = sorted(a for a in ab if _grupo_corr(a) == g)
        if mismos:
            avisos.append(f"{tk} y {', '.join(mismos)} son «{g}»: tienden a moverse juntas en un "
                          "día de mercado (no en el día a día). No es la misma apuesta, pero tenlo presente.")
    if tk in _TECH_GRANDE and "SPY" in ab:
        avisos.append(f"El SPY ya incluye algo de {tk} (es de sus mayores pesos), así que esta lo refuerza un poco.")
    return avisos


@st.cache_data(ttl=60, show_spinner=False)
def estado_cartera() -> dict:
    """
    Tu situación AHORA: cuántas posiciones tienes abiertas, cuántas operaciones
    abriste esta semana y en qué activos. El veredicto lo necesita: una señal
    puede ser perfecta y aun así no debes tomarla si ya tienes el cupo lleno.
    """
    from datetime import date, timedelta
    abiertas = [t for lib in ("real", "simulacion") for t in bitacora.listar(lib, "abierta")]
    hoy = date.today()
    lunes = (hoy - timedelta(days=hoy.weekday())).isoformat()
    todas = [t for lib in ("real", "simulacion") for t in bitacora.listar(lib)]
    semana = [t for t in todas if (t.get("fecha_entrada") or "")[:10] >= lunes]
    desplegado = sum(float(t.get("prima_entrada") or 0) * 100 * int(t.get("contratos") or 0)
                     for t in abiertas)
    return {"abiertas": len(abiertas),
            "tickers": sorted({t["ticker"] for t in abiertas}),
            "esta_semana": len(semana),
            "desplegado": round(desplegado)}


def veredicto_compra(s: dict) -> dict:
    """
    ⚖️ EL VEREDICTO ÚNICO: ¿es esta una de las 2-4 BUENAS de la semana?
    Junta todos los filtros en UNA respuesta, y explica el porqué.

    OBLIGATORIAS (si falla una, se pasa):
      1. Entrada CONFIRMADA (zona + ruptura del método)
      2. Valor esperado >= 1.2 (tiene ventaja matemática)
      3. Probabilidad de DOBLAR >= 50%
      4. Muestra suficiente (>= 12 casos históricos)
    DE CALIDAD (si fallan, baja a DUDOSA pero no la mata):
      5. Dobla en <= 3 días   6. Señal fresca   7. Contrato líquido
    """
    ok, falla, ojo = [], [], []

    # --- 1) confirmada ---
    if s.get("estado") == "ENTRADA":
        ok.append("Entrada confirmada (zona + ruptura)")
    else:
        falla.append("Aún no confirma la ruptura — todavía no es entrada")

    # --- 2) ventaja matemática ---
    ve = s.get("_ve")
    if ve is None:
        falla.append("Sin datos para calcular la ventaja (valor esperado)")
    elif ve >= 1.2:
        ok.append(f"Ventaja matemática buena (×{ve} por cada $1)")
    else:
        falla.append(f"Ventaja insuficiente (×{ve}; se pide ×1.2)")

    # --- 3) probabilidad de doblar ---
    p2, t2 = s.get("_p_x2"), s.get("_t_x2")
    if p2 is None:
        falla.append("Sin histórico para estimar la probabilidad de doblar")
    elif p2 >= 50:
        ok.append(f"Buena probabilidad de doblar ({p2:.0f}%)")
    else:
        falla.append(f"Probabilidad de doblar baja ({p2:.0f}%; se pide 50%)")

    # --- 4) muestra ---
    n = s.get("n_muestra", 0) or 0
    if n >= 12:
        ok.append(f"Muestra confiable ({n} casos históricos)")
    else:
        falla.append(f"Muestra muy chica ({n} casos) — el % no es de fiar")

    # --- 5) velocidad ---
    if t2 is not None:
        if t2 <= 3:
            ok.append(f"Rápida: dobla en ~{t2:.0f} día(s)")
        else:
            ojo.append(f"Lenta: tarda ~{t2:.0f} días en doblar")

    # --- 6) liquidez del contrato ---
    cot = s.get("_cot") or {}
    if cot.get("liquido"):
        ok.append("Contrato líquido (fácil de entrar y salir)")
    elif cot.get("interes_abierto") is not None:
        ojo.append("Contrato poco líquido — el spread te puede comer")

    # --- 7) EARNINGS dentro de la vida de la opción -> BLOQUEA (endurecido) ---
    # Es el único riesgo real de operar acciones y no del SPY: un reporte mueve
    # la acción de forma impredecible. Si cae dentro de la vida de la opción, se pasa.
    try:
        es_accion = UNIVERSO.get(s["ticker"], {}).get("clase") == "accion"
        earn = earnings_ctx(s["ticker"], s["opcion"]["dias_vencimiento"], es_accion)
        if earn.get("nivel") == "riesgo":
            falla.append("Reporte de resultados dentro de la vida de la opción — riesgo impredecible, pásala")
    except Exception:
        pass

    # --- 8) TU SITUACIÓN: ¿te toca tomarla? (cupo). La correlación va como NOTA suave ---
    frena_cartera = []
    notas = []
    try:
        c = estado_cartera()
        if c["abiertas"] >= 4:
            frena_cartera.append(f"Ya tienes {c['abiertas']} posiciones abiertas — guarda pólvora seca")
        if c["esta_semana"] >= 4:
            frena_cartera.append(f"Ya abriste {c['esta_semana']} esta semana — el método pide 2-4, no más")
        if s["ticker"] in c["tickers"]:
            frena_cartera.append(f"Ya tienes una posición abierta en {s['ticker']} — no concentres")
        # correlación: SOLO informa (no baja el veredicto ni frena)
        notas = choque_correlacion(s["ticker"], c["tickers"])
    except Exception:
        pass

    # --- ¿es EXCEPCIONAL? (lo bastante buena para justificar romper el cupo) ---
    excepcional = (ve is not None and ve >= 1.6 and p2 is not None and p2 >= 65
                   and n >= 20 and t2 is not None and t2 <= 3)

    # --- veredicto ---
    # El cupo AVISA, no bloquea: la decisión final es de Oscar. Pero le decimos
    # con claridad si la señal es lo bastante buena para justificar la excepción.
    if frena_cartera and not falla:
        if excepcional:
            return {"nivel": "tomala", "titulo": "🟢 TÓMALA — vale la excepción",
                    "resumen": ("Estás sobre tu cupo, PERO esta señal es excepcional "
                                "(ventaja alta, muy probable, rápida y con muestra grande). "
                                "Si vas a romper el cupo alguna vez, es por una así."),
                    "ok": ok, "falla": [], "ojo": ojo + frena_cartera, "notas": notas}
        return {"nivel": "espera", "titulo": "🟠 BUENA — pero vas sobre tu cupo",
                "resumen": ("La señal cumple, pero no es excepcional y ya vas sobre el ritmo del "
                            "método. **Tú decides**: lo prudente es guardar el turno."),
                "ok": ok, "falla": [], "ojo": ojo + frena_cartera, "notas": notas}
    if falla:
        nivel, titulo = "pasa", "⚪ PÁSALA — no es de las buenas"
        resumen = "No cumple lo mínimo. Esperar es la jugada correcta."
    elif ojo:
        nivel, titulo = "dudosa", "🟡 DUDOSA — solo si no hay algo mejor"
        resumen = "Cumple lo esencial, pero tiene peros. Si hay otra mejor hoy, prefiere esa."
    else:
        nivel, titulo = "tomala", "🟢 TÓMALA — es de las buenas de la semana"
        resumen = "Cumple TODO. Esta es de las 2-4 que vale la pena tomar."
    return {"nivel": nivel, "titulo": titulo, "resumen": resumen,
            "ok": ok, "falla": falla, "ojo": ojo, "notas": notas}


def grafico_prob_tiempo(s: dict, cot: dict, h: dict, tp: str, key: str):
    """
    📊 EL MAPA DE DECISIÓN: probabilidad (eje Y) vs tiempo (eje X) para cada meta.
    De un vistazo ves el trade-off: arriba-izquierda = rápido y probable (bueno);
    abajo-derecha = lento e improbable (malo). La zona verde es donde vale la pena.
    """
    import plotly.graph_objects as go
    metas = [("×1.5", 1.5), ("×2 (dobla)", 2), ("×3", 3), ("×5", 5), ("×10", 10)]
    xs, ys, txt, cols = [], [], [], []
    for etiqueta, n in metas:
        p = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], n, tp)
        t = opcion_real.tiempo_de_multiplo(s["precio"], cot, h["targets"], n, tp)
        if p is None or t is None or p <= 0:
            continue
        xs.append(round(float(t), 1)); ys.append(float(p)); txt.append(etiqueta)
        # verde si es rápido Y probable; ámbar si uno de los dos; gris si ninguno
        cols.append("#0E7C6B" if (t <= 3 and p >= 60) else
                    ("#B8860B" if (t <= 5 and p >= 40) else "#9AA0A6"))
    if not xs:
        return
    fig = go.Figure()
    # zona "vale la pena": rápido (≤3 días) y probable (≥60%)
    fig.add_shape(type="rect", x0=0, x1=3, y0=60, y1=100, fillcolor="#0E7C6B",
                  opacity=.10, line=dict(width=0), layer="below")
    fig.add_annotation(x=1.5, y=95, text="ZONA BUENA<br>rápido y probable",
                       showarrow=False, font=dict(size=10, color="#0E7C6B"))
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=txt, textposition="top center",
        textfont=dict(size=12, color="#3A3F47"),
        marker=dict(size=[max(14, min(30, p / 3)) for p in ys], color=cols,
                    line=dict(width=2, color="white")),
        hovertemplate="<b>%{text}</b><br>%{y:.0f}% de probabilidad<br>en ~%{x} días<extra></extra>"))
    fig.update_layout(
        height=330, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(title="⏱️ Días que tarda", gridcolor="#E9EDEE", zeroline=False,
                   range=[0, max(xs) * 1.25 + .5]),
        yaxis=dict(title="🎯 Probabilidad (%)", gridcolor="#E9EDEE", range=[0, 105], zeroline=False),
        showlegend=False)
    st.plotly_chart(fig, use_container_width=True, key=f"pt_{key}")
    st.caption("👉 **Cómo leerlo:** cada burbuja es una meta. Mientras más **arriba**, más probable; "
               "mientras más a la **izquierda**, más rápido. Las de la **zona verde** son las que "
               "valen la pena. Si todas caen abajo-derecha, esa opción es lenta e improbable: **pasa**.")


def _fecha_es(iso: str) -> str:
    """Convierte '2026-07-24' en 'viernes 24-jul' (para leer el vencimiento fácil)."""
    try:
        from datetime import date
        d = date.fromisoformat(iso)
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
        return f"{dias[d.weekday()]} {d.day}-{meses[d.month - 1]}"
    except Exception:
        return iso


def frase_de_decision(s: dict, cot: dict, costo1: int):
    """
    🧠 LA FRASE DE DECISIÓN — la idea de Oscar hecha realidad.
    Todo en una línea, en primer plano: inviertes $X por contrato · tienes P% de
    hacer ×N en D días · te recomiendo K contratos. La decisión, servida.
    """
    tp = cot.get("tipo") or s["opcion"]["tipo"]
    h = historial(s["ticker"], s["estrategia"])
    if h.get("sin_datos"):
        st.info(f"💵 Inviertes **${costo1}** por contrato. Sin histórico suficiente para "
                "estimar probabilidad y tiempo — decide con cuidado.")
        return

    # la meta más informativa: el DOBLAR (×2). Si es muy probable y rápido, mejor.
    p2 = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 2, tp)
    t2 = opcion_real.tiempo_de_multiplo(s["precio"], cot, h["targets"], 2, tp)
    p3 = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 3, tp)

    # cuántos contratos recomiendo (10% de la cuenta)
    cuenta = int(st.session_state.get("cuenta_usd", 1000))
    riesgo = round(cuenta * RIESGO_MAX_CAPITAL_PCT / 100)
    n_rec = max(1, int(riesgo // costo1)) if costo1 else 1
    inv_total = n_rec * costo1

    t_txt = "el mismo día" if (t2 is not None and t2 < 1) else \
            (f"~{t2:.0f} día" + ("s" if (t2 or 0) >= 2 else "")) if t2 is not None else "tiempo incierto"
    p_col = "#0F7A5A" if (p2 or 0) >= 60 else ("#B8860B" if (p2 or 0) >= 45 else "#C0392B")

    st.markdown(
        f"<div style='background:{p_col}12;border:1.5px solid {p_col};border-radius:12px;"
        f"padding:15px 18px;margin:6px 0;line-height:1.6'>"
        f"<div style='font-size:.72rem;letter-spacing:.1em;color:{p_col};font-weight:700'>TU DECISIÓN, EN UNA LÍNEA</div>"
        f"<div style='font-size:1.16rem;color:var(--text-color,inherit);margin-top:4px'>"
        f"Inviertes <b>${costo1}</b> por contrato · "
        f"tienes <b style='color:{p_col}'>{p2:.0f}%</b> de <b>doblar (×2)</b> en <b>{t_txt}</b> · "
        f"el sistema te dirá abajo <b>cuántos comprar</b> ({n_rec} con tu cuenta actual)."
        f"</div></div>", unsafe_allow_html=True)

    # la traducción a plata concreta
    c1, c2, c3 = st.columns(3)
    c1.metric("Si dobla (×2)", f"+${inv_total}", help="Ganancia neta si llega al ×2 (además recuperas tu inversión).")
    c2.metric("Prob. de ×3", f"{p3:.0f}%", help="Y de ahí en adelante, con la escalera, puede seguir.")
    c3.metric("Arriesgas (topado)", f"${inv_total}", help="Lo máximo que puedes perder. Ni un centavo más.")


def orden_de_compra(s: dict):
    """
    La ORDEN clara: exactamente QUÉ contrato comprar. Separa lo CONFIABLE (el
    contrato: tipo + activo + strike + vencimiento, que tecleas tal cual en uCharts)
    de lo ESTIMADO (la prima en $, que confirmas en el bróker).
    """
    o = s["opcion"]
    tipo = o["tipo"]
    emoji = "🟢" if tipo == "CALL" else "🔴"
    # REGLA DE CARDONA (día 2): el contrato se elige por PRECIO DE LA PRIMA,
    # no por % fuera del dinero. Si falla, caemos al método anterior.
    cot = cotizacion_por_prima(s["ticker"], tipo, s["precio"], o["dias_vencimiento"]) \
        or s.get("_cot") or cotizacion(s["ticker"], o["tipo"], o["strike"], o["dias_vencimiento"])
    with st.container(border=True):
        st.markdown(f"#### {emoji} ORDEN DE COMPRA")
        if not cot:
            st.warning(
                f"**{tipo} {s['ticker']}** · strike aproximado **~{o['strike']}** (~{o['otm_pct']}% OTM) · "
                f"vencimiento **~{o['dias_vencimiento']} días**.\n\n"
                "No pude traer la cadena real ahora mismo — busca en uCharts el strike más cercano "
                "y el vencimiento semanal más próximo. Refresca en un momento para la orden exacta.")
            return
        prima = cot["premium"]
        costo1 = round(prima * 100)
        venc = _fecha_es(cot["exp"])
        st.markdown(f"## {tipo} · {s['ticker']} · strike {cot['strike']}")
        st.markdown(f"**Vence {venc}** · en {cot['dias']} días")

        # ═══ 🧠 LA FRASE DE DECISIÓN — todo en una línea, en primer plano ═══
        frase_de_decision(s, cot, costo1)

        # ⏱️ FRESCURA: ¿cuánto tiempo llevas para actuar sobre esta señal?
        try:
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            _ET = _tz(_td(hours=-4))
            t_senal = pd.to_datetime(s["fecha"])
            t_senal = t_senal.tz_convert(_ET) if t_senal.tzinfo else t_senal.tz_localize(_ET)
            mins = (_dt.now(_ET) - t_senal.to_pydatetime()).total_seconds() / 60
            intradia_s = ESTRATEGIAS[s["estrategia"]]["intervalo"] in ("1h", "30m")
            if intradia_s and mins >= 0:
                if mins <= 20:
                    st.success(f"⏱️ **Señal FRESCA** (hace {mins:.0f} min) — este es el mejor momento para entrar.")
                elif mins <= 60:
                    st.warning(f"⏱️ Señal de hace **{mins:.0f} min** — todavía sirve, pero entra ya: "
                               "mientras más esperas, peor el precio.")
                else:
                    st.error(f"⌛ Señal de hace **{mins/60:.1f} h** — **ya pasó su momento.** "
                             "No la persigas; espera la próxima.")
        except Exception:
            pass
        a, b = st.columns(2)
        a.success(
            "**✅ Esto es EXACTO — tecléalo así en uCharts:**\n\n"
            f"- Tipo: **{tipo}**\n"
            f"- Activo: **{s['ticker']}**\n"
            f"- Strike: **{cot['strike']}**\n"
            f"- Vencimiento: **{cot['exp']}** ({venc})")
        # precio REAL de compra (el ask) + transparencia de spread y liquidez
        bid, ask = cot.get("bid"), cot.get("ask")
        sp, sp_pct = cot.get("spread"), cot.get("spread_pct")
        liq = cot.get("liquido")
        detalle = f"- **Pagas: ${prima}** por acción (precio ASK real)\n" \
                  f"- **1 contrato = ${costo1}**\n"
        if bid and ask:
            detalle += f"- Compra/venta: bid ${bid} · ask ${ask}"
            if sp is not None:
                detalle += f" · spread ${sp} ({sp_pct}%)\n"
            else:
                detalle += "\n"
        if cot.get("interes_abierto"):
            detalle += f"- Contratos abiertos: {cot['interes_abierto']:,} " \
                       f"{'✅ líquido' if liq else '⚠️ poco líquido'}\n"
        b.info("**💵 Precio REAL de compra:**\n\n" + detalle +
               "\nEste es el **ask del mercado** — lo que pagas al comprar ahora. "
               "Puede moverse unos centavos; confírmalo al ejecutar.")
        # ═══ 🎯 LA DECISIÓN DEL SISTEMA: cuántos comprar (regla del 10%, no tú) ═══
        # Tu capital, editable AQUÍ mismo y GLOBAL (queda igual en todas las fichas).
        cc = st.columns([1, 1])
        cuenta = cc[0].number_input(
            "💼 Mi capital disponible ($)", min_value=100,
            value=int(st.session_state.get("cuenta_usd", 1000)), step=100,
            key=f"cta_{s['ticker']}_{s['estrategia']}",
            help="Cámbialo cuando quieras. Se aplica a TODAS las fichas y recalcula la cantidad al instante.")
        if cuenta != st.session_state.get("cuenta_usd"):
            st.session_state["cuenta_usd"] = cuenta      # global para todas las fichas
        cc[1].metric("Riesgo por operación",
                     f"${round(cuenta * RIESGO_MAX_CAPITAL_PCT / 100)}",
                     help=f"El {RIESGO_MAX_CAPITAL_PCT}% de tu capital — lo máximo que arriesgas en esta.")

        riesgo = round(cuenta * RIESGO_MAX_CAPITAL_PCT / 100)
        n_cont = max(1, int(riesgo // costo1)) if costo1 else 1
        inv = n_cont * costo1
        st.markdown(
            f"<div style='background:#0F7A5A;color:white;border-radius:12px;padding:16px 20px;margin:6px 0'>"
            f"<div style='font-size:.72rem;letter-spacing:.1em;opacity:.85;font-weight:700'>EL SISTEMA DECIDE</div>"
            f"<div style='font-size:1.5rem;font-weight:800;margin-top:2px'>COMPRA {n_cont} CONTRATO{'S' if n_cont>1 else ''}</div>"
            f"<div style='opacity:.92;margin-top:2px'>Inviertes ${inv} · arriesgas ${inv} (topado) · "
            f"= el {RIESGO_MAX_CAPITAL_PCT}% de tu cuenta de ${cuenta:,}</div></div>",
            unsafe_allow_html=True)
        st.caption(f"No lo decides tú: **la regla del {RIESGO_MAX_CAPITAL_PCT}% lo calcula.** "
                   f"${riesgo} de riesgo ÷ ${costo1} por contrato = {n_cont}.")

        # --- UN CLIC: comprar esa cantidad exacta y registrar ---
        bc = st.columns([1.4, 1])
        libro_r = bc[1].selectbox("Libro", ["simulacion", "real"],
                                  key=f"lb_{s['ticker']}_{s['estrategia']}")
        if bc[0].button(f"📔 Compré {n_cont} — registrar en bitácora",
                        key=f"reg_{s['ticker']}_{s['estrategia']}", use_container_width=True):
            bitacora.agregar(libro_r, s["ticker"], s["direccion"], s["estrategia"],
                             cot["strike"], prima, int(n_cont),
                             nota=f"{s['estrategia_nombre']} · registrada desde la orden",
                             vencimiento=cot["exp"])
            st.success(f"✅ Registrada: {tipo} {s['ticker']} {cot['strike']} × {n_cont} "
                       f"a ${prima} · vence {cot['exp']}. El Vigilante ya te avisará cuándo vender.")
        # guardamos la cantidad para que la escalera use el mismo número
        st.session_state[f"nc_{s['ticker']}_{s['estrategia']}"] = n_cont


def tarjeta(s: dict):
    c = COLOR[s["estado"]]
    meta = UNIVERSO.get(s["ticker"], {})
    nombre = meta.get("nombre", s["ticker"])
    idx_badge = {"ETF": "ETF", "SP500": "🟦 S&P 500", "FUERA": "🧪 Fuera del S&P 500"}.get(meta.get("indice", ""), "")
    with st.container(border=True):
        cols = st.columns([3, 1, 1, 1])
        est_meta = ESTRATEGIAS[s["estrategia"]]
        titulo = f"### {ICONO[s['estado']]} {s['ticker']} — {s['direccion'].upper()}\n**{nombre}**  ·  {idx_badge}  ·  {s['estrategia_nombre']} {est_meta.get('ritmo','')}"
        if "oportunidad" in s:
            titulo += f"  ·  🎯 Oportunidad **{s['oportunidad']}/100**"
        cols[0].markdown(titulo)
        cols[0].caption(f"{est_meta.get('ritmo','')} — {est_meta.get('ritmo_txt','')}")
        n_ok = sum(1 for v in s["checklist"].values() if v["ok"])
        cols[1].metric("Condiciones", f"{n_ok} de 5")
        cols[2].metric("Precio", f"{s['precio']:.2f}")
        cols[3].markdown(f"<h4 style='color:{c}'>{s['estado']}</h4>", unsafe_allow_html=True)

        if "beneficio_pct" in s:
            br = s.get("ratio_br")
            br_txt = f"  ·  ⚖️ Ganas/arriesgas: **{br}x**" if br else ""
            st.caption(f"💥 A favor típico: **+{s['beneficio_pct']}%**  ·  "
                       f"🛡️ En contra típico: **{s.get('riesgo_pct','?')}%**  ·  "
                       f"📅 En 1 día: **+{s.get('beneficio_1d',0)}%**{br_txt}  ·  "
                       f"confiabilidad: **{s['confiabilidad_pct']:.0f}%**")
            # desglose del score de Oportunidad (para que se entienda el ranking)
            comp_b = screener.W_BENEFICIO * min(s["beneficio_pct"] / 8 * 100, 100)
            comp_c = screener.W_CONFIABILIDAD * s["confiabilidad_pct"]
            comp_m = screener.W_METODO * (s["n_cond"] / 5 * 100)
            st.caption(f"🎯 **Oportunidad {s['oportunidad']}** se arma así: "
                       f"💥 rentabilidad **{comp_b:.0f}** (de 40) + 🛡️ confiabilidad **{comp_c:.0f}** (de 35) + "
                       f"📋 condiciones **{comp_m:.0f}** (de 25). Por eso una 3/5 muy rentable y confiable "
                       "puede ir arriba de una 4/5 mediocre.")
            cf = s.get("confianza", {})
            nm = s.get("n_muestra", 0)
            st.caption(f"📊 Confiabilidad: **{s['confiabilidad_pct']:.0f}% observada** en **{nm} casos** "
                       f"{cf.get('emoji','')} ({cf.get('label','')}). Ajustada por el tamaño de muestra: "
                       f"**{s.get('confiab_ajustada', s['confiabilidad_pct']):.0f}%** ← esta es la que usa el ranking, "
                       "porque una muestra chica no es tan de fiar.")

        st.progress(n_ok / 5)

        # --- contexto en vivo (pre-market / mercado abierto) ---
        ctx = contexto_vivo(s["ticker"])
        ctx_ev = premarket.evaluar(ctx, s["direccion"])
        # --- contexto de calendario (evento grande próximo) ---
        cal_ctx = calendario()["contexto"]
        # --- contexto de earnings (riesgo de empresa única, solo acciones) ---
        es_accion = UNIVERSO.get(s["ticker"], {}).get("clase") == "accion"
        earn = earnings_ctx(s["ticker"], s["opcion"]["dias_vencimiento"], es_accion)

        # --- veredicto, AJUSTADO por contexto en vivo, calendario y earnings ---
        vd = viz.veredicto(s)
        contradice_pm = ctx_ev["nivel"] == "contradice"
        riesgo_cal = cal_ctx["nivel"] in ("peligro", "precaucion")
        riesgo_earn = earn["nivel"] == "riesgo"

        if vd["nivel"] == "go" and (contradice_pm or riesgo_cal or riesgo_earn):
            motivos = ""
            if contradice_pm:
                motivos += f"\n\n{ctx_ev['texto']}"
            if riesgo_cal:
                motivos += f"\n\n{cal_ctx['texto']}"
            if riesgo_earn:
                motivos += f"\n\n{earn['texto']}"
            st.error(f"### ⚠️ CUIDADO — reconfirmar antes de entrar\n"
                     f"El método marca entrada, PERO hay señales para esperar:{motivos}\n\n"
                     "Cardona esperaría a que la apertura confirme y a que pasen los eventos grandes. "
                     "Si sigue así, mejor **NO entrar**.")
        elif vd["nivel"] == "go":
            extra = f"\n\n{ctx_ev['texto']}" if ctx_ev["nivel"] in ("confirma", "neutral") else ""
            st.success(f"### {vd['titulo']}\n{vd['texto']}{extra}")
        elif vd["nivel"] == "wait":
            st.warning(f"### {vd['titulo']}\n{vd['texto']}")
        else:
            st.info(f"### {vd['titulo']}\n{vd['texto']}")

        # línea de contexto en vivo siempre visible
        if ctx.get("ok") and ctx.get("cambio_pct") is not None:
            iconos = {"confirma": "✅", "contradice": "🔴", "neutral": "➖", "sin_dato": "❔"}
            st.caption(f"{iconos.get(ctx_ev['nivel'],'')} **Contexto en vivo** · {ctx['estado_txt']}: "
                       f"{ctx['precio']:.2f} ({ctx['cambio_pct']:+.2f}%) — {ctx_ev['texto']}")
        # línea de earnings para acciones
        if es_accion and earn["nivel"] in ("riesgo", "ok"):
            ico = "⚠️" if earn["nivel"] == "riesgo" else "📆"
            st.caption(f"{ico} **Earnings** · {earn['texto']}")

        # --- ⚖️ EL VEREDICTO: ¿la tomo o la paso? (lo primero que debe leer) ---
        vc = veredicto_compra(s)
        c_ver = {"tomala": "#0F7A5A", "dudosa": "#B8860B", "espera": "#C2703D", "pasa": "#8A8578"}[vc["nivel"]]
        st.markdown(
            f"<div style='background:{c_ver};color:white;border-radius:12px;padding:16px 20px;margin:8px 0'>"
            f"<div style='font-size:1.45rem;font-weight:800'>{vc['titulo']}</div>"
            f"<div style='opacity:.92;margin-top:3px'>{vc['resumen']}</div></div>",
            unsafe_allow_html=True)
        with st.expander("¿Por qué este veredicto?", expanded=(vc["nivel"] != "tomala")):
            for r in vc["falla"]:
                st.markdown(f"❌ {r}")
            for r in vc["ojo"]:
                st.markdown(f"⚠️ {r}")
            for r in vc["ok"]:
                st.markdown(f"✅ {r}")
            for r in vc.get("notas", []):
                st.markdown(f"🔗 *{r}*")
            st.caption("Para ser **de las buenas** tiene que cumplir las 4 obligatorias: entrada "
                       "confirmada · ventaja ×1.2 · 50% de doblar · muestra de 12+ casos.")

        # --- LA ORDEN: exactamente qué contrato comprar (prominente) ---
        orden_de_compra(s)

        izq, der = st.columns(2)
        with izq:
            st.markdown("**Checklist del método** (🔴 obligatoria · 🟡 refuerzo):")
            etiquetas = {"zona": "Zona extrema", "media": "Confluencia con promedio",
                         "soporte": "Soporte/resistencia", "vela": "Vela de señal",
                         "ruptura": "Ruptura confirmada"}
            obligatorias = {"zona", "ruptura"}
            for k, v in s["checklist"].items():
                marca = "✅" if v["ok"] else "⬜️"
                tipo = "🔴" if k in obligatorias else "🟡"
                txt = v["detalle"] if v["ok"] else etiquetas[k] + " — pendiente"
                st.markdown(f"{marca} {tipo} {txt}")
            st.caption("Para ENTRADA se necesitan SÍ o SÍ las dos 🔴 (zona + ruptura). "
                       "Las 🟡 suman calidad, pero no son obligatorias.")
        with der:
            o = s["opcion"]
            st.markdown("**Por qué este contrato:**")
            st.markdown(
                f"- Strike ~{o['otm_pct']}% OTM (fuera del dinero): **barato y apalancado** — "
                "un movimiento chico del activo lo dispara.\n"
                "- Vencimiento corto: más gamma (sube rápido). **Vende al +100% (dobló)** — "
                "ahí recuperas todo — o antes de que venza.\n"
                "- **Riesgo topado en la prima:** nunca pierdes más que lo que pagaste.")

        # Cuánto dinero podrías hacer (con la prima real).
        st.divider()
        panel_dinero(s)

        # Medidor de probabilidad histórica (el "turbo").
        st.divider()
        medidor_historico(s)

        # La gráfica anotada: colapsada por defecto para que la ficha abra rápido.
        st.divider()
        with st.expander(f"📊 Ver la gráfica explicada de {s['ticker']} ({s['marco']})", expanded=False):
            st.plotly_chart(grafico(s), use_container_width=True,
                            key=f"chart_{s['ticker']}_{s['estrategia']}")
            st.markdown(viz.leyenda_markdown(s))


def accion_badge(s: dict) -> tuple[str, str]:
    """Devuelve el nivel de acción de la oportunidad (para la tarjeta compacta)."""
    cal_ctx = calendario()["contexto"]
    es_accion = UNIVERSO.get(s["ticker"], {}).get("clase") == "accion"
    earn = earnings_ctx(s["ticker"], s["opcion"]["dias_vencimiento"], es_accion)
    if s["estado"] == "ENTRADA":
        if cal_ctx["nivel"] in ("peligro", "precaucion") or earn["nivel"] == "riesgo":
            return "cuidado", "⚠️ CUIDADO — reconfirmar"
        return "comprar", "🟢 COMPRAR AHORA"
    return "vigilar", "⏳ VIGILAR — armándose"


@st.cache_data(ttl=180, show_spinner=False)
def reconstruir(ticker: str, est: str) -> dict | None:
    """Reconstruye una oportunidad completa (para la página de ficha en pestaña aparte)."""
    if est not in ESTRATEGIAS or ticker not in UNIVERSO:
        return None
    iv = ESTRATEGIAS[est]["intervalo"]
    try:
        df = method.preparar(data.obtener(ticker, iv))
        s = method.evaluar(ticker, df, est)
    except Exception:
        return None
    try:
        dfd = method.preparar(data.obtener(ticker, "1d"))
        s["volatilidad"] = screener.volatilidad(dfd)
    except Exception:
        s["volatilidad"] = {"mov_diario_mediana": 0}
    s["n_cond"] = sum(1 for v in s["checklist"].values() if v["ok"])
    s["indice"] = UNIVERSO.get(ticker, {}).get("indice", "")
    h = historial(ticker, est)
    if h and not h.get("sin_datos"):
        beneficio = h["mfe_mediana"]; confiab = h["principal"]["win_rate"]; n = h["n"]
        s["beneficio_pct"] = round(beneficio, 1)
        s["confiabilidad_pct"] = round(confiab, 0)
        s["riesgo_pct"] = round(h["mae_mediana"], 1)
        s["beneficio_1d"] = round(h.get("fav_1d_mediana", 0), 1)
        s["mfe_max"] = round(h.get("mfe_max", beneficio), 1)
        s["mfe_p90"] = round(h.get("mfe_p90", beneficio), 1)
        s["n_muestra"] = n
        s["confianza"] = screener.confianza(n)
        s["confiab_ajustada"] = round(screener.confiab_ajustada(confiab, n), 0)
        s["ratio_br"] = round(beneficio / abs(s["riesgo_pct"]), 1) if s["riesgo_pct"] else None
        s["oportunidad"] = screener._oportunidad(s["n_cond"], beneficio,
                                                 screener.confiab_ajustada(confiab, n), s["estado"])
    return s


def render_ficha_pagina(ticker: str, est: str):
    """Renderiza la ficha a pantalla completa (esta es su propia pestaña del navegador)."""
    st.markdown(CABECERA, unsafe_allow_html=True)
    if not ticker or est not in ESTRATEGIAS:
        st.error("Ficha no válida."); return
    with st.spinner("Cargando ficha..."):
        s = reconstruir(ticker, est)
        if not s:
            st.error(f"No pude cargar {ticker}."); return
        o = s["opcion"]
        s["_cot"] = cotizacion(ticker, o["tipo"], o["strike"], o["dias_vencimiento"])
        nombre = UNIVERSO.get(ticker, {}).get("nombre", ticker)
        st.markdown(f"# {ticker} · {o['tipo']}  —  {nombre}")
        tarjeta(s)


def _fmt_dias(d) -> str:
    if d is None:
        return "n/d"
    if d < 0.4:
        return "horas"
    if d < 1.5:
        return "~1 día"
    return f"~{d:.0f} días"


def calificar(s: dict) -> dict:
    """El TOOL es el juez: combina todo en una calificación clara, en palabras.
    Oscar solo la lee, no tiene que pesar números."""
    ve = s.get("_ve")
    p = s.get("_p_recup")          # prob. de recuperar (+50%)
    t = s.get("_t_recup")          # tiempo a recuperar
    n = s.get("n_muestra", 0)      # tamaño de muestra
    if ve is None:
        return {"emoji": "⚪", "titulo": "SIN DATOS",
                "color": "#8A8578", "resumen": "No hay suficiente histórico para calificarla."}
    prob = p if p is not None else 0
    # nivel según VE (edge) + probabilidad de recuperar (seguridad)
    if ve >= 1.5 and prob >= 80 and n >= 12:
        nivel = {"emoji": "🟢", "titulo": "EXCELENTE", "color": "#0E7C6B"}
    elif ve >= 1.2 and prob >= 70:
        nivel = {"emoji": "🟢", "titulo": "BUENA", "color": "#0E7C6B"}
    elif ve >= 1.0 and prob >= 55:
        nivel = {"emoji": "🟡", "titulo": "REGULAR", "color": "#B8860B"}
    else:
        nivel = {"emoji": "⚪", "titulo": "DÉBIL — mejor no", "color": "#8A8578"}
    # frase en cristiano
    if t is None:
        vel = ""
    elif t < 1.5:
        vel = " y **rápido**"
    elif t <= 4:
        vel = " en **pocos días**"
    else:
        vel = ", pero **lento** (varios días)"
    prtxt = f"**{prob:.0f}% de recuperar tu dinero**{vel}" if p is not None else "recuperación incierta"
    pinza = " · muestra chica, con pinza" if n < 12 else ""
    nivel["resumen"] = f"{prtxt}.{pinza}"
    return nivel


def tarjeta_compacta(s: dict, key: str, moonshot: bool = False):
    """Tarjeta corta y limpia: lo esencial de un vistazo."""
    # ⚖️ el VEREDICTO manda la tarjeta: ¿es de las buenas de la semana?
    vc = veredicto_compra(s)
    borde = {"tomala": "#0F7A5A", "dudosa": "#B8860B", "espera": "#C2703D", "pasa": "#8A8578"}[vc["nivel"]]
    badge = vc["titulo"]
    dir_txt = {"call": "🟢 CALL", "put": "🔴 PUT"}[s["direccion"]]
    with st.container(border=True):
        st.markdown(f"<div style='background:{borde};color:white;padding:6px 8px;border-radius:6px;"
                    f"font-weight:700;text-align:center;font-size:.92rem'>{badge}</div>",
                    unsafe_allow_html=True)
        ritmo = ESTRATEGIAS[s["estrategia"]].get("ritmo", "")
        st.markdown(f"### {s['ticker']} · {dir_txt}")
        st.caption(f"{s['estrategia_nombre']} · {ritmo}")

        # 🧑‍⚖️ CALIFICACIÓN (palabra) + 🎯 LOGROS POSIBLES (lo puntual que pediste)
        cal = calificar(s)
        logros = s.get("_logros") or []
        filas_html = ""
        for etiqueta, p, t in logros:
            col = "#0E7C6B" if p >= 70 else ("#B8860B" if p >= 40 else "#9AA0A6")
            peso = "800" if "Recuperar" in etiqueta else "600"
            filas_html += (f"<div style='display:flex;justify-content:space-between;font-size:.85rem;'>"
                           f"<span style='color:#3A3F47;font-weight:{peso};'>{etiqueta} <span style='color:#9AA0A6;'>· {_fmt_dias(t)}</span></span>"
                           f"<span style='color:{col};font-weight:800;'>{p}%</span></div>")
        st.markdown(
            f"<div style='background:{cal['color']}14;border-left:4px solid {cal['color']};"
            f"border-radius:8px;padding:8px 11px;margin:2px 0;'>"
            f"<span style='font-weight:800;color:{cal['color']};font-size:.92rem;'>{cal['emoji']} {cal['titulo']}</span>"
            f"<div style='margin-top:5px;'>{filas_html}</div></div>",
            unsafe_allow_html=True)

        # ⚡ MÉTRICA SCALP: prob de +20% EN EL DÍA (para operar y salir el mismo día)
        ps = s.get("_p_scalp")
        intradia = ESTRATEGIAS[s["estrategia"]]["intervalo"] == "1h"
        if ps is not None:
            sc_col = "#0E7C6B" if (ps >= 45 and intradia) else ("#B8860B" if ps >= 30 else "#9AA0A6")
            apto = "se mueve rápido" if (ps >= 45 and intradia) else ("movimiento moderado" if intradia else "movimiento lento (normal en diarias)")
            st.markdown(f"<div style='background:#FFF7E6;border-radius:8px;padding:6px 10px;font-size:.83rem;"
                        f"color:#7A5B00;'>⚡ <b>Velocidad — +20% en el día: <span style='color:{sc_col};'>{ps}%</span></b> "
                        f"<span style='color:#9AA0A6;'>· {apto}</span></div>", unsafe_allow_html=True)

        # 🧭 PLAN DEL MÉTODO: la ESCALERA de venta (así es como salen los ×10)
        plan_tit = "🪜 PLAN: LA ESCALERA"
        plan_txt = ("**×2** vende la mitad (recuperas tu capital) → **×3** vende una parte → "
                    "**×5** vende otra → **deja 1-2 contratos CORRIENDO**. "
                    "Ahí es donde aparecen los ×10-×20. **No vendas todo al doblar.**")
        plan_col = "#0E6E7D"
        st.markdown(f"<div style='background:{plan_col}14;border-radius:8px;padding:6px 10px;margin-top:4px;'>"
                    f"<b style='color:{plan_col};font-size:.86rem;'>{plan_tit}</b>"
                    f"<br><span style='font-size:.78rem;color:#3A3F47;'>{plan_txt}</span></div>",
                    unsafe_allow_html=True)

        cot = s.get("_cot")
        if cot:
            pr = opcion_real.proyeccion(s["precio"], cot, s.get("beneficio_pct") or 2.0)
            tp = s["opcion"]["tipo"]
            mult = opcion_real.multiplo(s["precio"], cot, s.get("mfe_max") or 0, tp)
            c1, c2 = st.columns(2)
            c1.metric("Arriesgas", f"${pr['costo']}", help="Pérdida máxima (topada)")
            c2.metric("Puede llegar a", f"${round(pr['costo']*mult):,}", help=f"Mejor caso histórico (×{mult})")

        # --- moonshot (solo si el interruptor está prendido) ---
        if moonshot and cot:
            tp2 = s["opcion"]["tipo"]
            cot_ag = cotizacion_agresiva(s["ticker"], tp2, s["precio"])
            hm = historial(s["ticker"], s["estrategia"])
            if cot_ag and hm and not hm.get("sin_datos"):
                costo_ag = round(cot_ag["premium"] * 100)
                p10 = opcion_real.prob_de_multiplo(s["precio"], cot_ag, hm["targets"], 10, tp2)
                mm = opcion_real.multiplo(s["precio"], cot_ag, s.get("mfe_max") or 0, tp2)
                st.markdown(f"<div style='background:#FBF1D0;padding:6px 8px;border-radius:6px;color:#6B4E00'>"
                            f"🎰 <b>Moonshot</b>: ${costo_ag} · mejor caso ×{mm} · ×10: {p10}% "
                            f"<i>(apuesta chica)</i></div>", unsafe_allow_html=True)

        _tok = _token()
        url = f"?view=ficha&t={s['ticker']}&e={s['estrategia']}" + (f"&k={_tok}" if _tok else "")
        st.markdown(
            f'<a href="{url}" target="_blank" style="display:block;text-align:center;padding:9px;'
            f'border:1px solid var(--line,#E9E4DA);border-radius:11px;text-decoration:none;'
            f'color:var(--accent2,#0E7C6B);font-weight:600;background:var(--card,#fff);margin-top:4px;">'
            f'🔎 Ver ficha ↗</a>', unsafe_allow_html=True)


def aplicar_filtros(ops: list[dict], min_cond: int, direccion_f: str,
                    solo_ent: bool, orden: str) -> list[dict]:
    """Filtra y ordena una lista de oportunidades según los controles."""
    filt = [s for s in ops if s["n_cond"] >= min_cond]
    if direccion_f.startswith("Solo CALL"):
        filt = [s for s in filt if s["direccion"] == "call"]
    elif direccion_f.startswith("Solo PUT"):
        filt = [s for s in filt if s["direccion"] == "put"]
    if solo_ent:
        filt = [s for s in filt if s["estado"] == "ENTRADA"]
    # ENTRADA siempre por encima de VIGILAR; luego el criterio elegido; a igualdad,
    # gana la que cumple más condiciones (más confluencia = más calidad).
    orden_estado = {"ENTRADA": 0, "VIGILAR": 1}
    if orden.startswith("💥"):
        clave = lambda s: (orden_estado.get(s["estado"], 2), -s["beneficio_pct"], -s["n_cond"])
    elif orden.startswith("🛡️"):
        clave = lambda s: (orden_estado.get(s["estado"], 2), -s["confiabilidad_pct"], -s["n_cond"])
    else:
        clave = lambda s: (orden_estado.get(s["estado"], 2), -s["oportunidad"], -s["n_cond"])
    filt.sort(key=clave)
    return filt


def render_grid(filt: list[dict], key_prefix: str, presupuesto: int, top: int = 9,
                moonshot: bool = False, filtro_premio: bool = False, ncols: int = 3) -> int:
    """Trae la prima real (respetando presupuesto) y pinta la parrilla de tarjetas."""
    mostrados = []
    for s in filt[:25]:
        o = s["opcion"]
        cot = cotizacion(s["ticker"], o["tipo"], o["strike"], o["dias_vencimiento"])
        s["_cot"] = cot
        costo = round(cot["premium"] * 100) if cot else None
        if presupuesto and costo and costo > presupuesto:
            continue
        # filtro "premio vale el tiempo": el mejor caso debe superar el umbral del ritmo
        if filtro_premio and cot:
            mm = opcion_real.multiplo(s["precio"], cot, s.get("mfe_max") or 0, o["tipo"])
            umbral = max(PREMIO_PISO_ABSOLUTO, PREMIO_MINIMO_POR_ESTRATEGIA.get(s["estrategia"], 1.5))
            if mm < umbral:
                continue
        mostrados.append(s)
        if len(mostrados) >= top:
            break
    if not mostrados:
        st.caption("— Sin oportunidades aquí ahora mismo. —")
        return 0

    # ¿cuáles VALEN LA PENA? (VE >= 1.2 y el premio justifica el tiempo)
    for s in mostrados:
        cot = s.get("_cot")
        if not cot:
            s["_ve"] = None; s["_vale"] = False
            continue
        tp = s["opcion"]["tipo"]
        h = historial(s["ticker"], s["estrategia"])
        tiene_h = h and not h.get("sin_datos")
        ve = opcion_real.valor_esperado(s["precio"], cot, h["targets"], s.get("mfe_max") or 0, tp) if tiene_h else None
        mult = opcion_real.multiplo(s["precio"], cot, s.get("mfe_max") or 0, tp)
        umbral = max(PREMIO_PISO_ABSOLUTO, PREMIO_MINIMO_POR_ESTRATEGIA.get(s["estrategia"], 1.5))
        s["_ve"] = ve
        s["_vale"] = bool(ve is not None and ve >= 1.2 and mult >= umbral)
        # RECUPERAR (+50% = ×1.5) y DOBLAR (×2): probabilidad Y tiempo
        s["_t_recup"] = opcion_real.tiempo_de_multiplo(s["precio"], cot, h["targets"], 1.5, tp) if tiene_h else None
        s["_t_x2"] = opcion_real.tiempo_de_multiplo(s["precio"], cot, h["targets"], 2, tp) if tiene_h else None
        s["_p_recup"] = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 1.5, tp) if tiene_h else None
        s["_p_x2"] = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 2, tp) if tiene_h else None
        # 🎯 LOGROS POSIBLES: prob de ×N dentro de D días (lo que Oscar quiere ver)
        # ⚡ SCALP: probabilidad de +20% (×1.2) DENTRO del día (mismo día)
        s["_p_scalp"] = (opcion_real.prob_multiplo_en_dias(s["precio"], cot, h["mfe_dias"], 1.2, 1, tp)
                         if (tiene_h and h.get("mfe_dias")) else None)
        # LOGROS POSIBLES: probabilidad + tiempo típico de cada meta (números honestos)
        s["_logros"] = []
        if tiene_h:
            for etiqueta, mult_n in [("Recuperar (+50%)", 1.5), ("Doblar (×2)", 2),
                                     ("Triplicar (×3)", 3)]:
                p = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], mult_n, tp)
                t = opcion_real.tiempo_de_multiplo(s["precio"], cot, h["targets"], mult_n, tp)
                s["_logros"].append((etiqueta, p, t))

    if sum(1 for s in mostrados if s.get("_vale")) == 0:
        st.warning("⏳ **Ninguna de aquí vale la pena hoy** (valor esperado bajo o el premio no "
                   "justifica el tiempo). Lo más inteligente: **esperar**. Puedes verlas abajo igual.")

    cols = st.columns(ncols)
    for i, s in enumerate(mostrados):
        with cols[i % ncols]:
            tarjeta_compacta(s, f"{key_prefix}_{i}", moonshot=moonshot)
    return len(mostrados)


def render_bitacora():
    st.markdown(CABECERA, unsafe_allow_html=True)
    st.markdown("## 📔 Bitácora")
    libro = st.radio("Libro", ["simulacion", "real"], horizontal=True,
                     format_func=lambda x: "📝 Simulación (papel)" if x == "simulacion" else "💵 Real")

    # --- métricas (la estrella: la EXPECTATIVA) ---
    m = bitacora.metricas(libro)
    if m["n"] == 0:
        st.info("Aún no hay operaciones **cerradas** en este libro. Registra abajo y ciérralas al salir. "
                "Con 15-20 operaciones ya verás si el método te da dinero.")
    else:
        c = st.columns(4)
        c[0].metric("Operaciones", m["n"])
        c[1].metric("% Acierto", f"{m['win_rate']:.0f}%")
        exp = m["expectativa"]
        c[2].metric("💡 Expectativa/op", f"{exp:+.0f}%")
        c[3].metric("Resultado total", f"${m['total_usd']:+,.0f}")
        st.caption(f"Ganancia media **+{m['avg_win']:.0f}%** · Pérdida media **{m['avg_loss']:.0f}%** · "
                   f"{m['ganadoras']} ✅ / {m['perdedoras']} ❌")
        if exp > 0:
            st.success(f"💡 **Expectativa POSITIVA (+{exp:.0f}% por operación):** en el conjunto, el método "
                       "te está dando dinero. Aunque pierdas varias, las ganadoras pagan de más.")
        else:
            st.warning(f"💡 **Expectativa negativa ({exp:.0f}%):** por ahora el conjunto no da. Sigue "
                       "registrando (la muestra es chica) o hay que afinar el método.")

    # --- registrar operación nueva ---
    with st.expander("➕ Registrar operación nueva", expanded=(m["n"] == 0)):
        with st.form("nueva_op", clear_on_submit=True):
            col = st.columns(3)
            ticker = col[0].text_input("Activo (ej. XOM)")
            direccion = col[1].selectbox("Dirección", ["call", "put"])
            estrategia = col[2].selectbox("Estrategia", list(ESTRATEGIAS.keys()),
                                          format_func=lambda e: ESTRATEGIAS[e]["nombre"])
            col2 = st.columns(4)
            strike = col2[0].number_input("Strike", min_value=0.0, step=1.0)
            prima = col2[1].number_input("Prima pagada ($/acción)", min_value=0.0, step=0.05)
            contratos = col2[2].number_input("Contratos", min_value=1, value=1, step=1)
            venc = col2[3].date_input("Vencimiento", value=None,
                                      help="IMPORTANTE: con esta fecha el Vigilante te avisa "
                                           "cuándo vence y cuándo vender. No la dejes vacía.")
            nota = st.text_input("Nota (por qué entraste)")
            if st.form_submit_button("Registrar"):
                if ticker and prima > 0:
                    bitacora.agregar(libro, ticker, direccion, estrategia, strike, prima,
                                     contratos, nota, venc.isoformat() if venc else "")
                    st.rerun()
                else:
                    st.error("Pon al menos el activo y la prima pagada.")

    # --- operaciones abiertas (para cerrar) ---
    abiertas = bitacora.listar(libro, "abierta")
    if abiertas:
        st.markdown("### Abiertas (ciérralas al salir)")
        for t in abiertas:
            with st.container(border=True):
                st.markdown(f"**{t['ticker']} · {t['direccion'].upper()}** · strike {t['strike']} · "
                            f"prima entrada **${t['prima_entrada']}** · {t['contratos']} contrato(s)")
                st.caption(f"{t['fecha_entrada']} · {ESTRATEGIAS.get(t['estrategia'],{}).get('nombre','')}"
                           + (f" · {t['nota']}" if t['nota'] else ""))
                # 🚦 CHEQUEO DE SEÑAL: ¿el motor sigue a favor o se volteó?
                niv, txt = chequear_senal(t["ticker"], t["direccion"])
                col = {"favor": "#0E7C6B", "contra": "#C0392B", "neutral": "#8A8578"}[niv]
                st.markdown(f"<div style='background:{col}14;border-left:4px solid {col};border-radius:6px;"
                            f"padding:5px 10px;font-size:.85rem;color:{col};font-weight:600;'>{txt}</div>",
                            unsafe_allow_html=True)
                # 💰 PRECIO ACTUAL en vivo: cuánto vale AHORA tu contrato exacto
                venc = t.get("vencimiento") or ""
                dias_v = None
                cot_ahora = None
                try:
                    from datetime import date as _d
                    dias_v = (_d.fromisoformat(venc) - _d.today()).days if venc else None
                except Exception:
                    dias_v = None
                if float(t.get("strike") or 0) > 0:
                    cot_ahora = cotizacion(t["ticker"], t["direccion"].upper(),
                                           float(t["strike"]), max(1, dias_v or 7))
                    if cot_ahora and abs(cot_ahora["strike"] - float(t["strike"])) / float(t["strike"]) > 0.02:
                        cot_ahora = None
                pe = float(t.get("prima_entrada") or 0)
                valor_ahora = cot_ahora["premium"] if cot_ahora else None
                if valor_ahora and pe:
                    gan = (valor_ahora - pe) / pe * 100
                    total = round((valor_ahora - pe) * 100 * t["contratos"])
                    ico = "🟢" if gan >= 0 else "🔴"
                    linea = (f"{ico} **Ahora vale ${valor_ahora}** (entrada ${pe}) · "
                             f"**{gan:+.0f}%** · {total:+,} $")
                    if gan >= 100:
                        linea += "  — 🎉 **¡DOBLÓ! Vende la MITAD**"
                    st.markdown(linea)
                if venc:
                    v_txt = f"Vence **{venc}**" + (f" · en **{dias_v} días**" if dias_v is not None else "")
                    if dias_v is not None and dias_v <= 2:
                        v_txt += " ⏳ **decide ya**"
                    st.caption(v_txt)
                else:
                    st.caption("⚠️ Sin fecha de vencimiento — el Vigilante no podrá avisarte. Vuelve a registrarla con fecha.")

                cc = st.columns([1.6, 1.2, 1, 0.7])
                ps = cc[0].number_input("Prima de salida ($)", min_value=0.0, step=0.05,
                                        value=float(valor_ahora or 0.0), key=f"ps_{t['id']}",
                                        help="Se rellena sola con el precio actual del mercado.")
                if cc[1].button("💰 Vender al precio actual", key=f"vender_{t['id']}",
                                use_container_width=True, disabled=not valor_ahora):
                    bitacora.cerrar(t["id"], float(valor_ahora))
                    st.rerun()
                if cc[2].button("✓ Cerrar", key=f"cerrar_{t['id']}", use_container_width=True):
                    bitacora.cerrar(t["id"], ps)
                    st.rerun()
                if cc[3].button("🗑️", key=f"del_{t['id']}", use_container_width=True):
                    bitacora.eliminar(t["id"])
                    st.rerun()

    # --- historial cerradas ---
    cerradas = bitacora.listar(libro, "cerrada")
    if cerradas:
        st.markdown("### Historial")
        filas = [{
            "Activo": t["ticker"], "Dir": t["direccion"].upper(),
            "Estrategia": ESTRATEGIAS.get(t["estrategia"], {}).get("nombre", t["estrategia"]),
            "Prima ent.": f"${t['prima_entrada']}", "Prima sal.": f"${t['prima_salida']}",
            "Resultado": f"{t['resultado_pct']:+.0f}%", "Dinero": f"${t['resultado_usd']:+.0f}",
            "Fecha": (t["fecha_entrada"] or "")[:10],
        } for t in cerradas]
        st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)

    # --- guardar / restaurar (importante en la nube) ---
    with st.expander("💾 Guardar / restaurar bitácora (¡descárgala seguido!)"):
        st.caption("En la nube, la bitácora puede borrarse al reiniciar. Descárgala para no perderla; "
                   "y súbela para restaurarla.")
        st.download_button("⬇️ Descargar bitácora (CSV)", bitacora.exportar_csv(),
                           "bitacora.csv", "text/csv")
        up = st.file_uploader("⬆️ Restaurar desde CSV (reemplaza todo)", type="csv")
        if up is not None:
            n = bitacora.importar_csv(up.getvalue().decode())
            st.success(f"Restauradas {n} operaciones.")
            st.rerun()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.markdown(ESTILO, unsafe_allow_html=True)


def _clave_esperada():
    import os
    e = os.environ.get("RADAR_PASSWORD")
    if not e:
        try:
            e = st.secrets.get("password")
        except Exception:
            e = None
    return e


def _token() -> str:
    """Token derivado de la contraseña (NO es la contraseña). Sirve para que las
    pestañas de ficha ya autenticadas no vuelvan a pedir la clave."""
    e = _clave_esperada()
    if not e:
        return ""
    import hashlib
    return hashlib.sha256(f"radar-metodo:{e}".encode()).hexdigest()[:24]


def _puerta_contrasena():
    """Candado: si hay contraseña configurada (RADAR_PASSWORD/secrets), la pide.
    En local, si no hay contraseña, se desactiva solo."""
    esperada = _clave_esperada()
    if not esperada:                       # sin contraseña configurada -> abierto (uso local)
        return
    # las pestañas de ficha traen un token válido -> ya están autenticadas
    if st.query_params.get("k") == _token():
        st.session_state["auth_ok"] = True
    if st.session_state.get("auth_ok"):
        return
    _c1, _c2, _c3 = st.columns([1, 1.4, 1])
    with _c2:
        st.markdown("<div style='height:12vh'></div>", unsafe_allow_html=True)
        st.markdown(CABECERA, unsafe_allow_html=True)
        pw = st.text_input("clave", type="password", label_visibility="collapsed",
                           placeholder="Clave")
        if pw:
            if pw == esperada:
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.error("Incorrecta.")
    st.stop()


_puerta_contrasena()

# --- PESTAÑA DE FICHA (se abre en su propia ventana del navegador) ---
_qp = st.query_params
if _qp.get("view") == "ficha":
    render_ficha_pagina(_qp.get("t", ""), _qp.get("e", ""))
    st.stop()

st.markdown(CABECERA, unsafe_allow_html=True)

with st.sidebar:
    st.header("Ajustes")
    universo_modo = st.radio(
        "Vista",
        ["🏠 Dashboard (3 universos)", "📔 Bitácora", "Método puro: S&P 500",
         "Motor paralelo: fuera del S&P 500", "Solo ETFs base (5)"],
        help="Dashboard: oportunidades. Bitácora: registra y mide tus operaciones.")
    bitacora_mode = universo_modo.startswith("📔")
    dashboard = universo_modo.startswith("🏠")
    ampliado = dashboard or not universo_modo.startswith("Solo ETFs")
    universo_tickers = UNIVERSO_NUCLEO if universo_modo.startswith("Método") else UNIVERSO_PARALELO
    es_paralelo = universo_modo.startswith("Motor")
    if not ampliado:
        modo = st.radio("¿Qué estrategias escanear?",
                        ["Recomendadas para empezar", "Las 4 estrategias"],
                        help="Las recomendadas (piso fuerte + tres semanas) son las más pausadas.")
        ests = ESTRATEGIAS_INICIALES if modo.startswith("Recomend") else list(ESTRATEGIAS)
    if st.button("🔄 Actualizar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    # --- auto-refresco durante horario de mercado ---
    sesion = premarket.estado_sesion()
    sesion_txt = {"pre": "🟡 Pre-market", "abierto": "🟢 Mercado ABIERTO",
                  "post": "🟠 After-hours", "cerrado": "⚪ Mercado cerrado"}[sesion]
    st.caption(f"Sesión: **{sesion_txt}**")
    auto = st.checkbox("🔄 Auto-refrescar", value=(sesion == "abierto"),
                       help="Mientras esté marcado, el Radar se actualiza solo. Útil con el mercado abierto.")
    if auto:
        cada = st.select_slider("Cada cuánto", options=[1, 2, 3, 5], value=3,
                                format_func=lambda x: f"{x} min")
        st_autorefresh(interval=cada * 60000, key="autoref")
        if sesion in ("pre", "abierto"):
            st.caption("Se refresca solo. Déjalo abierto en una pestaña.")

    # --- alertas al celular ---
    st.divider()
    if notify.telegram_configurado():
        st.caption("🔔 Alertas Telegram: **activadas**")
    else:
        with st.expander("🔔 Recibir alertas en el celular"):
            st.markdown(
                "Para que el **vigilante** te avise sin estar pegado a la pantalla:\n\n"
                "1. Corre `Iniciar Vigilante.command` (te avisa por notificación de Mac).\n"
                "2. Para alertas al **celular por Telegram**, mira las instrucciones en `ALERTAS.md`.")

    st.divider()
    st.markdown(
        f"**Recordatorios del método**\n\n"
        f"- Riesgo: máx **{RIESGO_MAX_CAPITAL_PCT}%** del capital en opciones.\n"
        f"- Capital de prueba: **${CAPITAL_PRUEBA}**.\n"
        f"- Salida: al **+{SALIDA_GANANCIA_PCT}%**, vender la mitad y dejar correr el resto.\n"
        f"- Pérdida máxima por trade = la prima. Ni un centavo más.")
    st.caption("Educativo. No es asesoría financiera. Simula y mide antes de arriesgar capital real.")


def panel_calendario():
    caldata = calendario()
    cc = caldata["contexto"]
    if cc["nivel"] == "peligro":
        st.error(f"📅 **{cc['texto']}**")
    elif cc["nivel"] == "precaucion":
        st.warning(f"📅 {cc['texto']}")
    else:
        st.success(f"📅 {cc['texto']}")
    if caldata["proximos"]:
        with st.expander("📅 Ver calendario económico de esta semana (eventos de alto impacto en EE.UU.)"):
            filas = [{
                "Cuándo": e["cuando"].strftime("%a %d-%b %H:%M"), "Evento": e["titulo"],
                "Se espera": e.get("forecast", "") or "—", "Previo": e.get("previous", "") or "—",
            } for e in caldata["proximos"]]
            st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)
            st.caption("Fuente: faireconomy (Forex Factory). CPI = inflación · FOMC/Fed = tasas · NFP = empleo.")


# =====================  MODO: BITÁCORA  =====================
if bitacora_mode:
    render_bitacora()
    st.stop()


# =====================  MODO: DASHBOARD (3 UNIVERSOS)  =====================
if dashboard:
    incluir_horario = premarket.estado_sesion() in ("pre", "abierto", "post")
    with st.spinner(f"Escaneando el universo completo ({len(UNIVERSO_TICKERS)} activos)..."):
        ops_all = oportunidades_universo(tuple(UNIVERSO_TICKERS), incluir_horario)

    ahora = datetime.now(premarket.ET).strftime("%H:%M")
    entradas = [s for s in ops_all if s["estado"] == "ENTRADA"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Activos vigilados", len(UNIVERSO_TICKERS))
    m2.metric("🟢 Entradas listas", len(entradas))
    m3.metric("🎯 Oportunidades activas", len(ops_all))
    if incluir_horario:
        st.caption(f"🔴 EN VIVO · {ahora} — se re-rankea solo cada 3 min. "
                   "Las señales intradía cambian durante el día; actúa cuando estén frescas.")

    panel_calendario()

    # --- 💼 TU CAPITAL (global): fija tu cuenta una vez para toda la sesión ---
    cap_cols = st.columns([1, 3])
    cap = cap_cols[0].number_input(
        "💼 Mi capital ($)", min_value=100,
        value=int(st.session_state.get("cuenta_usd", 1000)), step=100,
        help="Se usa en TODAS las fichas para calcular cuántos contratos comprar. "
             "También puedes cambiarlo dentro de cada oportunidad.")
    st.session_state["cuenta_usd"] = cap
    cap_cols[1].caption(f"El sistema arriesgará el **{RIESGO_MAX_CAPITAL_PCT}%** = "
                        f"**${round(cap*RIESGO_MAX_CAPITAL_PCT/100)}** por operación. "
                        "Cambia tu capital cuando crezca y todo se recalcula solo.")

    # --- 🧭 TU SITUACIÓN: cuánto cupo te queda esta semana ---
    try:
        c = estado_cartera()
        libre_sem = max(0, 4 - c["esta_semana"])
        libre_pos = max(0, 4 - c["abiertas"])
        q1, q2, q3 = st.columns(3)
        q1.metric("Abiertas ahora", f"{c['abiertas']}",
                  help="Máximo recomendado: 4 a la vez. Deja pólvora seca.")
        q2.metric("Operaciones esta semana", f"{c['esta_semana']} de 4",
                  help="El método pide 2-4 por semana. Forzar más es el error clásico.")
        q3.metric("Capital desplegado", f"${c['desplegado']:,}",
                  help="Lo que tienes metido en opciones abiertas ahora mismo.")
        if libre_sem == 0 or libre_pos == 0:
            motivo = ("ya cumpliste tu cupo semanal (4)" if libre_sem == 0
                      else "ya tienes 4 posiciones abiertas")
            st.info(f"🧭 **Vas sobre el ritmo del método** — {motivo}. "
                    "De aquí en adelante el tool te marcará las señales como **excepción**: "
                    "solo te dirá TÓMALA si es **excepcional** (ventaja alta, muy probable, "
                    "rápida y con muestra grande). **La decisión final es tuya.**")
        else:
            st.caption(f"🧭 Te quedan **{libre_sem} operación(es)** de tu cupo semanal y "
                       f"**{libre_pos} espacio(s)** de posiciones abiertas.")
    except Exception:
        pass

    # --- filtros (sin "mínimo de condiciones": el ranking lo hace solo) ---
    with st.container(border=True):
        f1, f2 = st.columns([1.2, 1.6])
        d_dir = f1.radio("Dirección", ["Ambas", "Solo CALL (sube)", "Solo PUT (baja)"],
                         help="Ya están las dos: 9 estrategias de CALL y 5 de PUT (día 1 + día 2).")
        d_orden = f2.radio("Ordenar por",
                           ["🎯 Oportunidad (equilibrio)", "💡 Valor esperado (matemática)",
                            "💥 Rentabilidad (más ganancia)", "🛡️ Confiabilidad (más segura)",
                            "⚡ Scalp (+20% en el día) — otro enfoque"],
                           help="Oportunidad = el equilibrio del método (zona + confiabilidad + beneficio). "
                                "Scalp es un enfoque distinto (entrar y salir el mismo día), no el método puro.")
        g1, g2, g3 = st.columns([1.4, 1, 1])
        d_pres = g1.number_input("💵 Presupuesto máx. por contrato ($) — 0 = sin límite",
                                 min_value=0, max_value=100000, value=0, step=100)
        d_incluir_vig = g2.checkbox("Incluir en vigilancia", value=False,
                                    help="Además de las confirmadas, muestra las que se están armando.")
        d_moonshot = g3.checkbox("🎰 Ver moonshot", value=False,
                                 help="Muestra en cada tarjeta la jugada AGRESIVA (más barata, ×10 posible). "
                                      "Para echarle el ojo de vez en cuando y apostar poquito.")
        d_premio = st.checkbox("🎯 Solo si el premio vale el tiempo (regla de Oscar)", value=False,
                               help="Oculta las que no pueden dar suficiente premio para el tiempo que esperas: "
                                    "rápidas mínimo ×2, medias ×3, lentas ×5. Piso absoluto ×1.5.")

    # partir el universo en las tres secciones
    por_indice = {"ETF": [], "SP500": [], "FUERA": []}
    for s in ops_all:
        por_indice.get(s.get("indice", ""), por_indice["SP500"]).append(s)

    secciones = [
        ("📊 ETFs base", "Los 5 índices/materias primas — el corazón del método", "ETF", "etf"),
        ("🟦 S&P 500", "Acciones dentro del índice — el principio de Cardona", "SP500", "sp5"),
        ("🧪 Motor paralelo", "Fuera del S&P 500 — más potencial, más riesgo", "FUERA", "par"),
    ]
    def calcular_ve(s):
        """Calcula el Valor Esperado real (con prima real) y lo guarda en la señal."""
        o = s["opcion"]
        cot = cotizacion(s["ticker"], o["tipo"], o["strike"], o["dias_vencimiento"])
        s["_cot"] = cot
        hh = historial(s["ticker"], s["estrategia"])
        if cot and hh and not hh.get("sin_datos"):
            s["_ve"] = opcion_real.valor_esperado(s["precio"], cot, hh["targets"], s.get("mfe_max") or 0, o["tipo"])
        else:
            s["_ve"] = -1
        return s["_ve"]

    def calcular_scalp(s):
        """Prob de +20% en el día (para rankear scalp). Guarda el orden en la señal."""
        o = s["opcion"]
        cot = cotizacion(s["ticker"], o["tipo"], o["strike"], o["dias_vencimiento"])
        s["_cot"] = cot
        hh = historial(s["ticker"], s["estrategia"])
        if cot and hh and not hh.get("sin_datos") and hh.get("mfe_dias"):
            p = opcion_real.prob_multiplo_en_dias(s["precio"], cot, hh["mfe_dias"], 1.2, 1, o["tipo"])
            # bonus a las intradía (son las que de verdad se pueden scalpear el mismo día)
            intradia = ESTRATEGIAS[s["estrategia"]]["intervalo"] == "1h"
            s["_scalp_sort"] = p + (15 if intradia else 0)
        else:
            s["_scalp_sort"] = -1
        return s["_scalp_sort"]

    for emoji_titulo, subt, indice, keyp in secciones:
        # sin filtro de condiciones: se rankea solo. Piso mínimo 3/5 (automático).
        lista = aplicar_filtros(por_indice[indice], 3, d_dir, not d_incluir_vig, d_orden)
        # ordenar por Valor Esperado o Scalp (requieren prima real; sobre el pool top)
        if d_orden.startswith("💡") and lista:
            pool = lista[:15]
            for s in pool:
                calcular_ve(s)
            lista = sorted(pool, key=lambda s: -(s.get("_ve") if s.get("_ve") is not None else -1))
        elif d_orden.startswith("⚡") and lista:
            pool = lista[:15]
            for s in pool:
                calcular_scalp(s)
            lista = sorted(pool, key=lambda s: -(s.get("_scalp_sort") if s.get("_scalp_sort") is not None else -1))
        n_ent = len([s for s in por_indice[indice] if s["estado"] == "ENTRADA"])
        st.markdown(f"### {emoji_titulo}")
        st.caption(f"{subt}  ·  🟢 **{n_ent} listas** · toca **Ver ficha ↗** para abrirla en otra pestaña")
        if indice == "FUERA" and lista:
            st.caption("🧪 Más arriesgadas. Posiciones pequeñas.")
        render_grid(lista, keyp, d_pres, top=6, moonshot=d_moonshot,
                    filtro_premio=d_premio, ncols=3)
        st.divider()

    st.stop()  # el dashboard no sigue al flujo de universo único


# =====================  MODO: UNIVERSO AMPLIADO  =====================
if ampliado:
    # incluir estrategias horarias (intradía) cuando hay actividad de mercado
    incluir_horario = premarket.estado_sesion() in ("pre", "abierto", "post")
    with st.spinner(f"Escaneando {len(universo_tickers)} activos"
                    f"{' (con intradía)' if incluir_horario else ''} y rankeando oportunidades..."):
        ops = oportunidades_universo(tuple(universo_tickers), incluir_horario)
    entradas = [s for s in ops if s["estado"] == "ENTRADA"]

    if es_paralelo:
        st.warning("🧪 **Motor paralelo — fuera del S&P 500.** Estas empresas se mueven mucho (gran "
                   "potencial), pero traen más riesgo: no son parte del índice base del método (SPY), "
                   "y algunas son extranjeras o muy especulativas. Trátalas como exploración, con posiciones "
                   "más pequeñas. El principio de Cardona sigue siendo el S&P 500.")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Activos escaneados", len(universo_tickers))
    m2.metric("🎯 Oportunidades activas", len(ops))
    m3.metric("🟢 Entradas listas", len(entradas))
    m4.metric("Mejor oportunidad", f"{ops[0]['oportunidad']}/100" if ops else "—")

    panel_calendario()

    titulo = "🧪 Oportunidades paralelas (fuera del S&P 500)" if es_paralelo else "🎯 Oportunidades del día — S&P 500"
    st.subheader(titulo)
    ahora = datetime.now(premarket.ET).strftime("%H:%M")
    if incluir_horario:
        st.caption(f"🔴 EN VIVO · {ahora} — Las señales intradía (canal, MA40) **cambian durante el día**. "
                   "Una entrada puede aparecer y desaparecer según se mueve el precio. Actúa cuando esté fresca.")

    # --- FILTROS ---
    with st.container(border=True):
        f1, f2, f3 = st.columns([1.1, 1.3, 1.4])
        min_cond = f1.select_slider("Mínimo de condiciones", options=[2, 3, 4, 5], value=4,
                                    help="4 de 5 = señales sólidas. Sube a 5 para las más exigentes.")
        direccion_f = f2.radio("Dirección", ["Ambas", "Solo CALL (sube)", "Solo PUT (baja)"],
                               help="Ya están las dos: 9 estrategias de CALL y 5 de PUT (día 1 + día 2).")
        orden = f3.radio("Ordenar por",
                         ["🎯 Oportunidad (equilibrio)", "💥 Rentabilidad (más ganancia)",
                          "🛡️ Confiabilidad (más segura)"])
        g1, g2 = st.columns([1.3, 1])
        presupuesto = g1.number_input("💵 Presupuesto máx. por contrato ($) — 0 = sin límite",
                                      min_value=0, max_value=100000, value=0, step=100,
                                      help="Oculta las opciones que cuesten más de esto. Ideal para tu capital de prueba.")
        solo_ent = g2.checkbox("Solo ENTRADA", value=True,
                               help="Solo las confirmadas (listas para comprar), sin las que aún se arman.")

    # aplicar filtros
    filt = list(ops)
    filt = [s for s in filt if s["n_cond"] >= min_cond]
    if direccion_f.startswith("Solo CALL"):
        filt = [s for s in filt if s["direccion"] == "call"]
    elif direccion_f.startswith("Solo PUT"):
        filt = [s for s in filt if s["direccion"] == "put"]
    if solo_ent:
        filt = [s for s in filt if s["estado"] == "ENTRADA"]
    if orden.startswith("💥"):
        filt.sort(key=lambda s: -s["beneficio_pct"])
    elif orden.startswith("🛡️"):
        filt.sort(key=lambda s: -s["confiabilidad_pct"])
    else:
        filt.sort(key=lambda s: -s["oportunidad"])

    # traer prima real y aplicar presupuesto (solo a los mejores, para no saturar)
    mostrados = []
    for s in filt[:20]:
        o = s["opcion"]
        cot = cotizacion(s["ticker"], o["tipo"], o["strike"], o["dias_vencimiento"])
        s["_cot"] = cot
        costo = round(cot["premium"] * 100) if cot else None
        if presupuesto and costo and costo > presupuesto:
            continue
        mostrados.append(s)
        if len(mostrados) >= 9:
            break

    st.caption(f"Mostrando **{len(mostrados)}** oportunidades (de {len(filt)} tras el filtro). "
               "🟢 COMPRAR = lista · ⚠️ CUIDADO = hay que reconfirmar · ⏳ VIGILAR = armándose.")

    if not mostrados:
        st.info("Ninguna oportunidad pasa el filtro ahora mismo. Prueba bajar el mínimo de condiciones, "
                "subir el presupuesto, o incluir vigilancia. La disciplina también es esperar.")
    else:
        # parrilla de tarjetas compactas (3 por fila), se re-rankea en cada refresco
        cols = st.columns(3)
        for i, s in enumerate(mostrados):
            with cols[i % 3]:
                tarjeta_compacta(s, i)

# =====================  MODO: SOLO ETFs BASE  =====================
else:
    with st.spinner("Escaneando los 5 ETFs base con el método..."):
        señales = escanear(tuple(ests))
    activas = [s for s in señales if s["estado"] != "NADA"]
    entradas = [s for s in activas if s["estado"] == "ENTRADA"]

    m1, m2, m3 = st.columns(3)
    m1.metric("ETFs escaneados", len(ACTIVOS))
    m2.metric("🟢 Entradas confirmadas", len(entradas))
    m3.metric("🟡 En vigilancia", len(activas) - len(entradas))

    panel_calendario()

    if not activas:
        st.info("Sin señales activas ahora mismo. El método dice: **esperar**. "
                "La mayoría de los días no hay entrada — y eso está bien.")
    else:
        st.subheader("Señales")
        for s in activas:
            tarjeta(s)

    with st.expander("Ver también los ETFs sin señal (estado NADA)"):
        for s in [s for s in señales if s["estado"] == "NADA"]:
            st.markdown(f"⚪ **{s['ticker']}** · {s['estrategia_nombre']} — {sum(1 for v in s['checklist'].values() if v['ok'])}/5 condiciones")
