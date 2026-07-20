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
        if p2 is None or p2 < PROB_X2_MINIMA:
            falla.append(f"probabilidad de doblar baja ({p2:.0f}%; se pide {PROB_X2_MINIMA}%)")
        if n < MUESTRA_MINIMA:
            falla.append(f"muestra muy chica ({n} casos; se piden {MUESTRA_MINIMA})")

    if earnings_riesgo:
        falla.append("reporte de resultados dentro de la vida de la opción")

    return (len(falla) == 0), falla
