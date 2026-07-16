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
from engine import backtest, earnings, notify, opcion_real, premarket, screener

ESTADO = Path(__file__).resolve().parent / "data" / "cache" / "alertas_estado.json"
INTERVALO_DEF = 10  # minutos


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

    # SOLO avisar en la VENTANA DE COMPRA (11am–4pm ET). Antes de las 11 no se
    # compran calls (regla de Cardona) y después de las 4 el mercado cerró:
    # avisar fuera de esa franja es ruido, porque no vas a comprar.
    if not (11 <= ahora.hour < 16):
        print(f"[{ahora.strftime('%H:%M')}] fuera de la ventana de compra (11am–4pm); sin alertas.")
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
        # SOLO CALLS por ahora: el método del día 1 (que ya validamos) es de compras.
        # Los PUTS tienen una excepción de horario que Cardona explica en el día 2;
        # hasta tenerlo, nuestra lógica de tiempo para puts es incorrecta -> no avisar.
        if s["direccion"] != "call":
            continue
        intervalo = ESTRATEGIAS.get(s["estrategia"], {}).get("intervalo", "1d")
        es_intra = intervalo == "1h"
        # las diarias se deciden al cierre: no avisar antes de las 3pm ET
        if not es_intra and ahora.hour < 15:
            continue
        clave = f"{s['ticker']}|{s['estrategia']}|{hoy}"
        if clave in estado["avisadas"]:
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
        print(f"Escaneo único: {n} alerta(s) nueva(s).")
        return

    while True:
        ahora = datetime.now(premarket.ET)
        en_ventana = premarket.estado_sesion() == "abierto" and 11 <= ahora.hour < 16
        if en_ventana:
            try:
                n = escanear_y_avisar()
                print(f"[{ahora.strftime('%H:%M')}] escaneo ok; {n} alertas nuevas.")
            except Exception as e:
                print(f"[vigilante] error en escaneo: {e}")
        else:
            print(f"[{ahora.strftime('%H:%M')}] fuera de la ventana de compra (11am–4pm ET); en pausa.")
        time.sleep(cada * 60)


if __name__ == "__main__":
    main()
