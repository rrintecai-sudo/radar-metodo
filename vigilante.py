"""
vigilante.py — El guardián que vigila por ti.

Corre en segundo plano durante el horario de mercado, escanea el universo cada
pocos minutos, y cuando aparece una ENTRADA confirmada te AVISA (Mac + Telegram).
Así no tienes que estar pegado a la pantalla: sigues con tu vida y el motor te
da el toque solo cuando hay que actuar.

No repite alertas: cada señal se avisa una sola vez por día.

Uso:
    python vigilante.py              # cada 10 minutos (por defecto)
    python vigilante.py --cada 5     # cada 5 minutos
    python vigilante.py --ahora      # un solo escaneo ya (para probar)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from config import (ESTRATEGIAS, UNIVERSO, UNIVERSO_NUCLEO,
                    VIGILANTE_MAX_DIAS_X2, VIGILANTE_MIN_PROB_X2)
from engine import calendar as cal
from engine import (backtest, earnings, notify, opcion_real, premarket,
                    screener, veredicto)

ESTADO = Path(__file__).resolve().parent / "data" / "cache" / "alertas_estado.json"
INTERVALO_DEF = 10  # minutos

# 🪜 LA ESCALERA DE VENTA (clase en vivo 21-jul: "saber comprar y saber vender").
# Alejandro NO vende todo al doblar: vende por partes y deja correr hacia ×10-×20.
# (ganancia_min_%, clave, título, qué hacer)
ESCALERA_SALIDA = [
    (100,  "x2",  "🎉 ¡DOBLÓ! +100%",
     "VENDE LA MITAD — recuperas TODO tu capital. El resto queda corriendo GRATIS."),
    (200,  "x3",  "📈 ×3 — +200%",
     "Asegura ganancia: vende una parte más. Deja correr el resto hacia el ×10."),
    (400,  "x5",  "🚀 ×5 — +400%",
     "Vende otra parte. Con lo que quede vas por el billete grande. No lo botes por centavos."),
    (900,  "x10", "🏆 ×10 — +900%",
     "El billete de Alejandro. Vende casi todo; deja 1 corriendo o cierra. 'Saber vender.'"),
]


def escalon_alcanzado(ganancia_pct: float):
    """El escalón de venta MÁS alto que ya se superó (o None si aún no dobla)."""
    cruzados = [r for r in ESCALERA_SALIDA if ganancia_pct >= r[0]]
    return cruzados[-1] if cruzados else None


def _cargar_estado() -> dict:
    if ESTADO.exists():
        try:
            return json.loads(ESTADO.read_text())
        except Exception:
            pass
    return {"fecha": "", "avisadas": []}


def _guardar_estado(e: dict):
    try:
        ESTADO.write_text(json.dumps(e))
    except Exception:
        pass


def _texto_alerta(s: dict) -> str:
    m = UNIVERSO.get(s["ticker"], {})
    o = s["opcion"]
    lineas = [
        f"🎯 {s['ticker']} ({m.get('nombre','')}) — {s['direccion'].upper()}",
        f"Estrategia: {s['estrategia_nombre']} ({s['marco']})",
        f"Condiciones: {s['n_cond']}/5 · Precio: {s['precio']:.2f}",
        f"Opción: {o['tipo']} strike {o['strike']} (~{o['dias_vencimiento']}d)",
    ]
    # avisos de contexto (para decidir con criterio)
    es_accion = m.get("clase") == "accion"
    earn = earnings.contexto(s["ticker"], o["dias_vencimiento"], es_accion)
    if earn["nivel"] == "riesgo":
        lineas.append("⚠️ Earnings dentro de la vida de la opción")
    calc = cal.contexto_senal()
    if calc["nivel"] in ("peligro", "precaucion"):
        lineas.append(f"⚠️ Evento próximo: {calc.get('titulo','')}")
    return "\n".join(lineas)


def _es_rapida_x2(s: dict):
    """¿Puede dar ×2 en ~1 día? Devuelve (es_rapida, prob_x2, dias_x2) o (False, ...)."""
    o = s["opcion"]
    cot = opcion_real.cotizar(s["ticker"], o["tipo"], o["strike"], o["dias_vencimiento"])
    h = backtest.historial_senal(s["ticker"], s["estrategia"])
    if not cot or h.get("sin_datos"):
        return False, None, None
    p2 = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 2, o["tipo"])
    t2 = opcion_real.tiempo_de_multiplo(s["precio"], cot, h["targets"], 2, o["tipo"])
    rapida = (t2 is not None and t2 <= VIGILANTE_MAX_DIAS_X2 and p2 >= VIGILANTE_MIN_PROB_X2)
    return rapida, p2, t2


def escanear_y_avisar() -> int:
    """
    Un ciclo alineado al MÉTODO: escanea el núcleo y avisa TODAS las ENTRADAS
    nuevas que el motor aprueba (todas las estrategias, no solo las rápidas).
    Respeta las reglas de Cardona:
      - Día de la FED: no se opera -> no se avisa nada.
      - Estrategias INTRADÍA (1h): ya vienen filtradas por el motor (11am, vela
        final, vela sólida, zona cara) -> se avisan "tómala ya".
      - Estrategias DIARIAS (1d): se deciden cerca del cierre -> solo se avisan
        a partir de las 3pm ET (antes, la vela del día aún se está formando).
    """
    ahora = datetime.now(premarket.ET)
    hoy = ahora.date().isoformat()
    estado = _cargar_estado()
    if estado.get("fecha") != hoy:
        estado = {"fecha": hoy, "avisadas": []}  # nuevo día, borrón y cuenta nueva

    # El MERCADO tiene que estar ABIERTO de verdad (no basta con la hora:
    # un domingo a las 3pm la hora "cuadra" pero no hay mercado).
    if premarket.estado_sesion() != "abierto":
        print(f"[{ahora.strftime('%H:%M')}] mercado cerrado; sin alertas.")
        _guardar_estado(estado)
        return 0

    # SOLO avisar en la VENTANA DE COMPRA (10am–4pm ET). Empieza a las 10 porque
    # la 'primera vela roja de apertura' (PUT) se compra a las 10:00 en punto;
    # los calls siguen siendo desde las 11. Fuera de esa franja, avisar es ruido.
    if not (10 <= ahora.hour < 16):
        print(f"[{ahora.strftime('%H:%M')}] fuera de la ventana de compra (10am–4pm); sin alertas.")
        _guardar_estado(estado)
        return 0

    # REGLA DE CARDONA: el día de la reunión de la FED NO se invierte.
    if cal.es_dia_fed():
        print(f"[{ahora.strftime('%H:%M')}] 🏛️ Día de la FED: hoy no se opera, sin alertas.")
        _guardar_estado(estado)
        return 0

    ops = screener.escanear_universo(tickers=UNIVERSO_NUCLEO,
                                     incluir_horario=True, con_backtest=False)
    nuevas = 0
    for s in ops:
        if s["estado"] != "ENTRADA":
            continue
        # PUTS ACTIVOS: ya tenemos sus reglas del día 2 (primera vela roja de
        # apertura, ruptura del piso del gap, 4 pasos, hanger diario, techo fuerte).
        intervalo = ESTRATEGIAS.get(s["estrategia"], {}).get("intervalo", "1d")
        es_intra = intervalo in ("1h", "30m")
        # las diarias se deciden al cierre: no avisar antes de las 3pm ET
        if not es_intra and ahora.hour < 15:
            continue
        clave = f"{s['ticker']}|{s['estrategia']}|{hoy}"
        if clave in estado["avisadas"]:
            continue

        # ═══ MISMO CRITERIO QUE EL RADAR: solo se avisa lo que el veredicto aprueba.
        # (Antes el Vigilante avisaba cualquier ENTRADA y el Radar la rechazaba
        #  -> te llegaban alertas de señales que la web decía NO tomar.)
        o = s["opcion"]
        try:
            cot = opcion_real.cotizar_por_prima(s["ticker"], o["tipo"], s["precio"],
                                                o["dias_vencimiento"])
        except Exception:
            cot = None
        h = s.get("historial") or backtest.historial_senal(s["ticker"], s["estrategia"])
        es_accion = UNIVERSO.get(s["ticker"], {}).get("clase") == "accion"
        try:
            earn_riesgo = earnings.contexto(s["ticker"], o["dias_vencimiento"],
                                            es_accion).get("nivel") == "riesgo"
        except Exception:
            earn_riesgo = False
        pasa, motivos = veredicto.califica(s, cot, h, earnings_riesgo=earn_riesgo)
        if not pasa:
            print(f"[{ahora.strftime('%H:%M')}] — {s['ticker']} {s['estrategia']}: "
                  f"no califica ({'; '.join(motivos[:2])})")
            estado["avisadas"].append(clave)   # no repetir el análisis hoy
            continue

        if es_intra:
            titulo = f"✅ ENTRADA {s['ticker']} {s['direccion'].upper()} — {s['estrategia_nombre']} (tómala ya)"
            # etiqueta informativa si además es una ×2 rápida (ya no filtra, solo informa)
            rapida, p2, t2 = _es_rapida_x2(s)
            extra = ""
            if rapida and p2 is not None:
                tt = f"{t2 * 24:.0f}h" if (t2 is not None and t2 < 1) else f"~{t2:.0f}d"
                extra = f"\n⚡ Además puede ×2 en {tt} ({p2:.0f}%)"
        else:
            titulo = f"📅 ENTRADA {s['ticker']} {s['direccion'].upper()} — {s['estrategia_nombre']} (decide al cierre ~3:55)"
            extra = ""

        notify.enviar(titulo, _texto_alerta(s) + extra)
        estado["avisadas"].append(clave)
        nuevas += 1
        print(f"[{ahora.strftime('%H:%M')}] 🔔 {titulo}")

    _guardar_estado(estado)
    return nuevas


def revisar_salidas() -> int:
    """
    EL VIGILANTE DE SALIDAS — la otra mitad del trabajo.
    Recorre tus posiciones ABIERTAS de la bitácora y te avisa cuándo VENDER:
      1) 🎉 Dobló (+100%) -> vende la MITAD (recuperas todo tu capital)
      2) 🚪 Señal de salida -> primera vela ROJA del día (si tienes CALL)
                               o primera vela VERDE (si tienes PUT)
      3) ⏳ Vence pronto (<= 2 días) -> decide, no la dejes derretir
    Así no tienes que llevar los vencimientos en la cabeza.
    """
    from datetime import date
    from engine import bitacora, method, data

    ahora = datetime.now(premarket.ET)
    # las ventas también se vigilan solo con el mercado abierto (los precios
    # de fin de semana están congelados: avisar sería ruido).
    if premarket.estado_sesion() != "abierto":
        return 0
    hoy = ahora.date().isoformat()
    estado = _cargar_estado()
    if estado.get("fecha") != hoy:
        estado = {"fecha": hoy, "avisadas": []}

    abiertas = [t for lib in ("real", "simulacion") for t in bitacora.listar(lib, "abierta")]
    avisos = 0
    for t in abiertas:
        tk, direc = t["ticker"], t["direccion"]
        tipo = "CALL" if direc == "call" else "PUT"
        strike = float(t.get("strike") or 0)
        pe = float(t.get("prima_entrada") or 0)
        # CANDADO: sin strike o sin prima no se puede cotizar -> no inventamos avisos
        if strike <= 0 or pe <= 0:
            continue
        etiqueta = f"{tk} {tipo} {strike:g}"

        # --- 1) ¿cuánto vale AHORA? ¿ya dobló? ---
        try:
            venc = t.get("vencimiento") or ""
            dias = (date.fromisoformat(venc) - date.today()).days if venc else 7
            cot = opcion_real.cotizar(tk, tipo, strike, max(1, dias))
        except Exception:
            cot, dias = None, None
        # CANDADO: el contrato cotizado tiene que ser REALMENTE el suyo (mismo strike)
        if cot and abs(cot["strike"] - strike) / strike > 0.02:
            cot = None
        if cot:
            ganancia = (cot["premium"] - pe) / pe * 100 if pe else 0
            # 🪜 escalera: avisa el escalón MÁS alto alcanzado (×2 → ×3 → ×5 → ×10),
            # cada uno una sola vez. Si saltó varios de golpe, avisa el mayor y marca
            # los inferiores como ya avisados (no rebobina).
            r = escalon_alcanzado(ganancia)
            if r:
                clave = f"salida_{r[1]}|{t['id']}|{hoy}"
                if clave not in estado["avisadas"]:
                    notify.enviar(
                        f"{r[2]} — {etiqueta}",
                        f"Entrada ${pe} → ahora ${cot['premium']} (+{ganancia:.0f}%)\n"
                        f"{r[3]}\n"
                        f"Tienes {t['contratos']} contrato(s).")
                    # marca este escalón y todos los inferiores como avisados
                    for rr in ESCALERA_SALIDA:
                        if rr[0] <= r[0]:
                            c2 = f"salida_{rr[1]}|{t['id']}|{hoy}"
                            if c2 not in estado["avisadas"]:
                                estado["avisadas"].append(c2)
                    avisos += 1
                    print(f"[{ahora.strftime('%H:%M')}] {r[1]}: {etiqueta} (+{ganancia:.0f}%)")

        # --- 2) ¿apareció la señal de SALIDA? (primera vela del día) ---
        try:
            df30 = method.preparar(data.obtener(tk, "30m"))
            v = method._vela_apertura(df30, vivo=True)
        except Exception:
            v = None
        if v is not None and ahora.hour >= 10:
            roja = float(v["Close"]) < float(v["Open"])
            salir = roja if direc == "call" else (not roja)
            if salir:
                clave = f"salida_senal|{t['id']}|{hoy}"
                if clave not in estado["avisadas"]:
                    q = "ROJA" if roja else "VERDE"
                    notify.enviar(
                        f"🚪 SEÑAL DE SALIDA — {etiqueta}",
                        f"La primera vela del día abrió {q}: es la señal de Cardona para "
                        f"cerrar lo que te quede de esta posición.\n"
                        f"(Si ya vendiste la mitad al +100%, vende el resto.)")
                    estado["avisadas"].append(clave); avisos += 1
                    print(f"[{ahora.strftime('%H:%M')}] 🚪 señal de salida: {etiqueta}")

        # --- 3) ¿se acerca el vencimiento? ---
        if dias is not None and 0 <= dias <= 2:
            clave = f"vence|{t['id']}|{hoy}"
            if clave not in estado["avisadas"]:
                cuando = "HOY" if dias == 0 else ("MAÑANA" if dias == 1 else f"en {dias} días")
                notify.enviar(
                    f"⏳ VENCE {cuando} — {etiqueta}",
                    f"Tu contrato vence {cuando} ({t.get('vencimiento','')}).\n"
                    f"Decide: vende lo que quede o déjalo expirar. "
                    f"NO lo dejes derretir esperando que 'cobre solo' — el vencimiento no paga.")
                estado["avisadas"].append(clave); avisos += 1
                print(f"[{ahora.strftime('%H:%M')}] ⏳ vence {cuando}: {etiqueta}")

    _guardar_estado(estado)
    return avisos


def main():
    cada = INTERVALO_DEF
    if "--cada" in sys.argv:
        try:
            cada = int(sys.argv[sys.argv.index("--cada") + 1])
        except Exception:
            pass
    una_vez = "--ahora" in sys.argv

    print("=" * 60)
    print("  VIGILANTE DEL MÉTODO — te aviso cuando haya una entrada")
    print(f"  Canales: Mac ✅  ·  Telegram {'✅' if notify.telegram_configurado() else '❌ (sin configurar)'}")
    print("=" * 60)

    if una_vez:
        n = escanear_y_avisar()
        s = revisar_salidas()
        print(f"Escaneo único: {n} alerta(s) de COMPRA, {s} de VENTA.")
        return

    while True:
        ahora = datetime.now(premarket.ET)
        abierto = premarket.estado_sesion() == "abierto"
        # COMPRAS: solo en la ventana 10am-4pm (fuera de ahí es ruido)
        if abierto and 10 <= ahora.hour < 16:
            try:
                n = escanear_y_avisar()
                print(f"[{ahora.strftime('%H:%M')}] compras: {n} alertas nuevas.")
            except Exception as e:
                print(f"[vigilante] error en escaneo de compras: {e}")
        else:
            print(f"[{ahora.strftime('%H:%M')}] fuera de la ventana de compra (10am–4pm ET).")
        # VENTAS: se vigilan durante TODA la sesión (una salida puede aparecer
        # a cualquier hora, y el aviso de vencimiento también).
        if abierto:
            try:
                s = revisar_salidas()
                if s:
                    print(f"[{ahora.strftime('%H:%M')}] ventas: {s} avisos.")
            except Exception as e:
                print(f"[vigilante] error revisando salidas: {e}")
        time.sleep(cada * 60)


if __name__ == "__main__":
    main()
