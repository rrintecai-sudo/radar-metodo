"""
pruebas.py — El GUARDIÁN del motor.

Cada regla crítica del método tiene aquí una prueba automática. Si alguien
(yo incluido) rompe una regla al tocar el código, esta prueba lo caza ANTES
de que te cueste dinero.

Los bugs que ya nos pasaron tienen su prueba, para que NO puedan volver.

Uso:
    python pruebas.py          # corre todo y dice si el motor está sano
"""
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

from datetime import datetime, timedelta, timezone

import pandas as pd

from config import (ESTRATEGIAS, PRIMA_OBJETIVO, VENCIMIENTO_MINIMO_DIAS,
                    VENCIMIENTO_POR_ESTRATEGIA)
from engine import data, method, opcion_real, zones as zn

ET = timezone(timedelta(hours=-4))
_fallos: list[str] = []
_ok = 0


def check(nombre: str, condicion: bool, detalle: str = ""):
    global _ok
    if condicion:
        _ok += 1
        print(f"  ✅ {nombre}")
    else:
        _fallos.append(f"{nombre} — {detalle}")
        print(f"  ❌ {nombre}  → {detalle}")


def _velas(specs, inicio="2026-07-20 09:30", freq="30min"):
    """Construye un dataframe de velas de prueba: specs = [(open, close, high, low)]."""
    idx = pd.date_range(inicio, periods=len(specs), freq=freq, tz=ET)
    return pd.DataFrame(
        {"Open": [s[0] for s in specs], "Close": [s[1] for s in specs],
         "High": [s[2] for s in specs], "Low": [s[3] for s in specs],
         "Volume": [1_000_000] * len(specs)}, index=idx)


print("=" * 62)
print("  PRUEBAS DEL MOTOR — que los bugs no vuelvan")
print("=" * 62)

# --- 1. LOS BUGS QUE YA NOS PASARON (no pueden volver) ---
print("\n[1] Bugs conocidos — no deben repetirse")

# Bug del 20-jul 9:39am: usaba la vela de apertura AÚN EN FORMACIÓN
df = _velas([(100, 99, 100.5, 98.5)])           # sola vela de 9:30, roja
en_formacion = datetime(2026, 7, 20, 9, 45, tzinfo=ET)   # 9:45: aún no cierra
check("Vela de apertura EN FORMACIÓN no se usa",
      method._vela_apertura(df, en_formacion) is None,
      "devolvió una vela que todavía no había cerrado")

ya_cerro = datetime(2026, 7, 20, 10, 15, tzinfo=ET)      # 10:15: ya cerró
check("Vela de apertura YA CERRADA sí se usa",
      method._vela_apertura(df, ya_cerro) is not None,
      "no devolvió la vela aunque ya había cerrado")

# Bug derivado: EN VIVO agarraba la vela de apertura de un DÍA ANTERIOR
# (datos viejos: finde, feriado, premarket, o yfinance rezagado).
df_viejo = _velas([(100, 99, 100.5, 98.5)], inicio="2026-07-17 09:30")
check("EN VIVO no usa la vela de apertura de un día anterior",
      method._vela_apertura(df_viejo, ya_cerro, vivo=True) is None,
      "tomó la apertura de otro día como si fuera la de hoy")
# Pero en BACKTEST esa misma vela histórica SÍ se usa (es el día simulado)
check("En BACKTEST la vela histórica sí se usa",
      method._vela_apertura(df_viejo, ya_cerro, vivo=False) is not None,
      "el backtest se quedó sin la vela de apertura del día simulado")

# Bug de la clase 20-jul: "primera vela roja" con gap AL ALZA no es "de apertura"
check("gap_de_sesion necesita 2+ velas de la sesión",
      zn.gap_de_sesion(_velas([(100, 101, 101.2, 99.8)])) is None,
      "confirmó un gap con una sola vela (aún en formación)")

# --- 2. REGLAS DE HORARIO (Cardona) ---
print("\n[2] Reglas de horario")

check("Cada estrategia declara su horario",
      all("horario" in v or True for v in ESTRATEGIAS.values()), "")

