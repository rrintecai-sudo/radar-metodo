"""
veredicto.py — LA ÚNICA FUENTE DE VERDAD sobre si una señal se toma o no.

Antes había dos criterios distintos: el Vigilante avisaba cualquier ENTRADA y
el Radar aplicaba filtros adicionales. Resultado: te llegaba una alerta de algo
que la web te decía que NO tomaras. Confusión total.

Ahora los dos (Radar y Vigilante) preguntan aquí. Un solo criterio, una sola
respuesta.

LAS 4 OBLIGATORIAS (si falla una, se pasa):
  1. Entrada CONFIRMADA (zona + ruptura del método)
  2. Ventaja matemática: valor esperado >= 1.2
  3. Probabilidad de DOBLAR >= 50%
  4. Muestra histórica >= 12 casos
  + BLOQUEO: reporte de resultados dentro de la vida de la opción
"""
from __future__ import annotations

VE_MINIMO = 1.2          # por cada $1 arriesgado, esperar al menos $1.20
PROB_X2_MINIMA = 50      # probabilidad de doblar
MUESTRA_MINIMA = 12      # casos históricos para fiarse del porcentaje

# ── PUERTA DE ASIMETRÍA ──────────────────────────────────────────────────────
# El oro (22-jul) doblaba solo el 31% de las veces, PERO cuando pega hace ×5-×7
# (VE 2.0+). Ese es el corazón del método: riesgo topado + salto enorme. Exigir
# "50% de doblar" mataba justo esas apuestas. Ahora, con ventaja alta y ALGO de
# chance del gran salto, la baja frecuencia de doblar se acepta.
VE_ASIMETRICO = 1.8       # con esta ventaja, no se exige el 50% de doblar
PROB_X2_PISO_ASIM = 25    # pero necesita algo de chance del gran salto (no lotería pura)


def califica(s: dict, cot: dict | None, h: dict | None,
             ve: float | None = None, p2: float | None = None,
             earnings_riesgo: bool = False) -> tuple[bool, list[str]]:
    """
    ¿Esta señal cumple lo mínimo para tomarla?
    Devuelve (pasa_o_no, lista_de_motivos_por_los_que_falla).
    """
    from engine import opcion_real

    falla: list[str] = []

    if s.get("estado") != "ENTRADA":
        falla.append("aún no confirma la ruptura")

    if not cot:
        falla.append("no se pudo cotizar el contrato real")
    if not h or h.get("sin_datos"):
        falla.append("sin histórico para juzgarla")

    if cot and h and not h.get("sin_datos"):
        tp = (s.get("opcion") or {}).get("tipo", "CALL")
        if ve is None:
            ve = opcion_real.valor_esperado(s["precio"], cot, h["targets"],
                                            s.get("mfe_max") or 0, tp)
        if p2 is None:
            p2 = opcion_real.prob_de_multiplo(s["precio"], cot, h["targets"], 2, tp)
        n = h.get("n", 0)

        if ve is None or ve < VE_MINIMO:
            falla.append(f"ventaja insuficiente (×{ve}; se pide ×{VE_MINIMO})")
        # Probabilidad de doblar: 50%... O una apuesta ASIMÉTRICA (ventaja alta con
        # algo de chance del gran salto). El oro es el caso: dobla 31% pero VE 2.0+.
        asimetrica = (ve is not None and ve >= VE_ASIMETRICO
                      and p2 is not None and p2 >= PROB_X2_PISO_ASIM)
        if (p2 is None or p2 < PROB_X2_MINIMA) and not asimetrica:
            falla.append(f"probabilidad de doblar baja ({p2:.0f}%; se pide {PROB_X2_MINIMA}% "
                         f"o ventaja ×{VE_ASIMETRICO}+ para apuesta asimétrica)")
        if n < MUESTRA_MINIMA:
            falla.append(f"muestra muy chica ({n} casos; se piden {MUESTRA_MINIMA})")

    if earnings_riesgo:
        falla.append("reporte de resultados dentro de la vida de la opción")

    return (len(falla) == 0), falla
