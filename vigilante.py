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

from config import (UNIVERSO, UNIVERSO_NUCLEO, VIGILANTE_SOLO_RAPIDAS,
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
    """Un ciclo: escanea el núcleo y avisa SOLO las entradas rápidas nuevas (×2 en ~1 día)."""
    hoy = datetime.now(premarket.ET).date().isoformat()
    estado = _cargar_estado()
    if estado.get("fecha") != hoy:
        estado = {"fecha": hoy, "avisadas": []}  # nuevo día, borrón y cuenta nueva

    ops = screener.escanear_universo(tickers=UNIVERSO_NUCLEO,
                                     incluir_horario=True, con_backtest=False)
    nuevas = 0
    for s in ops:
        if s["estado"] != "ENTRADA":
            continue
        clave = f"{s['ticker']}|{s['estrategia']}|{hoy}"
        if clave in estado["avisadas"]:
            continue
        # SOLO avisamos las rápidas (×2 en ~1 día)
        rapida, p2, t2 = _es_rapida_x2(s)
        if VIGILANTE_SOLO_RAPIDAS and not rapida:
            continue
        tt = f"{t2*24:.0f}h" if (t2 is not None and t2 < 1) else f"~{t2:.0f}d"
        titulo = f"⚡ RÁPIDA {s['ticker']} {s['direccion'].upper()} — ×2 en {tt}"
        extra = f"\n🎯 ×2: {p2:.0f}% en {tt} (esto es lo que buscas)"
        notify.enviar(titulo, _texto_alerta(s) + extra)
        estado["avisadas"].append(clave)
        nuevas += 1
        print(f"[{datetime.now().strftime('%H:%M')}] 🔔 ALERTA RÁPIDA: {titulo}")

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
        sesion = premarket.estado_sesion()
        if sesion in ("pre", "abierto"):
            try:
                n = escanear_y_avisar()
                print(f"[{datetime.now().strftime('%H:%M')}] escaneo ok ({sesion}); {n} alertas nuevas.")
            except Exception as e:
                print(f"[vigilante] error en escaneo: {e}")
        else:
            print(f"[{datetime.now().strftime('%H:%M')}] mercado {sesion}; en pausa.")
        time.sleep(cada * 60)


if __name__ == "__main__":
    main()