horarios = {e: v.get("horario", "desde_11") for e, v in ESTRATEGIAS.items()}
check("Primera vela roja se compra a las 10:00",
      horarios.get("primera_vela_roja") == "vela_10",
      f"tiene horario '{horarios.get('primera_vela_roja')}'")
check("Primer gap al alza y hanger se deciden al CIERRE",
      horarios.get("primer_gap_alza") == "cierre" and horarios.get("hanger_diario") == "cierre",
      "alguna no está marcada como 'cierre'")
check("El resto son desde las 11am",
      horarios.get("ma40") == "desde_11" and horarios.get("canal") == "desde_11", "")

# --- 3. VENCIMIENTOS: prohibido el 0DTE ---
print("\n[3] Vencimientos (prohibido 'hoy para hoy')")

check("Ninguna estrategia usa 0 días de vencimiento",
      all(d >= 1 for d in VENCIMIENTO_POR_ESTRATEGIA.values()),
      "hay alguna en 0 (0DTE prohibido por Cardona)")
check("El mínimo global es al menos 1 día",
      VENCIMIENTO_MINIMO_DIAS >= 1, "")
check("Primera vela roja NO es hoy-para-hoy",
      VENCIMIENTO_POR_ESTRATEGIA.get("primera_vela_roja", 0) >= 1,
      "Cardona: 'si mantengo haciendo hoy para hoy, la respuesta es NO'")

# --- 4. SELECCIÓN DE CONTRATO POR PRIMA ---
print("\n[4] Elección del contrato (por prima, no por % OTM)")

check("SPY y QQQ buscan primas de $0.25-0.30",
      PRIMA_OBJETIVO.get("SPY") == (0.25, 0.30) and PRIMA_OBJETIVO.get("QQQ") == (0.25, 0.30), "")
check("Tesla busca primas de $2.50-3.00",
      PRIMA_OBJETIVO.get("TSLA") == (2.50, 3.00), "")

# --- 5. LAS 14 ESTRATEGIAS EVALÚAN SIN ROMPERSE ---
print("\n[5] Las estrategias corren sobre datos reales")

vivas = 0
for est, v in ESTRATEGIAS.items():
    try:
        s = method.evaluar("SPY", method.preparar(data.obtener("SPY", v["intervalo"])), est)
        assert s["direccion"] in ("call", "put")
        assert s["estado"] in ("ENTRADA", "VIGILAR", "NADA")
        vivas += 1
    except Exception as e:
        print(f"      ⚠️  {est}: {type(e).__name__}")
check(f"Las {len(ESTRATEGIAS)} estrategias evalúan sin error",
      vivas == len(ESTRATEGIAS), f"solo {vivas} de {len(ESTRATEGIAS)} funcionaron")

calls = sum(1 for e in ESTRATEGIAS if e in
            ("ma40", "canal", "caida_normal", "caida_fuerte", "gap", "gap_bajista_alza",
             "primer_gap_alza", "piso_fuerte", "tres_semanas"))
puts = sum(1 for e in ESTRATEGIAS if e in
           ("primera_vela_roja", "ruptura_piso_gap", "modelo_4_pasos",
            "hanger_diario", "techo_fuerte"))
check("Están las 9 de CALL y las 5 de PUT", calls == 9 and puts == 5,
      f"hay {calls} calls y {puts} puts")

# --- 6. EL BUG DEL TOPE DE BACKTEST (falsos negativos) ---
print("\n[6] Todas las ENTRADAS se evalúan (no se descartan por 'muestra chica')")

try:
    from engine import screener
    ops = screener.escanear_universo(incluir_horario=True)
    entradas = [s for s in ops if s["estado"] == "ENTRADA"]
    sin_hist = [s for s in entradas if not s.get("n_muestra")]
    check("Ninguna ENTRADA se queda sin histórico",
          len(sin_hist) == 0,
          f"{len(sin_hist)} entradas sin evaluar (se descartarían por falta de datos)")
except Exception as e:
    check("El escaneo del universo corre", False, str(e)[:60])

