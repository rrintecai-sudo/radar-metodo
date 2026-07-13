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
def cotizacion(ticker: str, tipo: str, strike: float, dias: int) -> dict | None:
    return opcion_real.cotizar(ticker, tipo, strike, dias)


@st.cache_data(ttl=300, show_spinner=False)
def cotizacion_agresiva(ticker: str, tipo: str, precio: float) -> dict | None:
    """La opción 'lotería': más fuera del dinero y vencimiento corto (×10 posible)."""
    from config import STRIKE_OTM_AGRESIVO, VENCIMIENTO_DIAS_AGRESIVO
    signo = 1 if tipo == "CALL" else -1
    strike = round(precio * (1 + signo * STRIKE_OTM_AGRESIVO / 100), 2)
    return opcion_real.cotizar(ticker, tipo, strike, VENCIMIENTO_DIAS_AGRESIVO)


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
        st.markdown("**¿Qué tan factible es cada multiplicación, y EN CUÁNTO TIEMPO?**")
        fp = pd.DataFrame([
            {"Multiplicar": "×2 (doblar, +100%)", "Probabilidad": f"{p2}%", "⏱️ Tiempo típico": fmt_d(t2)},
            {"Multiplicar": "×3 (+200%)", "Probabilidad": f"{p3}%", "⏱️ Tiempo típico": fmt_d(t3)},
            {"Multiplicar": "×5 (+400%)", "Probabilidad": f"{p5}%", "⏱️ Tiempo típico": fmt_d(t5)},
            {"Multiplicar": "×10 (+1000%)", "Probabilidad": f"{p10}%", "⏱️ Tiempo típico": fmt_d(t10)},
        ])
        st.dataframe(fp, hide_index=True, use_container_width=True)
        st.caption("👉 Ahora sí decides bien: un ×2 en ~1 día es un negoción; un ×2 en ~7 días, según tu regla, "
                   "no vale la pena. **El multiplicador SIN el tiempo engaña.**")
        # --- la opción AGRESIVA (billete de lotería) — en desplegable para no cargar de más ---
        with st.expander("🎰 ¿Y si busco el moonshot (×10)? — ver la opción agresiva"):
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
            st.markdown("**Opción sugerida:**")
            st.markdown(
                f"- Tipo: **{o['tipo']}**\n"
                f"- Strike: **{o['strike']}** (~{o['otm_pct']}% OTM)\n"
                f"- Vencimiento: **~{o['dias_vencimiento']} días** ({o['vencimiento_aprox']})")

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


def tarjeta_compacta(s: dict, key: str, moonshot: bool = False):
    """Tarjeta corta y limpia: lo esencial de un vistazo."""
    nivel, badge = accion_badge(s)
    borde = {"comprar": "#0F7A5A", "cuidado": "#C0392B", "vigilar": "#B8860B"}[nivel]
    dir_txt = {"call": "🟢 CALL", "put": "🔴 PUT"}[s["direccion"]]
    with st.container(border=True):
        st.markdown(f"<div style='background:{borde};color:white;padding:5px 8px;border-radius:6px;"
                    f"font-weight:700;text-align:center'>{badge}</div>", unsafe_allow_html=True)
        ritmo = ESTRATEGIAS[s["estrategia"]].get("ritmo", "")
        st.markdown(f"### {s['ticker']} · {dir_txt}")
        st.caption(f"{s['estrategia_nombre']} · {ritmo}")

        cot = s.get("_cot")
        if cot:
            pr = opcion_real.proyeccion(s["precio"], cot, s.get("beneficio_pct") or 2.0)
            tp = s["opcion"]["tipo"]
            mult = opcion_real.multiplo(s["precio"], cot, s.get("mfe_max") or 0, tp)
            c1, c2 = st.columns(2)
            c1.metric("Arriesgas", f"${pr['costo']}", help="Pérdida máxima (topada)")
            c2.metric("🚀 Mejor caso", f"×{mult}", help=f"${pr['costo']} → ${round(pr['costo']*mult):,}")
            hc = historial(s["ticker"], s["estrategia"])
            ve = opcion_real.valor_esperado(s["precio"], cot, hc["targets"], s.get("mfe_max") or 0, tp) \
                if (hc and not hc.get("sin_datos")) else None
        else:
            ve = None

        # UNA sola línea con lo esencial (menos ruido)
        cf = s.get("confianza", {})
        nm = s.get("n_muestra", 0)
        ve_txt = f"💡 VE **×{ve}** · " if ve is not None else ""
        st.caption(f"{ve_txt}✅ **{s['confiabilidad_pct']:.0f}%** ({nm} casos {cf.get('emoji','')}) · "
                   f"⚖️ **{s.get('ratio_br','—')}** · 📋 **{s['n_cond']}/5**")

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

        url = f"?view=ficha&t={s['ticker']}&e={s['estrategia']}"
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
        st.caption("— Sin oportunidades que cumplan el filtro aquí ahora mismo. —")
        return 0
    cols = st.columns(ncols)
    for i, s in enumerate(mostrados):
        with cols[i % ncols]:
            tarjeta_compacta(s, f"{key_prefix}_{i}", moonshot=moonshot)
    return len(mostrados)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.markdown(ESTILO, unsafe_allow_html=True)


def _puerta_contrasena():
    """Candado simple: si hay una contraseña configurada (RADAR_PASSWORD), la pide.
    En local, si no hay contraseña configurada, el candado se desactiva solo."""
    import os
    esperada = os.environ.get("RADAR_PASSWORD")
    if not esperada:
        try:
            esperada = st.secrets.get("password")
        except Exception:
            esperada = None
    if not esperada:                       # sin contraseña configurada -> abierto (uso local)
        return
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
        ["🏠 Dashboard (3 universos)", "Método puro: S&P 500",
         "Motor paralelo: fuera del S&P 500", "Solo ETFs base (5)"],
        help="Dashboard: los tres universos juntos en secciones. "
             "Las otras vistas son para enfocarte en uno solo.")
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

    # --- filtros (sin "mínimo de condiciones": el ranking lo hace solo) ---
    with st.container(border=True):
        f1, f2 = st.columns([1.2, 1.6])
        d_dir = f1.radio("Dirección", ["Ambas", "Solo CALL (sube)", "Solo PUT (baja)"])
        d_orden = f2.radio("Ordenar por",
                           ["💡 Valor esperado (matemática)", "🎯 Oportunidad (equilibrio)",
                            "💥 Rentabilidad (más ganancia)", "🛡️ Confiabilidad (más segura)"],
                           help="Valor esperado = la forma más objetiva: combina probabilidad y ganancia.")
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

    for emoji_titulo, subt, indice, keyp in secciones:
        # sin filtro de condiciones: se rankea solo. Piso mínimo 3/5 (automático).
        lista = aplicar_filtros(por_indice[indice], 3, d_dir, not d_incluir_vig, d_orden)
        # ordenar por Valor Esperado (requiere prima real; se calcula sobre el pool top)
        if d_orden.startswith("💡") and lista:
            pool = lista[:15]
            for s in pool:
                calcular_ve(s)
            lista = sorted(pool, key=lambda s: -(s.get("_ve") if s.get("_ve") is not None else -1))
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
                               help="En mercado de caídas, los PUT ganan. Aquí eliges.")
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
