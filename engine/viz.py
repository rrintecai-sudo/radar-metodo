"""
viz.py — La gráfica que EXPLICA la señal (estilo limpio, oscuro, tipo uCharts).

Dibuja, encima de un gráfico de velas limpio y oscuro, lo que el motor "vio":
  - los promedios móviles que importan (líneas finas, colores tipo uCharts)
  - la línea de techo bajista o las líneas del canal
  - el piso fuerte histórico
  - el punto exacto de la RUPTURA (con estrella)
  - la vela de señal (martillo / hanger / sólida) marcada
  - el precio actual y el strike sugerido

Principio de diseño: limpio primero. Pocas líneas, finas, y el eje vertical
pegado al rango de las velas para que se vean grandes y claras.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# --- paleta (fondo claro/crema, limpio) ---
FONDO = "#FFFFFF"
REJILLA = "#ECE7DE"
TEXTO = "#2A2E35"
VERDE = "#12A06A"      # velas al alza / confirmaciones alcistas
ROJO = "#E0514E"       # velas a la baja
AMBAR = "#C9930A"      # señales / línea de techo (ámbar oscuro para verse en claro)
COL_MA = {20: "#C9930A", 40: "#E0514E", 100: "#12A06A", 200: "#8E44AD"}  # PM20/40/100/200


def veredicto(senal: dict) -> dict:
    """Traduce el estado en un veredicto claro tipo semáforo para mostrar arriba."""
    etiquetas = {"zona": "zona", "media": "confluencia con promedio",
                 "soporte": "soporte", "vela": "vela de señal", "ruptura": "ruptura confirmada"}
    if senal["estado"] == "ENTRADA":
        return {"nivel": "go", "titulo": "✅ SÍ, ADELANTE",
                "texto": "Cumple zona extrema + confirmación por ruptura. "
                         "Revisa el calendario de eventos y ejecuta según tu gestión de riesgo."}
    if senal["estado"] == "VIGILAR":
        faltan = ", ".join(etiquetas.get(k, k) for k in senal["faltan"])
        return {"nivel": "wait", "titulo": "⏳ AÚN NO — en vigilancia",
                "texto": f"Está en zona, pero falta: {faltan}. Espera la confirmación (la ruptura)."}
    return {"nivel": "no", "titulo": "⛔ NO — esperar",
            "texto": "No se cumplen las condiciones del método. La mayoría de los días toca esperar."}


def figura_detallada(df: pd.DataFrame, senal: dict, n_velas: int = 60) -> go.Figure:
    """Construye la gráfica anotada, limpia y oscura, para una señal concreta."""
    geo = senal.get("geo", {})
    tail = df.iloc[-n_velas:]
    fig = go.Figure()

    # --- velas (finas, colores limpios) ---
    fig.add_trace(go.Candlestick(
        x=tail.index, open=tail["Open"], high=tail["High"],
        low=tail["Low"], close=tail["Close"], name=senal["ticker"],
        increasing=dict(line=dict(color=VERDE, width=1), fillcolor=VERDE),
        decreasing=dict(line=dict(color=ROJO, width=1), fillcolor=ROJO),
        whiskerwidth=0.4, showlegend=False))

    # --- promedios móviles: finos; los de la estrategia, un pelín más marcados ---
    enfasis = set(geo.get("enfasis_medias", []))
    for p, col in COL_MA.items():
        c = f"MA{p}"
        if c not in tail:
            continue
        resaltado = p in enfasis
        fig.add_trace(go.Scatter(
            x=tail.index, y=tail[c], name=f"PM{p}",
            line=dict(color=col, width=1.8 if resaltado else 1.0),
            opacity=1.0 if resaltado else 0.55))

    anotaciones = []

    # --- línea de techo bajista (estrategia MA40) ---
    lb = geo.get("linea_bajista")
    if lb:
        v = lb["ventana"]
        seg = tail.iloc[-v:] if len(tail) >= v else tail
        x0, x1 = seg.index[0], seg.index[-1]
        y0 = lb["b"]
        y1 = lb["m"] * (len(seg) - 1) + lb["b"]
        fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                                 line=dict(color=AMBAR, width=1.6, dash="dot"),
                                 showlegend=False, hoverinfo="skip"))
        anotaciones.append(dict(x=x0, y=y0, text="Línea de techo", showarrow=False,
                                xanchor="left", yanchor="bottom",
                                font=dict(color=AMBAR, size=11)))

    # --- canal (estrategia canal): dos líneas finas + relleno muy tenue ---
    canal = geo.get("canal")
    if canal:
        v = canal["ventana"]
        seg = tail.iloc[-v:] if len(tail) >= v else tail
        x0, x1 = seg.index[0], seg.index[-1]
        n = len(seg)
        yt0, yt1 = canal["b_techo"], canal["m_techo"] * (n - 1) + canal["b_techo"]
        yp0, yp1 = canal["b_piso"], canal["m_piso"] * (n - 1) + canal["b_piso"]
        fig.add_trace(go.Scatter(x=[x0, x1], y=[yp0, yp1], mode="lines",
                                 line=dict(color=VERDE, width=1.4), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[x0, x1], y=[yt0, yt1], mode="lines",
                                 line=dict(color=ROJO, width=1.4), fill="tonexty",
                                 fillcolor="rgba(241,196,15,0.05)", showlegend=False, hoverinfo="skip"))
        anotaciones.append(dict(x=x0, y=yt0, text=f"Canal {canal['direccion']}", showarrow=False,
                                xanchor="left", yanchor="bottom", font=dict(color=ROJO, size=11)))

    # --- piso fuerte (estrategias piso fuerte / tres semanas) ---
    piso = geo.get("piso")
    if piso:
        fig.add_hline(y=piso["precio"], line_color=VERDE, line_width=1.6,
                      annotation_text=f"Piso fuerte {piso['precio']:.1f} · {piso['toques']} toques",
                      annotation_position="bottom left",
                      annotation_font=dict(color=VERDE, size=11))

    # --- punto de RUPTURA (estrella) ---
    rup = geo.get("ruptura")
    if rup and rup.get("hay"):
        xr = tail.index[-1]
        yr = rup.get("linea", float(tail["Close"].iloc[-1]))
        fig.add_trace(go.Scatter(x=[xr], y=[yr], mode="markers",
                                 marker=dict(symbol="star", size=15, color=AMBAR,
                                             line=dict(color=FONDO, width=1)),
                                 showlegend=False, hoverinfo="skip"))
        anotaciones.append(dict(x=xr, y=yr, text="⚡ Ruptura", showarrow=True, arrowhead=2,
                                arrowcolor=AMBAR, ax=-38, ay=-38,
                                font=dict(color=AMBAR, size=12),
                                bgcolor="rgba(255,255,255,0.9)", bordercolor=AMBAR))

    # --- vela de señal ---
    if geo.get("vela_ok"):
        patron = {"martillo": "Martillo", "verde_solida": "Verde sólida",
                  "hanger": "Hanger", "roja_solida": "Roja sólida"}.get(
                      geo.get("vela_patron"), "Señal")
        vela = tail.iloc[-1]
        y_marca = float(vela["Low"]) * 0.998
        fig.add_trace(go.Scatter(x=[tail.index[-1]], y=[y_marca], mode="markers+text",
                                 marker=dict(symbol="triangle-up", size=11, color=AMBAR),
                                 text=[patron], textposition="bottom center",
                                 textfont=dict(color=AMBAR, size=10),
                                 showlegend=False, hoverinfo="skip"))

    # --- precio actual y strike (sutiles, a la derecha) ---
    fig.add_hline(y=senal["precio"], line_dash="dash", line_color="#6B7684", line_width=1,
                  annotation_text=f"{senal['precio']:.2f}", annotation_position="right",
                  annotation_font=dict(color="#9AA4AF", size=10))
    fig.add_hline(y=senal["opcion"]["strike"], line_dash="dashdot", line_color="#5A6472", line_width=1,
                  annotation_text=f"strike {senal['opcion']['strike']}", annotation_position="right",
                  annotation_font=dict(color="#7C8794", size=10))

    # --- eje Y pegado al rango de las velas (para que se vean grandes) ---
    lo, hi = float(tail["Low"].min()), float(tail["High"].max())
    # incluir el piso si está cerca, sin dejar que un MA lejano comprima las velas
    if piso and (lo * 0.985) <= piso["precio"] <= (hi * 1.015):
        lo, hi = min(lo, piso["precio"]), max(hi, piso["precio"])
    pad = (hi - lo) * 0.06
    yrange = [lo - pad, hi + pad]

    fig.update_layout(
        height=560, margin=dict(l=8, r=8, t=34, b=8),
        paper_bgcolor=FONDO, plot_bgcolor=FONDO, font=dict(color=TEXTO),
        xaxis=dict(rangeslider_visible=False, gridcolor=REJILLA, showgrid=True,
                   rangebreaks=[dict(bounds=["sat", "mon"])]),  # sin huecos de fin de semana
        yaxis=dict(range=yrange, gridcolor=REJILLA, side="right", showgrid=True),
        title=dict(text=f"{senal['ticker']} · {senal['estrategia_nombre']} ({senal['marco']}) — {senal['direccion'].upper()}",
                   font=dict(size=14, color=TEXTO)),
        annotations=anotaciones,
        legend=dict(orientation="h", y=1.05, x=0, font=dict(size=11)),
        hovermode="x unified")
    return fig


def leyenda_markdown(senal: dict) -> str:
    """Texto que explica, en palabras, qué está dibujado en la gráfica."""
    geo = senal.get("geo", {})
    lineas = ["**Cómo leer la gráfica (reconfirma con tu ojo):**"]
    if geo.get("piso"):
        lineas.append(f"- **Línea verde horizontal** = el *piso fuerte* histórico "
                      f"({geo['piso']['toques']} rebotes previos). El precio debería frenar y rebotar ahí.")
    if geo.get("linea_bajista"):
        lineas.append("- **Línea amarilla punteada** = la *línea de techo* de la caída. "
                      "Se entra cuando una vela verde la **rompe hacia arriba**.")
    if geo.get("canal"):
        lineas.append(f"- **Banda sombreada** = el *canal {geo['canal']['direccion']}* "
                      "(techo rojo / piso verde). La entrada es la **ruptura** de una de sus líneas.")
    ema = geo.get("enfasis_medias", [])
    if ema:
        lineas.append(f"- **Promedios resaltados**: {', '.join('PM'+str(p) for p in ema)} "
                      "(las zonas dinámicas de rebote). Los demás quedan tenues de fondo.")
    if geo.get("vela_ok"):
        lineas.append("- **Triángulo amarillo** en la última vela = la *vela de señal* que confirma el giro.")
    if geo.get("ruptura", {}).get("hay"):
        lineas.append("- **⚡ Estrella** = el punto exacto de la **ruptura** (la confirmación de Cardona).")
    else:
        lineas.append("- Todavía **no hay ruptura**: por eso está en *vigilancia*, no en *entrada*.")
    lineas.append("- **Líneas grises a la derecha** = el *precio* actual y el *strike* OTM sugerido.")
    return "\n".join(lineas)