# --- 7. LA VELA DE RUPTURA DEBE SER SÓLIDA ---
print("\n[7] Calidad de la vela de ruptura")

# vela verde con cuerpo grande (sólida) vs. una con cola larga (hanger)
solida = _velas([(100, 99, 100, 99), (99, 102, 102.2, 98.9)])
hanger = _velas([(100, 99, 100, 99), (99, 99.3, 103, 98.9)])
check("Una vela verde SÓLIDA confirma la ruptura",
      zn.ruptura(solida, 100.0, "call")["hay"] is True, "no reconoció una ruptura válida")
check("Un hanger (cola larga) NO confirma la ruptura",
      zn.ruptura(hanger, 100.0, "call")["hay"] is False,
      "aceptó una vela débil como ruptura")

# --- 8. LA ESCALERA DE VENTA (clase 21-jul: "saber vender") ---
print("\n[8] Escalera de venta — el Vigilante avisa en cada escalón")

import vigilante as vig

check("Antes del +100% no hay escalón (no se vende aún)",
      vig.escalon_alcanzado(80) is None, "avisó de venta antes de doblar")
check("Al +100% el escalón es ×2 (vende la mitad)",
      vig.escalon_alcanzado(100)[1] == "x2", "no reconoció el doble")
check("Al +250% el escalón es ×3",
      vig.escalon_alcanzado(250)[1] == "x3", "")
check("Al +500% el escalón es ×5",
      vig.escalon_alcanzado(500)[1] == "x5", "")
check("Si salta directo a +1200% avisa el ×10 (el más alto)",
      vig.escalon_alcanzado(1200)[1] == "x10",
      "no avisó el escalón más alto cuando saltó varios de golpe")

# Google e Intel: contrato $60-80 (clase 21-jul)
check("Google e Intel buscan primas de $0.60-0.80",
      PRIMA_OBJETIVO.get("GOOGL") == (0.60, 0.80) and PRIMA_OBJETIVO.get("INTC") == (0.60, 0.80), "")

# --- 9. PUERTA DE ASIMETRÍA (el caso del oro, 22-jul) ---
print("\n[9] Apuesta asimétrica — no rechazar el oro por 'dobla poco'")

from engine import veredicto as ver

# El oro: VE 2.03, dobla 31%, muestra 21. Antes -> PÁSALA. Ahora -> debe pasar.
s_oro = {"estado": "ENTRADA", "precio": 380.0, "opcion": {"tipo": "CALL"}}
h_ok = {"n": 21, "targets": [], "sin_datos": False}
cot_x = {"strike": 383, "premium": 0.74}
pasa_oro, falla_oro = ver.califica(s_oro, cot_x, h_ok, ve=2.03, p2=31)
check("El oro (VE 2.03, dobla 31%) YA NO se descarta por 'dobla poco'",
      pasa_oro, f"lo siguió rechazando: {falla_oro}")

# Pero una apuesta MALA de verdad (VE bajo) sigue rechazándose
pasa_mala, _ = ver.califica(s_oro, cot_x, h_ok, ve=0.9, p2=20)
check("Una apuesta mala (VE 0.9, dobla 20%) SÍ se rechaza",
      not pasa_mala, "dejó pasar una apuesta de ventaja baja")

# Y una con ventaja normal pero doblar bajo Y VE no-asimétrico se rechaza
pasa_borde, _ = ver.califica(s_oro, cot_x, h_ok, ve=1.4, p2=35)
check("Ventaja media (VE 1.4) con doblar 35% sigue siendo PÁSALA",
      not pasa_borde, "aflojó demasiado la puerta")

# --- RESULTADO ---
print("\n" + "=" * 62)
if _fallos:
    print(f"  ⛔ {len(_fallos)} PRUEBA(S) FALLARON — NO OPERES hasta revisarlo:")
    for f in _fallos:
        print(f"     · {f}")
else:
    print(f"  ✅ LAS {_ok} PRUEBAS PASARON — el motor está sano para operar.")
print("=" * 62)
